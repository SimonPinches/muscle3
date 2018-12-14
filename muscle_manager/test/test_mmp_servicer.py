from muscle_manager.mmp_server import MMPServicer
import muscle_manager_protocol.muscle_manager_protocol_pb2 as mmp
from google.protobuf.timestamp_pb2 import Timestamp

from ymmsl import Operator


def test_create_servicer(logger, instance_registry):
    MMPServicer(logger, instance_registry)


def test_log_message(mmp_servicer, caplog):
    timestamp = Timestamp()
    timestamp.FromJsonString("1970-01-01T00:00:00.000Z")
    message = mmp.LogMessage(
            instance_id='test_instance_id',
            operator=mmp.OPERATOR_B,
            timestamp=timestamp,
            level=mmp.LOG_LEVEL_WARNING,
            text='Testing log message')
    result = mmp_servicer.SubmitLogMessage(message, None)
    assert isinstance(result, mmp.LogResult)
    assert caplog.records[0].name == 'test_instance_id'
    assert caplog.records[0].operator == 'B'
    assert caplog.records[0].time_stamp == '1970-01-01T00:00:00Z'
    assert caplog.records[0].levelname == 'WARNING'
    assert caplog.records[0].message == 'Testing log message'


def test_register_instance(mmp_servicer, instance_registry):
    port = mmp.Port(name='test_in', operator=mmp.OPERATOR_F_INIT)
    request = mmp.RegistrationRequest(
            instance_name='test_instance',
            network_locations=['tcp://localhost:10000'],
            ports=[port])

    result = mmp_servicer.RegisterInstance(request, None)

    assert result.status == mmp.RESULT_STATUS_SUCCESS
    assert (instance_registry._InstanceRegistry__locations['test_instance'] ==
            ['tcp://localhost:10000'])

    registered_ports = instance_registry._InstanceRegistry__ports
    assert registered_ports['test_instance'][0].name == 'test_in'
    assert registered_ports['test_instance'][0].operator == Operator.F_INIT


def test_double_register_instance(mmp_servicer, instance_registry):
    port = mmp.Port(name='test_in', operator=mmp.OPERATOR_F_INIT)
    request = mmp.RegistrationRequest(
            instance_name='test_instance',
            network_locations=['tcp://localhost:10000'],
            ports=[port])

    result = mmp_servicer.RegisterInstance(request, None)
    assert result.status == mmp.RESULT_STATUS_SUCCESS

    result = mmp_servicer.RegisterInstance(request, None)
    assert result.status == mmp.RESULT_STATUS_ERROR
    assert 'test_instance' in result.error_message
