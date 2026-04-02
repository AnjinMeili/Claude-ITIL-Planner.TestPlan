"""
Phase 3 integration tests.

These tests require:
- DATABASE_URL set to the smart_disk_monitor Postgres instance
- At least two rows in device_reading from different host_ids (for multi-machine test)
- A Linux host with smartctl installed (for auto-discovery test)

Run with: DATABASE_URL=postgresql://... python -m pytest tests/test_integration_phase3.py -m integration -v
"""

import os
from datetime import datetime, timezone

import psycopg2
import pytest

from shared.types import DeviceReading


def _conn():
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")
    return psycopg2.connect(url)


# --- Step 3.3: PostgreSQL reachable ---


@pytest.mark.integration
def test_postgres_reachable():
    """Step 3.3: confirm DATABASE_URL is reachable from this host."""
    conn = _conn()
    with conn.cursor() as cur:
        cur.execute("SELECT 1")
        result = cur.fetchone()
    conn.close()
    assert result == (1,)


# --- Step 3.4: Multi-machine data in one view ---


@pytest.mark.integration
def test_multiple_hosts_appear_in_single_query():
    """AC-05-01: device_reading rows from multiple hosts are returned by the web query."""
    conn = _conn()

    # Insert test rows for two synthetic hosts
    now = datetime.now(tz=timezone.utc)
    test_rows = [
        DeviceReading("test-host-alpha", "/dev/sda", "sat", "--device=sat", "PASSED", "{}", now),
        DeviceReading("test-host-beta", "/dev/sdb", "nvme", "--device=nvme", "PASSED", "{}", now),
    ]

    try:
        # Ensure host registry rows exist
        with conn.cursor() as cur:
            for row in test_rows:
                cur.execute(
                    "INSERT INTO host (host_id, hostname, last_seen) VALUES (%s, %s, %s) "
                    "ON CONFLICT (host_id) DO UPDATE SET last_seen = EXCLUDED.last_seen",
                    (row.host_id, row.host_id, now),
                )
                cur.execute(
                    "INSERT INTO device_reading "
                    "(host_id, device_path, device_type, smart_flags_used, health_status, raw_output, collected_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (row.host_id, row.device_path, row.device_type,
                     row.smart_flags_used, row.health_status, row.raw_output, row.collected_at),
                )
        conn.commit()

        # Run the web query
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT ON (host_id, device_path)
                    host_id, device_path, health_status
                FROM device_reading
                WHERE host_id IN ('test-host-alpha', 'test-host-beta')
                ORDER BY host_id, device_path, collected_at DESC
            """)
            rows = cur.fetchall()

        host_ids = {r[0] for r in rows}
        assert "test-host-alpha" in host_ids, "test-host-alpha missing from results"
        assert "test-host-beta" in host_ids, "test-host-beta missing from results"

        # AC-05-01: devices not cross-attributed
        for r in rows:
            if r[0] == "test-host-alpha":
                assert r[1] == "/dev/sda"
            if r[0] == "test-host-beta":
                assert r[1] == "/dev/sdb"

    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM device_reading WHERE host_id IN ('test-host-alpha', 'test-host-beta')")
            cur.execute("DELETE FROM host WHERE host_id IN ('test-host-alpha', 'test-host-beta')")
        conn.commit()
        conn.close()


# --- Step 3.4: Concurrent writes from multiple agents ---


@pytest.mark.integration
def test_concurrent_agent_writes_no_conflict():
    """AC-05-02: concurrent inserts from multiple agents produce no data loss or constraint violation."""
    import threading

    conn1 = _conn()
    conn2 = _conn()
    now = datetime.now(tz=timezone.utc)
    errors = []

    def insert(conn, host_id, device_path):
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO host (host_id, hostname, last_seen) VALUES (%s, %s, %s) "
                    "ON CONFLICT (host_id) DO UPDATE SET last_seen = EXCLUDED.last_seen",
                    (host_id, host_id, now),
                )
                cur.execute(
                    "INSERT INTO device_reading "
                    "(host_id, device_path, device_type, smart_flags_used, health_status, raw_output, collected_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (host_id, device_path, "sat", "", "PASSED", "{}", now),
                )
            conn.commit()
        except Exception as exc:
            errors.append(str(exc))
        finally:
            conn.close()

    t1 = threading.Thread(target=insert, args=(conn1, "concurrent-host-1", "/dev/sda"))
    t2 = threading.Thread(target=insert, args=(conn2, "concurrent-host-2", "/dev/sda"))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert errors == [], f"Concurrent write errors: {errors}"

    # Verify both rows exist
    verify_conn = _conn()
    try:
        with verify_conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM device_reading WHERE host_id IN ('concurrent-host-1', 'concurrent-host-2')"
            )
            count = cur.fetchone()[0]
        assert count == 2
    finally:
        with verify_conn.cursor() as cur:
            cur.execute("DELETE FROM device_reading WHERE host_id IN ('concurrent-host-1', 'concurrent-host-2')")
            cur.execute("DELETE FROM host WHERE host_id IN ('concurrent-host-1', 'concurrent-host-2')")
        verify_conn.commit()
        verify_conn.close()


# --- Step 3.5: Auto-discovery of new disk ---


@pytest.mark.integration
def test_new_device_appears_after_next_cycle():
    """AC-04-01: a new device must appear in DB after the next collection cycle without agent restart.

    This test simulates the scenario by running two collection cycles and checking
    that a device added between them appears in the second cycle's results.
    Requires a Linux host with smartctl installed.
    """
    from unittest.mock import patch
    from agent.enumerator import list_block_devices
    from agent.flag_detector import detect_flags
    from agent.collector import collect_device
    from agent.db_writer import write_readings, upsert_host
    import socket

    real_devices = list_block_devices()
    if not real_devices:
        pytest.skip("No block devices found — cannot simulate new device discovery")

    conn = _conn()
    host_id = f"integration-test-{socket.gethostname()}"
    now = datetime.now(tz=timezone.utc)

    try:
        # Cycle 1: only first device
        with patch("agent.scheduler.list_block_devices", return_value=real_devices[:1]):
            from agent.scheduler import run_collection_cycle
            run_collection_cycle(host_id=host_id, conn=conn)

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM device_reading WHERE host_id = %s", (host_id,))
            count_after_cycle_1 = cur.fetchone()[0]

        # Cycle 2: all devices (simulates new disk appearing)
        with patch("agent.scheduler.list_block_devices", return_value=real_devices):
            run_collection_cycle(host_id=host_id, conn=conn)

        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT device_path FROM device_reading WHERE host_id = %s", (host_id,))
            paths = {r[0] for r in cur.fetchall()}

        # All real devices should now be present
        for d in real_devices:
            assert d in paths, f"Expected {d} to appear after second cycle"

    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM device_reading WHERE host_id = %s", (host_id,))
            cur.execute("DELETE FROM host WHERE host_id = %s", (host_id,))
        conn.commit()
        conn.close()
