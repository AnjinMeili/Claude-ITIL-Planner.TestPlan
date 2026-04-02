import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import psycopg2
import pytest

from agent.db_writer import connect_with_backoff, upsert_host, write_readings
from shared.types import DeviceReading, WriteResult


def _reading(device_path: str = "/dev/sda", health_status: str = "PASSED") -> DeviceReading:
    return DeviceReading(
        host_id="test-host",
        device_path=device_path,
        device_type="sat",
        smart_flags_used="--device=sat",
        health_status=health_status,
        raw_output="{}",
        collected_at=datetime.now(tz=timezone.utc),
    )


def _mock_conn() -> tuple[MagicMock, MagicMock]:
    """Return (conn, cursor) mocks with the cursor wired as the context manager result."""
    cur = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn, cur


# --- Unit tests: write_readings ---


def test_successful_write_returns_success(mocker):
    conn, cur = _mock_conn()
    results = write_readings([_reading()], conn)
    assert len(results) == 1
    assert results[0].success is True
    assert results[0].device_path == "/dev/sda"


def test_correct_sql_issued(mocker):
    conn, cur = _mock_conn()
    reading = _reading()
    write_readings([reading], conn)
    cur.execute.assert_called_once()
    sql, params = cur.execute.call_args[0]
    assert "INSERT INTO device_reading" in sql
    assert reading.host_id in params
    assert reading.device_path in params
    assert reading.health_status in params


def test_commit_called_per_record():
    conn, cur = _mock_conn()
    write_readings([_reading("/dev/sda"), _reading("/dev/sdb")], conn)
    assert conn.commit.call_count == 2


def test_single_record_failure_does_not_abort_batch():
    """NFR-09: one device failure must not abort the entire collection cycle."""
    conn, cur = _mock_conn()
    cur.execute.side_effect = [Exception("constraint error"), None]

    results = write_readings([_reading("/dev/sda"), _reading("/dev/sdb")], conn)

    assert len(results) == 2
    assert results[0].success is False
    assert results[0].error == "constraint error"
    assert results[1].success is True


def test_failed_record_error_message_captured():
    conn, cur = _mock_conn()
    cur.execute.side_effect = Exception("unique violation")

    results = write_readings([_reading()], conn)
    assert results[0].success is False
    assert "unique violation" in results[0].error


def test_rollback_called_on_failure():
    conn, cur = _mock_conn()
    cur.execute.side_effect = Exception("error")

    write_readings([_reading()], conn)
    conn.rollback.assert_called_once()


def test_empty_batch_returns_empty_results():
    conn, cur = _mock_conn()
    results = write_readings([], conn)
    assert results == []


def test_write_result_device_path_matches_input():
    conn, cur = _mock_conn()
    results = write_readings([_reading("/dev/nvme0")], conn)
    assert results[0].device_path == "/dev/nvme0"


# --- Unit tests: connect_with_backoff ---


def test_connect_succeeds_first_attempt(mocker):
    mock_conn = MagicMock()
    mocker.patch("psycopg2.connect", return_value=mock_conn)
    conn = connect_with_backoff("postgresql://test")
    assert conn is mock_conn


def test_connect_retries_then_succeeds(mocker):
    mock_conn = MagicMock()
    mocker.patch("psycopg2.connect", side_effect=[psycopg2.OperationalError("refused"), mock_conn])
    mocker.patch("time.sleep")
    conn = connect_with_backoff("postgresql://test", max_wait_seconds=60)
    assert conn is mock_conn


def test_connect_raises_after_max_wait(mocker):
    mocker.patch("psycopg2.connect", side_effect=psycopg2.OperationalError("refused"))
    mocker.patch("time.sleep")
    with pytest.raises(psycopg2.OperationalError):
        connect_with_backoff("postgresql://test", max_wait_seconds=4)


# --- Integration test ---


@pytest.mark.integration
def test_write_reading_persists_to_db():
    """Requires a live PostgreSQL instance with the smart_disk_monitor schema applied."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not set")

    conn = psycopg2.connect(database_url)
    reading = _reading("/dev/test-device-integration")

    try:
        results = write_readings([reading], conn)
        assert results[0].success is True

        with conn.cursor() as cur:
            cur.execute(
                "SELECT host_id, device_path, health_status FROM device_reading WHERE device_path = %s",
                ("/dev/test-device-integration",),
            )
            row = cur.fetchone()

        assert row is not None
        assert row[0] == "test-host"
        assert row[1] == "/dev/test-device-integration"
        assert row[2] == "PASSED"
    finally:
        # Clean up integration test row
        with conn.cursor() as cur:
            cur.execute("DELETE FROM device_reading WHERE device_path = %s", ("/dev/test-device-integration",))
        conn.commit()
        conn.close()
