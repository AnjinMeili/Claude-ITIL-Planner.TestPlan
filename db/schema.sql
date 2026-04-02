-- SMART Disk Health Monitor — database schema
-- Database: smart_disk_monitor
-- Apply with: psql $DATABASE_URL -f db/schema.sql

CREATE TABLE IF NOT EXISTS host (
    host_id     TEXT PRIMARY KEY,
    hostname    TEXT NOT NULL,
    last_seen   TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS device_reading (
    id              BIGSERIAL PRIMARY KEY,
    host_id         TEXT NOT NULL REFERENCES host(host_id),
    device_path     TEXT NOT NULL,
    device_type     TEXT NOT NULL,
    smart_flags_used TEXT NOT NULL,
    health_status   TEXT NOT NULL,
    raw_output      TEXT NOT NULL,
    collected_at    TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_device_reading_lookup
    ON device_reading (host_id, device_path, collected_at DESC);
