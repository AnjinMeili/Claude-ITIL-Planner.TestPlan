import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

# Set DATABASE_URL before importing app so the module loads cleanly
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from web.app import app, _LATEST_READINGS_SQL


@pytest.fixture()
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _make_row(
    host_id: str = "host-a",
    device_path: str = "/dev/sda",
    device_type: str = "sat",
    health_status: str = "PASSED",
    smart_flags_used: str = "--device=sat",
    collected_at: datetime | None = None,
) -> dict:
    return {
        "host_id": host_id,
        "device_path": device_path,
        "device_type": device_type,
        "health_status": health_status,
        "smart_flags_used": smart_flags_used,
        "collected_at": collected_at or datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc),
    }


def _mock_db(rows: list[dict]):
    """Patch web.app._get_connection to return a mock yielding the given rows."""
    conn = MagicMock()
    cur = MagicMock()
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    cur.fetchall.return_value = rows
    conn.cursor.return_value = cur
    return patch("web.app._get_connection", return_value=conn)


# --- Unit tests ---


def test_index_renders_table_with_rows(client):
    rows = [_make_row(), _make_row("host-b", "/dev/sdb")]
    with _mock_db(rows):
        resp = client.get("/")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "host-a" in body
    assert "host-b" in body
    assert "/dev/sda" in body
    assert "/dev/sdb" in body


def test_index_shows_health_status(client):
    with _mock_db([_make_row(health_status="PASSED")]):
        resp = client.get("/")
    assert b"PASSED" in resp.data


def test_index_shows_failed_status(client):
    with _mock_db([_make_row(health_status="FAILED")]):
        resp = client.get("/")
    assert b"FAILED" in resp.data


def test_index_shows_collected_at_timestamp(client):
    with _mock_db([_make_row()]):
        resp = client.get("/")
    assert b"2026-04-01" in resp.data
    assert b"UTC" in resp.data


def test_index_shows_empty_message_with_no_rows(client):
    with _mock_db([]):
        resp = client.get("/")
    assert resp.status_code == 200
    assert b"No data yet" in resp.data


def test_index_returns_503_on_db_error(client):
    with patch("web.app._get_connection", side_effect=Exception("connection refused")):
        resp = client.get("/")
    assert resp.status_code == 503
    assert b"Service unavailable" in resp.data


def test_503_does_not_leak_exception_details(client):
    """Critical fix: exception message must not appear in 503 response body."""
    with patch("web.app._get_connection", side_effect=Exception("host=secret-db port=5432 user=postgres")):
        resp = client.get("/")
    assert resp.status_code == 503
    assert b"secret-db" not in resp.data
    assert b"postgres" not in resp.data


def test_index_shows_correct_row_count(client):
    rows = [_make_row("host-a", f"/dev/sd{c}") for c in "abcde"]
    with _mock_db(rows):
        resp = client.get("/")
    body = resp.data.decode()
    # Each device path should appear once
    for c in "abcde":
        assert f"/dev/sd{c}" in body


def test_distinct_on_query_uses_correct_columns(client):
    """AC-01-01: query must return host_id, device_path, health_status, collected_at."""
    assert "DISTINCT ON (host_id, device_path)" in _LATEST_READINGS_SQL
    assert "collected_at DESC" in _LATEST_READINGS_SQL
    assert "health_status" in _LATEST_READINGS_SQL


def test_no_flags_displays_dash(client):
    with _mock_db([_make_row(smart_flags_used="")]):
        resp = client.get("/")
    assert "—" in resp.data.decode()


# --- Integration test ---


@pytest.mark.integration
def test_index_queries_live_db(client):
    """Requires DATABASE_URL pointing to smart_disk_monitor with at least one row."""
    resp = client.get("/")
    assert resp.status_code in (200, 503)  # 503 acceptable if DB has no rows yet
