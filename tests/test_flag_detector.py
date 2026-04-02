import json
import subprocess
from unittest.mock import MagicMock

import pytest

from agent.flag_detector import detect_flags


def _mock_run(device_type: str | None, returncode: int = 0) -> MagicMock:
    """Build a mock subprocess result with a smartctl -i -j style JSON payload."""
    if device_type is not None:
        payload = {"device": {"type": device_type}}
    else:
        payload = {}
    result = MagicMock()
    result.returncode = returncode
    result.stdout = json.dumps(payload)
    result.stderr = ""
    return result


# --- Unit tests ---


def test_sata_device_returns_sat_flag(mocker):
    mocker.patch("subprocess.run", return_value=_mock_run("sat"))
    info = detect_flags("/dev/sda")
    assert info.detected_type == "sat"
    assert info.smartctl_flags == ["--device=sat"]
    assert info.device_path == "/dev/sda"


def test_nvme_device_returns_nvme_flag(mocker):
    mocker.patch("subprocess.run", return_value=_mock_run("nvme"))
    info = detect_flags("/dev/nvme0")
    assert info.detected_type == "nvme"
    assert info.smartctl_flags == ["--device=nvme"]


def test_scsi_device_returns_no_flags(mocker):
    mocker.patch("subprocess.run", return_value=_mock_run("scsi"))
    info = detect_flags("/dev/sdb")
    assert info.detected_type == "scsi"
    assert info.smartctl_flags == []


def test_usb_device_returns_sat_flag(mocker):
    mocker.patch("subprocess.run", return_value=_mock_run("usb"))
    info = detect_flags("/dev/sdc")
    assert info.detected_type == "usb"
    assert info.smartctl_flags == ["--device=sat"]


def test_ata_device_returns_no_flags(mocker):
    mocker.patch("subprocess.run", return_value=_mock_run("ata"))
    info = detect_flags("/dev/sda")
    assert info.detected_type == "ata"
    assert info.smartctl_flags == []


def test_unknown_type_returns_empty_flags(mocker):
    mocker.patch("subprocess.run", return_value=_mock_run("raid"))
    info = detect_flags("/dev/sda")
    assert info.detected_type == "raid"
    assert info.smartctl_flags == []


def test_missing_device_type_field_returns_unknown(mocker):
    result = MagicMock()
    result.returncode = 0
    result.stdout = json.dumps({})  # no device.type field
    result.stderr = ""
    mocker.patch("subprocess.run", return_value=result)
    info = detect_flags("/dev/sda")
    assert info.detected_type == "unknown"
    assert info.smartctl_flags == []


def test_invalid_json_returns_unknown(mocker):
    result = MagicMock()
    result.returncode = 1
    result.stdout = "not json"
    result.stderr = "some error"
    mocker.patch("subprocess.run", return_value=result)
    info = detect_flags("/dev/sda")
    assert info.detected_type == "unknown"
    assert info.smartctl_flags == []


def test_timeout_returns_unknown(mocker):
    mocker.patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="smartctl", timeout=30),
    )
    info = detect_flags("/dev/sda", timeout_seconds=30)
    assert info.detected_type == "unknown"
    assert info.smartctl_flags == []


def test_smartctl_not_found_returns_unknown(mocker):
    mocker.patch("subprocess.run", side_effect=FileNotFoundError)
    info = detect_flags("/dev/sda")
    assert info.detected_type == "unknown"
    assert info.smartctl_flags == []


def test_no_hardcoded_device_map(mocker):
    """AC-03-03: detection must not read a static device-to-flag mapping file."""
    mock_open = mocker.patch("builtins.open")
    mocker.patch("subprocess.run", return_value=_mock_run("sat"))
    detect_flags("/dev/sda")
    mock_open.assert_not_called()


def test_nonzero_exit_with_valid_json_still_returns_type(mocker):
    """smartctl may exit non-zero for advisory warnings but still return valid JSON."""
    mocker.patch("subprocess.run", return_value=_mock_run("sat", returncode=4))
    info = detect_flags("/dev/sda")
    assert info.detected_type == "sat"
    assert info.smartctl_flags == ["--device=sat"]


# --- Integration test ---


@pytest.mark.integration
def test_detects_type_on_real_device():
    """Requires sudo smartctl on a Linux host with at least one block device."""
    from agent.enumerator import list_block_devices

    devices = list_block_devices()
    assert devices, "No block devices found — cannot run integration test"

    info = detect_flags(devices[0])
    assert info.device_path == devices[0]
    assert info.detected_type != ""
