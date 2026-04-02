from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest

from agent.scheduler import run_collection_cycle
from shared.types import DeviceInfo, SmartResult, WriteResult


def _mock_deps(
    devices: list[str] | None = None,
    detected_type: str = "sat",
    flags: list[str] | None = None,
    health_status: str = "PASSED",
    smart_error: str | None = None,
    write_success: bool = True,
):
    """Return a dict of patched callables for the scheduler's dependencies."""
    devices = devices if devices is not None else ["/dev/sda"]
    flags = flags or ["--device=sat"]

    mock_list = MagicMock(return_value=devices)
    mock_detect = MagicMock(
        return_value=DeviceInfo(device_path=devices[0] if devices else "/dev/sda",
                                detected_type=detected_type,
                                smartctl_flags=flags)
    )
    mock_collect = MagicMock(
        return_value=SmartResult(
            device_path=devices[0] if devices else "/dev/sda",
            device_type=detected_type,
            flags_used=flags,
            health_status=health_status,
            raw_output="{}",
            error=smart_error,
        )
    )
    mock_write = MagicMock(
        return_value=[WriteResult(device_path=devices[0] if devices else "/dev/sda", success=write_success)]
    )
    mock_upsert = MagicMock()
    return {
        "list_block_devices": mock_list,
        "detect_flags": mock_detect,
        "collect_device": mock_collect,
        "write_readings": mock_write,
        "upsert_host": mock_upsert,
    }


def _run_with_mocks(mocks: dict, **kwargs):
    with (
        patch("agent.scheduler.list_block_devices", mocks["list_block_devices"]),
        patch("agent.scheduler.detect_flags", mocks["detect_flags"]),
        patch("agent.scheduler.collect_device", mocks["collect_device"]),
        patch("agent.scheduler.write_readings", mocks["write_readings"]),
        patch("agent.scheduler.upsert_host", mocks["upsert_host"]),
    ):
        run_collection_cycle(host_id="test-host", conn=MagicMock(), **kwargs)


# --- Unit tests ---


def test_full_cycle_calls_all_stages():
    mocks = _mock_deps()
    _run_with_mocks(mocks)

    mocks["list_block_devices"].assert_called_once()
    mocks["detect_flags"].assert_called_once_with("/dev/sda", timeout_seconds=30)
    mocks["collect_device"].assert_called_once()
    mocks["write_readings"].assert_called_once()
    mocks["upsert_host"].assert_called_once()


def test_write_readings_receives_device_reading():
    mocks = _mock_deps(health_status="PASSED")
    _run_with_mocks(mocks)

    args, _ = mocks["write_readings"].call_args
    readings = args[0]
    assert len(readings) == 1
    assert readings[0].host_id == "test-host"
    assert readings[0].device_path == "/dev/sda"
    assert readings[0].health_status == "PASSED"


def test_timed_out_device_not_written_to_db():
    """FM-1: timed-out devices must not be written to the database."""
    mocks = _mock_deps(smart_error="timeout")
    _run_with_mocks(mocks)

    args, _ = mocks["write_readings"].call_args
    readings = args[0]
    assert readings == []


def test_smartctl_not_found_device_not_written():
    mocks = _mock_deps(smart_error="smartctl_not_found")
    _run_with_mocks(mocks)

    args, _ = mocks["write_readings"].call_args
    readings = args[0]
    assert readings == []


def test_no_devices_skips_cycle():
    mocks = _mock_deps(devices=[])
    _run_with_mocks(mocks)

    mocks["detect_flags"].assert_not_called()
    mocks["collect_device"].assert_not_called()
    mocks["write_readings"].assert_not_called()


def test_multiple_devices_all_processed():
    devices = ["/dev/sda", "/dev/sdb", "/dev/nvme0"]
    mocks = _mock_deps(devices=devices)

    # Make detect and collect return appropriate values per device
    mocks["detect_flags"].side_effect = [
        DeviceInfo(d, "sat", ["--device=sat"]) for d in devices
    ]
    mocks["collect_device"].side_effect = [
        SmartResult(d, "sat", ["--device=sat"], "PASSED", "{}", None) for d in devices
    ]
    mocks["write_readings"].return_value = [
        WriteResult(d, success=True) for d in devices
    ]

    _run_with_mocks(mocks)

    assert mocks["detect_flags"].call_count == 3
    assert mocks["collect_device"].call_count == 3
    args, _ = mocks["write_readings"].call_args
    assert len(args[0]) == 3


def test_device_timeout_forwarded_to_detect_and_collect():
    mocks = _mock_deps()
    _run_with_mocks(mocks, device_timeout_seconds=15)

    mocks["detect_flags"].assert_called_once_with("/dev/sda", timeout_seconds=15)
    _, detect_kwargs = mocks["collect_device"].call_args
    assert detect_kwargs.get("timeout_seconds") == 15 or mocks["collect_device"].call_args[0][1] == 15


def test_collected_at_is_utc():
    mocks = _mock_deps()
    _run_with_mocks(mocks)

    args, _ = mocks["write_readings"].call_args
    reading = args[0][0]
    assert reading.collected_at.tzinfo is not None
    assert reading.collected_at.tzinfo == timezone.utc


def test_upsert_host_called_with_host_id():
    mocks = _mock_deps()
    _run_with_mocks(mocks)

    args, _ = mocks["upsert_host"].call_args
    assert args[0] == "test-host"


def test_upsert_host_called_before_write_readings():
    """Critical fix: host row must exist before device_reading FK insert."""
    call_order = []
    mocks = _mock_deps()
    mocks["upsert_host"].side_effect = lambda *a, **kw: call_order.append("upsert_host")
    mocks["write_readings"].side_effect = lambda *a, **kw: call_order.append("write_readings") or [
        WriteResult(device_path="/dev/sda", success=True)
    ]

    _run_with_mocks(mocks)

    assert call_order.index("upsert_host") < call_order.index("write_readings"), (
        "upsert_host must be called before write_readings to satisfy FK constraint"
    )


def test_cycle_continues_after_component_exception():
    """Unhandled errors in the cycle must not propagate out of run_collection_cycle."""
    mocks = _mock_deps()
    mocks["detect_flags"].side_effect = RuntimeError("unexpected")

    # Should not raise
    _run_with_mocks(mocks)
