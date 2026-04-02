import socket
from unittest.mock import patch

from agent import __main__ as agent_main


def test_host_id_derived_from_hostname(mocker):
    mocker.patch("socket.gethostname", return_value="my-server")
    mocker.patch("agent.__main__.connect_with_backoff", return_value=None)
    mocker.patch("agent.__main__.run_scheduler")
    mocker.patch.dict("os.environ", {"DATABASE_URL": "postgresql://x:x@localhost/x"})

    agent_main.main()

    agent_main.run_scheduler.assert_called_once()
    _, kwargs = agent_main.run_scheduler.call_args
    assert kwargs["host_id"] == "my-server"


def test_host_id_stable_across_calls():
    """host_id from gethostname() is the same on repeated calls within a session."""
    id_1 = socket.gethostname()
    id_2 = socket.gethostname()
    assert id_1 == id_2
    assert len(id_1) > 0
