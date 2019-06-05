from copy import copy
import logging
from pathlib import Path
import sys
from typing import cast, Dict, List, Optional, Tuple, Type, Union

from ymmsl import (Conduit, Identifier, Operator, ParameterValue, Port,
                   Reference)

from libmuscle.communicator import _ClosePort, Communicator, Message
from libmuscle.configuration import Configuration
from libmuscle.configuration_store import ConfigurationStore
from libmuscle.logging_handler import MuscleManagerHandler
from libmuscle.mmp_client import MMPClient
from libmuscle.profiler import Profiler
from libmuscle.profiling import ProfileEvent, ProfileEventType


class ComputeElement:
    """Represents a Compute Element instance in a MUSCLE3 simulation.

    This class provides a low-level send/receive API for the instance
    to use.
    """
    def __init__(self, instance: str,
                 ports: Optional[Dict[Operator, List[str]]]=None
                 ) -> None:
        """Create a ComputeElement.

        Args:
            name: The name of the instance represented by this object.
            ports: A list of port names for each operator of this
                compute element.
        """
        # Note that these are accessed by Muscle3, but otherwise private.
        self._name, self._index = self.__make_full_name(Reference(instance))
        """Name and index of this compute element."""

        mmp_location = self.__extract_manager_location()
        self.__manager = MMPClient(mmp_location)
        """Client object for talking to the manager."""

        self.__set_up_logging()

        self._profiler = Profiler(self._instance_name(), self.__manager)
        """Profiler for this instance."""

        self._communicator = Communicator(
                self._name, self._index, ports, self._profiler)
        """Communicator for this instance."""

        self._declared_ports = ports
        """Declared ports for this instance."""

        self._configuration_store = ConfigurationStore()
        """Configuration (parameters) for this instance."""

        self._first_run = True
        """Keeps track of whether this is the first reuse run."""

        FInitCacheType = Dict[Tuple[str, Optional[int]], Message]
        self._f_init_cache = dict()     # type: FInitCacheType

        self._register()
        self._connect()

    def reuse_instance(self, apply_overlay: bool=True) -> bool:
        """Decide whether to run this instance again.

        In a multiscale simulation, instances get reused all the time.
        For example, in a macro-micro simulation, the micromodel does a
        complete run for every timestep of the macromodel. Rather than
        starting up a new instance of the micromodel, which could be
        expensive, we reuse a single instance many times.

        This may bring other advantages, such as faster convergence
        when starting from the previous final state, and in some
        cases may be necessary if micromodel state needs to be
        preserved from one macro timestep to the next.

        So in MUSCLE, submodels run in a *reuse loop*, which runs them
        over and over again until their work is done and they should be
        shut down. Whether to do another F_INIT, O_I, S, B, O_F cycle
        is decided by this method.

        This method must be called at the beginning of the reuse loop,
        i.e. before the F_INIT operator, and its return value should
        decide whether to enter that loop again.

        Args:
            apply_overlay: Whether to apply the received configuration
                overlay or to save it. If you're going to use
                :meth:`receive_with_parameters` on your F_INIT ports,
                set this to False. If you don't know what that means,
                just call `reuse_instance()` without specifying this
                and everything will be fine, this is only for some
                specific uses that you're probably not doing.
        """
        do_reuse = self.__receive_parameters()

        # TODO: _f_init_cache should be empty here, or the user didn't
        # receive something that was sent on the last go-around.
        # At least emit a warning.
        self.__pre_receive_f_init(apply_overlay)

        ports = self._communicator.list_ports()
        f_init_not_connected = all(
                [not self.is_connected(port)
                 for port in ports.get(Operator.F_INIT, [])])
        no_parameters_in = not self._communicator.parameters_in_connected()

        if f_init_not_connected and no_parameters_in:
            do_reuse = self._first_run
            self._first_run = False
        else:
            for message in self._f_init_cache.values():
                if isinstance(message.data, _ClosePort):
                    do_reuse = False

        if not do_reuse:
            self.__close_ports()
            self._communicator.shutdown()
            self._deregister()
        return do_reuse

    def get_parameter_value(self, name: str,
                            typ: Optional[str] = None
                            ) -> ParameterValue:
        """Returns the value of a model parameter.

        Args:
            name: The name of the parameter, without any instance
                    prefix.
            typ: The expected type of the value. If the value does
                    not match this type, a TypeError will be raised.
                    If not specified, any of the supported types
                    will be accepted, and you'll have to figure out
                    what you got yourself.

        Raises:
            KeyError: If no value was set for this parameter.
            TypeError: If the type of the parameter's value was not
                    as expected.
        """
        return self._configuration_store.get_parameter(
                self._instance_name(), Reference(name), typ)

    def list_ports(self) -> Dict[Operator, List[str]]:
        """Returns a description of the ports that this CE has.

        Note that the result has almost the same format as the port
        declarations you pass when making a ComputeElement. The only
        difference is that the port names never have `[]` at the end,
        even if the port is a vector port.

        This method will return an empty dictionary if _connect() has
        not yet been called.

        Returns:
            A dictionary, indexed by Operator, containing lists of
            port names. Operators with no associated ports are not
            included.
        """
        return self._communicator.list_ports()

    def is_connected(self, port: str) -> bool:
        """Returns whether the given port is connected.

        Args:
            port: The name of the port to inspect.

        Returns:
            True if there is a conduit attached to this port, False
            if not.
        """
        return self._communicator.get_port(port).is_connected()

    def is_vector_port(self, port: str) -> bool:
        """Returns whether a port is a vector or scalar port

        If a port has been declared to be a vector port (i.e. the
        name passed when creating this ComputeElement had '[]' at the
        end), then you can pass a 'slot' argument when sending or
        receiving. It's like the port is a vector of slots on which
        you can send or receive messages.

        This function returns True if the given port is a vector
        port, and False if it is a scalar port.

        Args:
            port: The port to check this property of.
        """
        return self._communicator.get_port(port).is_vector()

    def is_resizable(self, port: str) -> bool:
        """Returns whether the given port is resizable.

        Scalar ports are never resizable. Whether a vector port is
        resizable depends on what it is connected to.

        Args:
            port: Name of the port to inspect.

        Returns:
            True if the port can be resized.
        """
        return self._communicator.get_port(port).is_resizable()

    def get_port_length(self, port: str) -> int:
        """Returns the current length of the port.

        Args:
            port: The name of the port to measure.

        Raises: RuntimeError if this is a scalar port.
        """
        return self._communicator.get_port(port).get_length()

    def set_port_length(self, port: str, length: int) -> None:
        """Resizes the port to the given length.

        You should check whether the port is resizable using
        `is_resizable()` first; whether it is depends on how this
        compute element is wired up, so you should check.

        Args:
            port: Name of the port to resize.
            length: The new length.

        Raises:
            RuntimeError: If the port is not resizable.
        """
        self._communicator.get_port(port).set_length(length)

    def send_message(self, port_name: str, message: Message,
                     slot: Optional[int]=None) -> None:
        """Send a message to the outside world.

        Sending is non-blocking, a copy of the message will be made
        and stored until the receiver is ready to receive it.

        Args:
            port_name: The port on which this message is to be sent.
            message: The message to be sent.
            slot: The slot to send the message on, if any.
        """
        self.__check_port(port_name)
        if message.configuration is None:
            message = copy(message)
            message.configuration = self._configuration_store.overlay

        self._communicator.send_message(port_name, message, slot)

    def receive_message(self, port_name: str, slot: Optional[int]=None,
                        default: Optional[Message]=None
                        ) -> Message:
        """Receive a message from the outside world.

        Receiving is a blocking operation. This function will contact
        the sender, wait for a message to be available, and receive and
        return it.

        If the port you are receiving on is not connected, the default
        value you specified will be returned exactly as you passed it.
        If you didn't specify a default value (e.g. because there is no
        reasonable default, you really need the outside input) and the
        port is not connected, you'll get a RuntimeError.

        Args:
            port_name: The endpoint on which a message is to be
                    received.
            slot: The slot to receive the message on, if any.
            default: A default value to return if this port is not
                    connected.

        Returns:
            The received message.The configuration attribute of the
            received message will be None.

        Raises:
            RuntimeError: If the given port is not connected and no
                    default value was given.
        """
        return self.__receive_message(port_name, slot, default, False)

    def receive_message_with_parameters(
            self, port_name: str, slot: Optional[int]=None,
            default: Optional[Message]=None
            ) -> Message:
        """Receive a message with attached parameter overlay.

        This function should not be used in submodels. It is intended
        for use by special compute elements that are ensemble-aware and
        have to pass on overlay parameter sets explicitly.

        Receiving is a blocking operaton. This function will contact
        the sender, wait for a message to be available, and receive and
        return it.

        If the port you are receiving on is not connected, the default
        value you specified will be returned exactly as you passed it.
        If you didn't specify a default value (e.g. because there is no
        reasonable default, and you really need the outside input) and
        the port is not connected, then you'll get a RuntimeError.

        Args:
            port_name: The endpoint on which a message is to be
                    received.
            slot: The slot to receive the message on, if any.
            default: A default value to return if this port is not
                    connected.

        Returns:
            The received message. The configuration attribute will
            contain the received Configuration, and will not be None.

        Raises:
            RuntimeError: If the given port is not connected and no
                    default value was given.
        """
        return self.__receive_message(port_name, slot, default, True)

    def _register(self) -> None:
        """Register this compute element with the manager.
        """
        register_event = self._profiler.start(ProfileEventType.REGISTER)
        locations = self._communicator.get_locations()
        port_list = self.__list_declared_ports()
        self.__manager.register_instance(self._instance_name(), locations,
                                         port_list)
        register_event.stop()

    def _connect(self) -> None:
        """Connect this compute element to the given peers / conduits.
        """
        connect_event = self._profiler.start(ProfileEventType.CONNECT)
        conduits, peer_dims, peer_locations = self.__manager.request_peers(
                self._instance_name())
        self._communicator.connect(conduits, peer_dims, peer_locations)
        self._configuration_store.base = self.__manager.get_configuration()
        connect_event.stop()

    def _deregister(self) -> None:
        """Deregister this instance from the manager.
        """
        deregister_event = self._profiler.start(ProfileEventType.DEREGISTER)
        self.__manager.deregister_instance(self._instance_name())
        deregister_event.stop()
        # this is the last thing we'll profile, so flush messages
        self._profiler.shutdown()

    @staticmethod
    def __extract_manager_location() -> str:
        """Gets the manager network location from the command line.

        We use a --muscle-manager=<host:port> argument to tell the
        MUSCLE library how to connect to the manager. This function
        will extract this argument from the command line arguments,
        if it is present.

        Returns:
            A connection string, or None.
        """
        # Neither getopt, optparse, or argparse will let me pick out
        # just one option from the command line and ignore the rest.
        # So we do it by hand.
        prefix = '--muscle-manager='
        for arg in sys.argv[1:]:
            if arg.startswith(prefix):
                return arg[len(prefix):]

        return 'localhost:9000'

    def __set_up_logging(self) -> None:
        """Adds logging handlers for one or more instances.
        """
        id_str = str(self._instance_name())

        logfile = self.__extract_log_file_location(
                'muscle3.{}.log'.format(id_str))
        local_handler = logging.FileHandler(str(logfile), mode='w')
        logging.getLogger().addHandler(local_handler)

        if self.__manager is not None:
            mmp_handler = MuscleManagerHandler(id_str, logging.WARNING,
                                               self.__manager)
            logging.getLogger().addHandler(mmp_handler)

    @staticmethod
    def __extract_log_file_location(filename: str) -> Optional[Path]:
        """Gets the log file location from the command line.

        Extracts the --muscle-log-file=<path> argument to tell the
        MUSCLE library where to write the local log file. This
        function will extract this argument from the command line
        arguments if it is present. If the given path is to a
        directory, <filename> will be written inside of that directory,
        if the path is not an existing directory, then it will be used
        as the name of the log file to write to. If no command line
        argument is given, <filename> will be written in the current
        directory.

        Args:
            filename: Default file name to use.

        Returns:
            Path to the log file to write.
        """
        # Neither getopt, optparse, or argparse will let me pick out
        # just one option from the command line and ignore the rest.
        # So we do it by hand.
        prefix = '--muscle-log-file='
        given_path_str = ''
        for arg in sys.argv[1:]:
            if arg.startswith(prefix):
                given_path_str = arg[len(prefix):]

        if given_path_str == '':
            return Path('.') / filename

        given_path = Path(given_path_str)

        if given_path.is_dir():
            return given_path / filename
        return given_path

    def __receive_message(
            self, port_name: str, slot: Optional[int],
            default: Optional[Message], with_parameters: bool
            ) -> Message:
        """Receives a message on the given port.

        This implements receive_message and
        receive_message_with_parameters, see the description of those.
        """
        self.__check_port(port_name)

        port = self._communicator.get_port(port_name)
        if port.operator == Operator.F_INIT:
            if (port_name, slot) in self._f_init_cache:
                msg = self._f_init_cache[(port_name, slot)]
                del(self._f_init_cache[(port_name, slot)])
                if with_parameters and msg.configuration is None:
                    raise RuntimeError('If you use receive_with_parameters()'
                                       ' on an F_INIT port, then you have to'
                                       ' pass False to reuse_instance(),'
                                       ' otherwise the parameters will already'
                                       ' have been applied by MUSCLE.')
            else:
                if port.is_connected():
                    raise RuntimeError(('Tried to receive twice on the same'
                                        ' port "{}", that\'s not possible.'
                                        ' Did you forget to call'
                                        ' reuse_instance() in your reuse loop?'
                                        ).format(port_name))
                else:
                    if default is not None:
                        return default
                    raise RuntimeError(('Tried to receive on port "{}",'
                                        ' which is not connected, and no'
                                        ' default value was given. Please'
                                        ' connect this port!').format(
                                            port_name))

        else:
            msg = self._communicator.receive_message(
                    port_name, slot, default)
            if not with_parameters:
                self.__check_compatibility(port_name, msg.configuration)
                msg.configuration = None
        return msg

    def __make_full_name(self, instance: Reference
                         ) -> Tuple[Reference, List[int]]:
        """Returns instance name and index.

        The given instance string is split into a compute element and
        an index, which are returned.

        If a --muscle-index=x,y,z is given on the command line, then
        it is parsed and prepended on the index. If there is no
        --muscle-index on the command line, and instance does not
        contain an index either, then this returns an empty list for
        the second item.
        """
        # Neither getopt, optparse, or argparse will let me pick out
        # just one option from the command line and ignore the rest.
        # So we do it by hand.
        index = list()     # type: List[int]
        prefix = '--muscle-index='
        for arg in sys.argv[1:]:
            if arg.startswith(prefix):
                index_str = arg[len(prefix):]
                indices = index_str.split(',')
                index += map(int, indices)
                break

        i = 0
        while i < len(instance) and isinstance(instance[i], Identifier):
            i += 1
        kernel = instance[:i]

        while i < len(instance) and isinstance(instance[i], int):
            index.append(cast(int, instance[i]))
            i += 1

        return kernel, index

    def __list_declared_ports(self) -> List[Port]:
        """Returns a list of declared ports.

        This returns a list of ymmsl.Port objects, which have only the
        name and the operator, not libmuscle.Port, which has more.
        """
        result = list()
        if self._declared_ports is not None:
            for operator, port_names in self._declared_ports.items():
                for name in port_names:
                    if name.endswith('[]'):
                        name = name[:-2]
                    result.append(Port(Identifier(name), operator))
        return result

    def _instance_name(self) -> Reference:
        """Returns the full instance name.
        """
        return self._name + self._index

    def __check_port(self, port_name: str) -> None:
        if not self._communicator.port_exists(port_name):
            raise ValueError(('Port "{}" does not exist on "{}". Please check'
                              ' the name and the list of ports you gave for'
                              ' this compute element.').format(port_name,
                                                               self._name))

    def __receive_parameters(self) -> bool:
        """Receives parameters on muscle_parameters_in.

        Returns:
            False iff the port is connnected and ClosePort was received.
        """
        default_message = Message(0.0, None, Configuration(), Configuration())
        message = self._communicator.receive_message(
                'muscle_parameters_in', None, default_message)
        if isinstance(message.data, _ClosePort):
            return False
        if not isinstance(message.data, Configuration):
            raise RuntimeError('"{}" received a message on'
                               ' muscle_parameters_in that is not a'
                               ' Configuration. It seems that your'
                               ' simulation is miswired or the sending'
                               ' instance is broken.'.format(
                                   self._instance_name()))

        configuration = cast(Configuration, message.configuration)
        for key, value in message.data.items():
            configuration[key] = value
        self._configuration_store.overlay = configuration
        return True

    def __pre_receive_f_init(self, apply_overlay: bool) -> None:
        """Receives on all ports connected to F_INIT.

        This receives all incoming messages on F_INIT and stores them
        in self._f_init_cache.
        """
        def pre_receive(port_name: str, slot: Optional[int]) -> None:
            msg = self._communicator.receive_message(port_name)
            self._f_init_cache[(port_name, slot)] = msg
            if apply_overlay:
                self.__apply_overlay(msg)
                self.__check_compatibility(port_name, msg.configuration)
                msg.configuration = None

        self._f_init_cache = dict()
        ports = self._communicator.list_ports()
        for port_name in ports.get(Operator.F_INIT, []):
            port = self._communicator.get_port(port_name)
            if not port.is_connected():
                continue
            if not port.is_vector():
                pre_receive(port_name, None)
            else:
                pre_receive(port_name, 0)
                # The above receives the length, if needed, so now we can
                # get the rest.
                for slot in range(1, port.get_length()):
                    pre_receive(port_name, slot)

    def __apply_overlay(self, message: Message) -> None:
        """Sets local overlay if we don't already have one.

        Args:
            message: The message to apply the overlay from.
        """
        if len(self._configuration_store.overlay) == 0:
            if message.configuration is not None:
                self._configuration_store.overlay = message.configuration

    def __check_compatibility(self, port_name: str,
                              overlay: Optional[Configuration]) -> None:
        """Checks whether a received overlay matches the current one.

        Args:
            port_name: Name of the port on which the overlay was
                    received.
            overlay: The received overlay.
        """
        if overlay is None:
            return
        if self._configuration_store.overlay != overlay:
            raise RuntimeError(('Unexpectedly received data from a'
                                ' parallel universe on port "{}". My'
                                ' parameters are "{}" and I received'
                                ' from a universe with "{}".').format(
                                    port_name,
                                    self._configuration_store.overlay,
                                    overlay))

    def __close_outgoing_ports(self) -> None:
        """Closes outgoing ports.

        This sends a close port message on all slots of all outgoing
        ports.
        """
        for operator, ports in self._communicator.list_ports().items():
            if operator.allows_sending():
                for port_name in ports:
                    port = self._communicator.get_port(port_name)
                    if port.is_vector():
                        for slot in range(port.get_length()):
                            self._communicator.close_port(port_name, slot)
                    else:
                        self._communicator.close_port(port_name)

    def __drain_incoming_port(self, port_name: str) -> None:
        """Receives messages until a ClosePort is received.

        Receives at least once.

        Args:
            port_name: Port to drain.
        """
        msg = self._communicator.receive_message(port_name)
        while not isinstance(msg.data, _ClosePort):
            # TODO: log warning if not a ClosePort
            msg = self._communicator.receive_message(port_name)

    def __drain_incoming_vector_port(self, port_name: str) -> None:
        """Receives messages until a ClosePort is received.

        Receives at least once, and works with (resizable) vector
        ports.

        Args:
            port_name: Port to drain.
        """
        port = self._communicator.get_port(port_name)

        msg = self._communicator.receive_message(port_name, 0)
        for slot in range(1, port.get_length()):
            self._communicator.receive_message(port_name, slot)
        while not isinstance(msg.data, _ClosePort):
            # TODO: log warning if not a ClosePort
            msg = self._communicator.receive_message(port_name, 0)
            for slot in range(1, port.get_length()):
                self._communicator.receive_message(port_name, slot)

    def __drain_f_init_port(self, port_name: str) -> None:
        """Receives messages until a ClosePort is received.

        Version for F_INIT ports, which have the cache to contend with.

        Args:
            port_name: Port to drain.
        """
        if (port_name, None) in self._f_init_cache:
            msg = self._f_init_cache[(port_name, None)]
            del(self._f_init_cache[(port_name, None)])
            if not isinstance(msg.data, _ClosePort):
                self.__drain_incoming_port(port_name)
        elif (port_name, 0) in self._f_init_cache:
            port = self._communicator.get_port(port_name)
            msg = self._f_init_cache[(port_name, 0)]
            del(self._f_init_cache[(port_name, 0)])
            for slot in range(port.get_length()):
                del(self._f_init_cache[(port_name, slot)])
            if not isinstance(msg.data, _ClosePort):
                self.__drain_incoming_port(port_name)

    def __close_incoming_ports(self) -> None:
        """Closes incoming ports.

        This receives on all incoming ports until a ClosePort is
        received on them, signaling that there will be no more
        messages, and allowing the sending instance to shut down
        cleanly.
        """
        for operator, port_names in self._communicator.list_ports().items():
            if operator == Operator.F_INIT:
                pass
            elif operator.allows_receiving():
                for port_name in port_names:
                    port = self._communicator.get_port(port_name)
                    if not port.is_connected():
                        continue
                    if not port.is_vector():
                        self.__drain_incoming_port(port_name)
                    else:
                        self.__drain_incoming_vector_port(port_name)

    def __close_ports(self) -> None:
        """Closes all ports.

        This sends a close port message on all slots of all outgoing
        ports, then receives one on all incoming ports.
        """
        self.__close_outgoing_ports()
        self.__close_incoming_ports()
