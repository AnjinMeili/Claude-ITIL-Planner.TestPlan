import subprocess
from unittest.mock import MagicMock

import pytest

from agent.enumerator import list_block_devices


def _mock_run(stdout: str, returncode: int = 0) -> MagicMock:
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = ""
    return result


# --- Unit tests (mocked subprocess) ---


def test_returns_device_paths(mocker):
    mocker.patch("subprocess.run", return_value=_mock_run("sda\nnvme0\n"))
    devices = list_block_devices()
    assert devices == ["/dev/sda", "/dev/nvme0"]


def test_skips_blank_lines(mocker):
    mocker.patch("subprocess.run", return_value=_mock_run("sda\n\nsdb\n"))
    devices = list_block_devices()
    assert devices == ["/dev/sda", "/dev/sdb"]


def test_returns_empty_on_nonzero_exit(mocker):
    mocker.patch("subprocess.run", return_value=_mock_run("", returncode=1))
    devices = list_block_devices()
    assert devices == []


def test_returns_empty_when_lsblk_not_found(mocker):
    mocker.patch("subprocess.run", side_effect=FileNotFoundError)
    devices = list_block_devices()
    assert devices == []


def test_returns_empty_on_timeout(mocker):
    mocker.patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="lsblk", timeout=10))
    devices = list_block_devices()
    assert devices == []


def test_single_device(mocker):
    mocker.patch("subprocess.run", return_value=_mock_run("sda\n"))
    devices = list_block_devices()
    assert devices == ["/dev/sda"]


# --- Integration test (real lsblk, Linux only) ---


@pytest.mark.integration
def test_returns_at_least_one_device_on_linux():
    """Requires lsblk to be available and at least one block device present."""
    devices = list_block_devices()
    assert len(devices) >= 1
    for d in devices:
        assert d.startswith("/dev/")
