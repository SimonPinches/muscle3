import multiprocessing as mp
from multiprocessing.connection import Connection
from typing import Dict, Tuple
import uuid

from ymmsl import Reference


class _InstancePipes:
    """Pipes for communicating between an instance and the mux.

    Objects of this class contain the endpoints for a set of two pipes
    that is used to communicate between the instance processes and the
    multiplexer. The multiplexer (in this module) facilitates the
    creation of peer-to-peer pipe connections between the processes.

    For each instance there is a server pipe, on which the instance
    listens for incoming connection requests, and a client pipe,
    through which an instance asks the multiplexer to create a
    connection to another instance.

    Attributes:
        server_mux_conn: Mux side of the server pipe.
        server_instance_conn: Instance side of the server pipe.
        client_mux_conn: Mux side of the client pipe
        client_instance_conn: Instance side of the client pipe.
    """
    def __init__(self) -> None:
        """Create an InstancePipes containing two new pipes.
        """
        self.server_mux_conn, self.server_instance_conn = mp.Pipe()
        self.client_mux_conn, self.client_instance_conn = mp.Pipe()

    def close_mux_ends(self) -> None:
        """Closes the mux ends of both the pipes.
        """
        self.server_mux_conn.close()
        self.client_mux_conn.close()

    def close_instance_ends(self) -> None:
        """Closes the instance ends of both the pipes.
        """
        self.server_instance_conn.close()
        self.client_instance_conn.close()


_instance_pipes = dict()     # type: Dict[Reference, _InstancePipes]


def add_instance(instance_id: Reference) -> None:
    """Adds pipes for an instance.

    Args:
        instance_id: Name of the new instance.
    """
    _instance_pipes[instance_id] = _InstancePipes()


def can_communicate_for(instance_id: Reference) -> bool:
    """Returns whether we can serve on pipes for this instance.

    If the instance was not started via Muscle3, then it will not be
    registered, and we cannot start a PipeServer for it. That's fine,
    but we need to know.

    Args:
        instance_id: Name of the requested instance.
    """
    return instance_id in _instance_pipes


def close_instance_ends(instance_id: Reference) -> None:
    """Closes the instance sides of the pipes for the given instance.

    Args:
        instance_id: The instance to close for.
    """
    _instance_pipes[instance_id].close_instance_ends()


def get_pipes_for_instance(name: Reference) -> Tuple[Connection, Connection]:
    """Returns the instance sides of the pipes for this instance.

    Returns:
        A tuple (server_conn, client_conn) of Connections.
    """
    pipes = _instance_pipes[name]
    pipes.close_mux_ends()
    return pipes.server_instance_conn, pipes.client_instance_conn


_process_uuid = uuid.uuid4()


def get_address_for(instance_id: Reference) -> str:
    """Returns the MUSCLE-address for the given instance.

    Args:
        instance_id: Id of the instance to get the address for.

    Returns:
        An address string that can be passed to the MUSCLE Manager.
    """
    return '{}/{}'.format(_process_uuid, instance_id)


def can_connect_to(peer_address: str) -> bool:
    """Checks whether this multiplexer can make connections for the address.

    This does not check whether the peer is up and running and
    listening, just that it's in the right process tree.

    Args:
        peer_address: An address of the form <uuid>/<instance_id>.
    """
    peer_uuid = peer_address.split('/')[0]
    return peer_uuid == str(_process_uuid)