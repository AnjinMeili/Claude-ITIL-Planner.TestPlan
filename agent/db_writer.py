import logging
import time

import psycopg2
import psycopg2.extensions

from shared.types import DeviceReading, WriteResult

logger = logging.getLogger(__name__)

_INSERT_SQL = """
INSERT INTO device_reading
    (host_id, device_path, device_type, smart_flags_used,
     health_status, raw_output, collected_at)
VALUES
    (%s, %s, %s, %s, %s, %s, %s)
"""

_UPSERT_HOST_SQL = """
INSERT INTO host (host_id, hostname, last_seen)
VALUES (%s, %s, %s)
ON CONFLICT (host_id) DO UPDATE SET
    hostname = EXCLUDED.hostname,
    last_seen = EXCLUDED.last_seen
"""


def connect_with_backoff(database_url: str, max_wait_seconds: int = 60) -> psycopg2.extensions.connection:
    """Attempt to connect to PostgreSQL with exponential backoff.

    Retries on connection failure using delays of 2, 4, 8, 16, ... seconds
    up to max_wait_seconds total elapsed time. Raises the last exception if
    the maximum wait is exceeded.

    Args:
        database_url: libpq connection string.
        max_wait_seconds: Maximum total time to spend retrying.

    Returns:
        An open psycopg2 connection.

    Raises:
        psycopg2.OperationalError: If connection cannot be established within the wait window.
    """
    delay = 2
    elapsed = 0
    attempt = 0

    while True:
        try:
            conn = psycopg2.connect(database_url)
            if attempt > 0:
                logger.info("db_writer: connected to PostgreSQL after %ds", elapsed)
            return conn
        except psycopg2.OperationalError as exc:
            attempt += 1
            if elapsed >= max_wait_seconds:
                logger.error(
                    "db_writer: could not connect to PostgreSQL after %ds — giving up",
                    elapsed,
                )
                raise
            next_delay = min(delay, max_wait_seconds - elapsed)
            logger.warning(
                "db_writer: connection attempt %d failed (%s) — retrying in %ds",
                attempt,
                exc,
                next_delay,
            )
            time.sleep(next_delay)
            elapsed += next_delay
            delay = min(delay * 2, max_wait_seconds)


def write_readings(
    readings: list[DeviceReading],
    conn: psycopg2.extensions.connection,
) -> list[WriteResult]:
    """Insert a batch of DeviceReading records into PostgreSQL.

    Each record is inserted individually. A failure on one record is logged
    and skipped; all remaining records are attempted (NFR-09).

    If the connection is lost mid-batch, one reconnect is attempted before
    marking remaining records as failed.

    Args:
        readings: Normalised device readings from the SMART Collector.
        conn: An open psycopg2 connection.

    Returns:
        List of WriteResult, one per input reading.
    """
    results: list[WriteResult] = []

    for reading in readings:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    _INSERT_SQL,
                    (
                        reading.host_id,
                        reading.device_path,
                        reading.device_type,
                        reading.smart_flags_used,
                        reading.health_status,
                        reading.raw_output,
                        reading.collected_at,
                    ),
                )
            conn.commit()
            results.append(WriteResult(device_path=reading.device_path, success=True))

        except psycopg2.OperationalError as exc:
            # Connection lost — attempt one reconnect then mark remainder failed
            logger.error(
                "db_writer: connection lost writing %s (%s) — attempting reconnect",
                reading.device_path,
                exc,
            )
            results.append(WriteResult(device_path=reading.device_path, success=False, error=str(exc)))
            try:
                conn.reset()
            except Exception:
                logger.error("db_writer: reconnect failed — skipping remaining records")
                remaining = readings[len(results):]
                for r in remaining:
                    results.append(WriteResult(device_path=r.device_path, success=False, error="connection_lost"))
                return results

        except Exception as exc:
            logger.error(
                "db_writer: failed to write reading for %s: %s",
                reading.device_path,
                exc,
            )
            try:
                conn.rollback()
            except Exception:
                pass
            results.append(WriteResult(device_path=reading.device_path, success=False, error=str(exc)))

    return results


def upsert_host(host_id: str, hostname: str, conn: psycopg2.extensions.connection) -> None:
    """Update the host registry with the latest seen timestamp.

    Args:
        host_id: Stable identifier for this host (hostname or UUID).
        hostname: Human-readable hostname.
        conn: An open psycopg2 connection.
    """
    from datetime import datetime, timezone

    try:
        with conn.cursor() as cur:
            cur.execute(_UPSERT_HOST_SQL, (host_id, hostname, datetime.now(tz=timezone.utc)))
        conn.commit()
    except Exception as exc:
        logger.error("db_writer: failed to upsert host %s: %s", host_id, exc)
        try:
            conn.rollback()
        except Exception:
            pass
