from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class DeviceInfo:
    """Output of Flag Detector: device path, classified type, and flags to use."""

    device_path: str
    detected_type: str  # "sata" | "nvme" | "usb" | "raid" | "unknown"
    smartctl_flags: list[str] = field(default_factory=list)


@dataclass
class SmartResult:
    """Output of SMART Collector: parsed health data for one device."""

    device_path: str
    device_type: str
    flags_used: list[str]
    health_status: str  # "PASSED" | "FAILED" | "UNKNOWN"
    raw_output: str
    error: str | None = None


@dataclass
class DeviceReading:
    """A normalised record ready to be written to device_reading table."""

    host_id: str
    device_path: str
    device_type: str
    smart_flags_used: str
    health_status: str  # never null; "UNKNOWN" is acceptable
    raw_output: str
    collected_at: datetime


@dataclass
class WriteResult:
    """Outcome of a single DB insert attempt."""

    device_path: str
    success: bool
    error: str | None = None
