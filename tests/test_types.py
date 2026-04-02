from datetime import datetime, timezone

from shared.types import DeviceInfo, DeviceReading, SmartResult, WriteResult


def test_device_info_defaults():
    d = DeviceInfo(device_path="/dev/sda", detected_type="sata")
    assert d.device_path == "/dev/sda"
    assert d.detected_type == "sata"
    assert d.smartctl_flags == []


def test_device_info_with_flags():
    d = DeviceInfo(device_path="/dev/sda", detected_type="sata", smartctl_flags=["--device=sat"])
    assert d.smartctl_flags == ["--device=sat"]


def test_smart_result_defaults():
    r = SmartResult(
        device_path="/dev/sda",
        device_type="sata",
        flags_used=["--device=sat"],
        health_status="PASSED",
        raw_output="{}",
    )
    assert r.error is None
    assert r.health_status == "PASSED"


def test_smart_result_with_error():
    r = SmartResult(
        device_path="/dev/sda",
        device_type="unknown",
        flags_used=[],
        health_status="UNKNOWN",
        raw_output="",
        error="timeout",
    )
    assert r.error == "timeout"
    assert r.health_status == "UNKNOWN"


def test_device_reading_fields():
    now = datetime.now(tz=timezone.utc)
    dr = DeviceReading(
        host_id="host-a",
        device_path="/dev/nvme0",
        device_type="nvme",
        smart_flags_used="--device=nvme",
        health_status="PASSED",
        raw_output="{}",
        collected_at=now,
    )
    assert dr.host_id == "host-a"
    assert dr.health_status == "PASSED"
    assert dr.collected_at == now


def test_write_result_success():
    wr = WriteResult(device_path="/dev/sda", success=True)
    assert wr.success is True
    assert wr.error is None


def test_write_result_failure():
    wr = WriteResult(device_path="/dev/sda", success=False, error="connection refused")
    assert wr.success is False
    assert wr.error == "connection refused"
