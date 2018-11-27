import pytest
from unittest.mock import patch

from libmuscle.mmp_client import MMPClient


@pytest.fixture
def mock_grpc_channel():
    with patch('grpc.insecure_channel'):
        yield None


@pytest.fixture
def mocked_mmp_client(mock_grpc_channel):
    with patch('grpc.insecure_channel'), \
         patch('libmuscle.mmp_client.grpc.channel_ready_future'), \
         patch('muscle_manager_protocol.' +
               'muscle_manager_protocol_pb2_grpc.MuscleManagerStub'
               ) as mock_stub:

        stub = mock_stub.return_value
        yield MMPClient(''), stub