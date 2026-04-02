import json
import logging
import subprocess

from shared.types import DeviceInfo

logger = logging.getLogger(__name__)

# Map smartctl device.type values to the flags needed for a full SMART query.
# Values come from `smartctl -i -j` output — these are smartctl's own classifications.
_TYPE_TO_FLAGS: dict[str, list[str]] = {
    "sat": ["--device=sat"],
    "nvme": ["--device=nvme"],
    "scsi": [],  # SCSI devices respond without a type flag
    "usb": ["--device=sat"],  # USB-attached drives typically use SAT passthrough
    "ata": [],  # ATA devices respond without a type flag
}


def detect_flags(device_path: str, timeout_seconds: int = 30) -> DeviceInfo:
    """Determine the correct smartctl flags for a device using its JSON info output.

    Runs `sudo smartctl -i -j <device_path>` and parses the `device.type` field
    to select the appropriate flags. Falls back to `detected_type="unknown"` and
    empty flags if the probe times out, fails, or returns unrecognised output.

    Args:
        device_path: Block device path, e.g. "/dev/sda".
        timeout_seconds: Per-device subprocess timeout. Device is skipped on expiry.

    Returns:
        DeviceInfo with detected_type and smartctl_flags populated.
    """
    try:
        result = subprocess.run(
            ["sudo", "smartctl", "-i", "-j", device_path],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )

        # smartctl exits non-zero for some error conditions but may still return
        # valid JSON with a device.type field — attempt to parse regardless.
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            logger.error(
                "flag_detector: could not parse JSON from smartctl -i -j %s (exit %d)",
                device_path,
                result.returncode,
            )
            return DeviceInfo(device_path=device_path, detected_type="unknown")

        detected_type = data.get("device", {}).get("type", "").lower()
        if not detected_type:
            logger.warning("flag_detector: no device.type in smartctl output for %s", device_path)
            return DeviceInfo(device_path=device_path, detected_type="unknown")

        flags = _TYPE_TO_FLAGS.get(detected_type, [])
        if detected_type not in _TYPE_TO_FLAGS:
            logger.warning(
                "flag_detector: unrecognised device type %r for %s — using no flags",
                detected_type,
                device_path,
            )

        logger.debug("flag_detector: %s → type=%r flags=%s", device_path, detected_type, flags)
        return DeviceInfo(device_path=device_path, detected_type=detected_type, smartctl_flags=flags)

    except subprocess.TimeoutExpired:
        logger.error(
            "flag_detector: smartctl -i -j timed out after %ds for %s",
            timeout_seconds,
            device_path,
        )
        return DeviceInfo(device_path=device_path, detected_type="unknown")

    except FileNotFoundError:
        logger.error("flag_detector: smartctl not found — is smartmontools installed?")
        return DeviceInfo(device_path=device_path, detected_type="unknown")
