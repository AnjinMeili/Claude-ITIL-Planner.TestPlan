import json
import subprocess
from unittest.mock import MagicMock

import pytest

from agent.collector import collect_device
from shared.types import DeviceInfo


def _device(path: str = "/dev/sda", dtype: str = "sat", flags: list[str] | None = None) -> DeviceInfo:
    return DeviceInfo(device_path=path, detected_type=dtype, smartctl_flags=flags or ["--device=sat"])


def _mock_run(smart_status_passed: bool | None, returncode: int = 0, raw: str | None = None) -> MagicMock:
    if raw is not None:
        stdout = raw
    elif smart_status_passed is None:
        stdout = json.dumps({})  # no smart_status field
    else:
        stdout = json.dumps({"smart_status": {"passed": smart_status_passed}})
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = ""
    return result


# --- Unit tests ---


def test_healthy_device_returns_passed(mocker):
    mocker.patch("subprocess.run", return_value=_mock_run(True))
    r = collect_device(_device())
    assert r.health_status == "PASSED"
    assert r.error is None


def test_failed_device_returns_failed(mocker):
    mocker.patch("subprocess.run", return_value=_mock_run(False))
    r = collect_device(_device())
    assert r.health_status == "FAILED"
    assert r.error is None


def test_missing_smart_status_returns_unknown(mocker):
    mocker.patch("subprocess.run", return_value=_mock_run(None))
    r = collect_device(_device())
    assert r.health_status == "UNKNOWN"
    assert r.error is None


def test_invalid_json_returns_unknown_with_error(mocker):
    mocker.patch("subprocess.run", return_value=_mock_run(None, returncode=1, raw="not json"))
    r = collect_device(_device())
    assert r.health_status == "UNKNOWN"
    assert r.error is not None


def test_timeout_returns_unknown_with_timeout_error(mocker):
    mocker.patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="smartctl", timeout=30),
    )
    r = collect_device(_device(), timeout_seconds=30)
    assert r.health_status == "UNKNOWN"
    assert r.error == "timeout"


def test_smartctl_not_found_returns_unknown(mocker):
    mocker.patch("subprocess.run", side_effect=FileNotFoundError)
    r = collect_device(_device())
    assert r.health_status == "UNKNOWN"
    assert r.error == "smartctl_not_found"


def test_health_status_never_null(mocker):
    """FM-2: health_status must be non-null regardless of smartctl output."""
    for raw in ["{}", "not json", "", json.dumps({"smart_status": {}})]:
        mocker.patch("subprocess.run", return_value=_mock_run(None, raw=raw))
        r = collect_device(_device())
        assert r.health_status is not None
        assert r.health_status != ""


def test_device_fields_propagated(mocker):
    mocker.patch("subprocess.run", return_value=_mock_run(True))
    dev = _device(path="/dev/nvme0", dtype="nvme", flags=["--device=nvme"])
    r = collect_device(dev)
    assert r.device_path == "/dev/nvme0"
    assert r.device_type == "nvme"
    assert r.flags_used == ["--device=nvme"]


def test_raw_output_captured(mocker):
    payload = json.dumps({"smart_status": {"passed": True}, "extra": "data"})
    result = MagicMock()
    result.returncode = 0
    result.stdout = payload
    result.stderr = ""
    mocker.patch("subprocess.run", return_value=result)
    r = collect_device(_device())
    assert r.raw_output == payload


def test_no_flags_device(mocker):
    mocker.patch("subprocess.run", return_value=_mock_run(True))
    dev = DeviceInfo(device_path="/dev/sda", detected_type="scsi", smartctl_flags=[])
    r = collect_device(dev)
    assert r.health_status == "PASSED"
    assert r.flags_used == []


def test_nonzero_exit_with_valid_json_still_parses(mocker):
    """smartctl exits non-zero for advisory conditions but JSON may still be valid."""
    mocker.patch("subprocess.run", return_value=_mock_run(True, returncode=4))
    r = collect_device(_device())
    assert r.health_status == "PASSED"


# --- Integration test ---


@pytest.mark.integration
def test_collect_real_device():
    """Requires sudo smartctl on a Linux host with at least one block device."""
    from agent.enumerator import list_block_devices
    from agent.flag_detector import detect_flags

    devices = list_block_devices()
    assert devices, "No block devices found"

    device_info = detect_flags(devices[0])
    result = collect_device(device_info)

    assert result.health_status in ("PASSED", "FAILED", "UNKNOWN")
    assert result.health_status is not None
    assert result.device_path == devices[0]
