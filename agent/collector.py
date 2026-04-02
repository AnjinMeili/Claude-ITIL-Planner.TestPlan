import json
import logging
import subprocess

from shared.types import DeviceInfo, SmartResult

logger = logging.getLogger(__name__)


def collect_device(device_info: DeviceInfo, timeout_seconds: int = 30) -> SmartResult:
    """Collect SMART health data for a single device.

    Runs `sudo smartctl -H -j [flags] <device_path>` and parses the result.
    health_status is always non-null: "PASSED", "FAILED", or "UNKNOWN".
    A timed-out device is returned with health_status="UNKNOWN" and error="timeout";
    its record is not written to the database (caller's responsibility).

    Args:
        device_info: Device path, type, and flags from Flag Detector.
        timeout_seconds: Per-device subprocess timeout.

    Returns:
        SmartResult with health_status guaranteed non-null.
    """
    cmd = ["sudo", "smartctl", "-H", "-j"] + device_info.smartctl_flags + [device_info.device_path]
    flags_str = " ".join(device_info.smartctl_flags) if device_info.smartctl_flags else "(none)"

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            logger.error(
                "collector: could not parse JSON from smartctl -H -j %s (exit %d)",
                device_info.device_path,
                result.returncode,
            )
            return SmartResult(
                device_path=device_info.device_path,
                device_type=device_info.detected_type,
                flags_used=device_info.smartctl_flags,
                health_status="UNKNOWN",
                raw_output=result.stdout,
                error=f"json_parse_error (exit {result.returncode})",
            )

        health_status = _parse_health_status(data)

        if health_status == "UNKNOWN":
            logger.warning(
                "collector: could not determine health_status for %s — storing as UNKNOWN",
                device_info.device_path,
            )
        else:
            logger.debug(
                "collector: %s → %s (flags: %s)",
                device_info.device_path,
                health_status,
                flags_str,
            )

        return SmartResult(
            device_path=device_info.device_path,
            device_type=device_info.detected_type,
            flags_used=device_info.smartctl_flags,
            health_status=health_status,
            raw_output=result.stdout,
        )

    except subprocess.TimeoutExpired:
        logger.error(
            "collector: smartctl -H -j timed out after %ds for %s (flags: %s)",
            timeout_seconds,
            device_info.device_path,
            flags_str,
        )
        return SmartResult(
            device_path=device_info.device_path,
            device_type=device_info.detected_type,
            flags_used=device_info.smartctl_flags,
            health_status="UNKNOWN",
            raw_output="",
            error="timeout",
        )

    except FileNotFoundError:
        logger.error("collector: smartctl not found — is smartmontools installed?")
        return SmartResult(
            device_path=device_info.device_path,
            device_type=device_info.detected_type,
            flags_used=device_info.smartctl_flags,
            health_status="UNKNOWN",
            raw_output="",
            error="smartctl_not_found",
        )


def _parse_health_status(data: dict) -> str:
    """Extract health status from parsed smartctl JSON output.

    Returns "PASSED", "FAILED", or "UNKNOWN". Never returns None or empty string.
    """
    passed = data.get("smart_status", {}).get("passed")
    if passed is True:
        return "PASSED"
    if passed is False:
        return "FAILED"
    return "UNKNOWN"
