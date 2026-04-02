import logging
import socket
import time
from datetime import datetime, timezone

import psycopg2.extensions

from shared.types import DeviceReading
from agent.enumerator import list_block_devices
from agent.flag_detector import detect_flags
from agent.collector import collect_device
from agent.db_writer import upsert_host, write_readings

logger = logging.getLogger(__name__)


def run_collection_cycle(
    host_id: str,
    conn: psycopg2.extensions.connection,
    device_timeout_seconds: int = 30,
) -> None:
    """Execute one full collection cycle: enumerate → detect → collect → write.

    A failure on any individual device is logged and skipped; the cycle
    continues for all remaining devices (NFR-09).

    Args:
        host_id: Stable identifier for this host.
        conn: Open psycopg2 connection to the central PostgreSQL instance.
        device_timeout_seconds: Per-device smartctl subprocess timeout.
    """
    cycle_start = time.monotonic()
    hostname = socket.gethostname()

    devices = list_block_devices()
    discovered = len(devices)

    if not devices:
        logger.warning("scheduler: no block devices found on %s — skipping cycle", host_id)
        return

    readings: list[DeviceReading] = []
    failed_devices: list[str] = []

    for device_path in devices:
        try:
            device_info = detect_flags(device_path, timeout_seconds=device_timeout_seconds)
            result = collect_device(device_info, timeout_seconds=device_timeout_seconds)

            if result.error == "timeout" or result.error == "smartctl_not_found":
                # FM-1: timed-out devices are not written to the DB
                failed_devices.append(device_path)
                continue

            readings.append(
                DeviceReading(
                    host_id=host_id,
                    device_path=result.device_path,
                    device_type=result.device_type,
                    smart_flags_used=" ".join(result.flags_used) if result.flags_used else "",
                    health_status=result.health_status,
                    raw_output=result.raw_output,
                    collected_at=datetime.now(tz=timezone.utc),
                )
            )
        except Exception as exc:
            logger.error("scheduler: unexpected error processing %s: %s", device_path, exc, exc_info=True)
            failed_devices.append(device_path)

    # upsert_host must run before write_readings: device_reading.host_id FK references host.host_id
    upsert_host(host_id, hostname, conn)
    write_results = write_readings(readings, conn)

    succeeded = sum(1 for r in write_results if r.success)
    write_failures = sum(1 for r in write_results if not r.success)
    duration_ms = int((time.monotonic() - cycle_start) * 1000)

    # NFR-11: structured cycle summary log
    logger.info(
        "scheduler: cycle complete | host=%s devices_discovered=%d "
        "devices_succeeded=%d devices_failed=%d duration_ms=%d",
        host_id,
        discovered,
        succeeded,
        len(failed_devices) + write_failures,
        duration_ms,
    )


def run_scheduler(
    host_id: str,
    conn: psycopg2.extensions.connection,
    polling_interval_seconds: int = 300,
    device_timeout_seconds: int = 30,
) -> None:
    """Run the collection pipeline on a recurring interval.

    The first cycle runs immediately on startup (within startup overhead),
    satisfying NFR-03 (first cycle within 30s of startup).

    This function blocks indefinitely. It is intended to be the main loop
    of the agent process, managed by systemd or equivalent.

    Args:
        host_id: Stable identifier for this host.
        conn: Open psycopg2 connection.
        polling_interval_seconds: Seconds between cycle starts (default: 300 = 5 min).
        device_timeout_seconds: Per-device smartctl timeout.
    """
    logger.info(
        "scheduler: starting | host=%s interval=%ds device_timeout=%ds",
        host_id,
        polling_interval_seconds,
        device_timeout_seconds,
    )

    while True:
        try:
            run_collection_cycle(
                host_id=host_id,
                conn=conn,
                device_timeout_seconds=device_timeout_seconds,
            )
        except Exception as exc:
            # Catch-all to prevent scheduler from dying on unexpected errors.
            # Individual component errors are handled within run_collection_cycle.
            logger.error("scheduler: unhandled error in collection cycle: %s", exc, exc_info=True)

        time.sleep(polling_interval_seconds)
