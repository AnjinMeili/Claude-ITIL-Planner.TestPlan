import subprocess
import logging

logger = logging.getLogger(__name__)


def list_block_devices() -> list[str]:
    """Return a list of block device paths on the local host.

    Uses lsblk to enumerate non-partition disk devices.
    Returns paths in the form /dev/<name> (e.g. /dev/sda, /dev/nvme0).

    Returns:
        List of device path strings. Empty list if lsblk fails or no devices found.
    """
    try:
        result = subprocess.run(
            ["lsblk", "-d", "-o", "NAME", "-n"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            logger.error("lsblk exited with code %d: %s", result.returncode, result.stderr.strip())
            return []

        devices = []
        for line in result.stdout.splitlines():
            name = line.strip()
            if name:
                devices.append(f"/dev/{name}")

        logger.debug("Enumerated %d block device(s): %s", len(devices), devices)
        return devices

    except FileNotFoundError:
        logger.error("lsblk not found — is util-linux installed?")
        return []
    except subprocess.TimeoutExpired:
        logger.error("lsblk timed out")
        return []
