# PLAN.md — SMART Disk Health Monitor

Derived from: PROJECT.md, SPEC.md, ARCH.md, DEV-SPEC.md
Date: 2026-04-01

---

## Goal

Deliver a working SMART disk health monitoring system: a collection agent that auto-detects and queries disk devices on Linux hosts, persists results to PostgreSQL, and a web application that displays all device readings in a single table.

Success is confirmed when all four PROJECT.md success metrics are verifiable:
1. All attached devices visible in the web table without SSH after initial setup.
2. Each device queried with correct `smartctl` options — no device errors due to wrong flags.
3. SMART data persists in PostgreSQL across agent restarts.
4. A newly attached disk appears in the web UI on the next collection cycle without config changes.

---

## Phase 1 — Database schema and agent core (Days 1–2)

**Milestone:** `smartctl` output for all disk devices on the local machine is parsed, normalised, and written to PostgreSQL with correct per-device options applied automatically.

### 1.1 — Project scaffold
- Create project directory structure: `agent/`, `web/`, `shared/`, `tests/`
- Initialise `requirements.txt` with pinned versions: `psycopg2-binary`, `python-dotenv`, `black`, `ruff`
- Create `.env.example` with `DATABASE_URL`, `AGENT_POLLING_INTERVAL_SECONDS`, `AGENT_DEVICE_TIMEOUT_SECONDS`, `WEB_PORT`
- Create `.gitignore` (`.env`, `__pycache__`, `*.pyc`, `.pytest_cache`)

### 1.2 — Database schema
- Write `db/schema.sql` defining `host` and `device_reading` tables per ARCH.md §3
- Apply schema to `smart_disk_monitor` database: `psql $DATABASE_URL -f db/schema.sql`
- Verify tables exist: `psql $DATABASE_URL -c '\dt'`
- **Rollback:** `DROP TABLE device_reading; DROP TABLE host;` — schema is empty at this point, no data at risk

### 1.3 — Shared types
- Define `DeviceInfo`, `SmartResult`, `DeviceReading`, `WriteResult` dataclasses in `shared/types.py` per ARCH.md §4 interface contracts
- Unit tests: instantiate each type, verify field access and type annotations

### 1.4 — Device Enumerator
- Implement `agent/enumerator.py`: `list_block_devices() -> list[str]`
- Use `lsblk -d -o NAME -n` subprocess to list block devices; return paths as `/dev/<name>`
- Unit test: mock subprocess output, assert returned device paths
- Integration test: run against local machine, assert at least one device returned

### 1.5 — Flag Detector
- Implement `agent/flag_detector.py`: `detect_flags(device_path: str, timeout_seconds: int) -> DeviceInfo`
- Strategy: run `sudo smartctl -i -j <device>`, parse `device.type` JSON field (ADR-002)
- Map `device.type` to smartctl flags: `sat` → `--device=sat`, `nvme` → `--device=nvme`, unknown → `[]`
- Per-device subprocess timeout: kill and return `detected_type="unknown"` on expiry (FM-1 mitigation)
- Unit tests: mock subprocess JSON output for SATA, NVMe, unknown device; assert correct flags returned
- Unit test: mock timeout — assert `detected_type="unknown"` returned, no exception raised
- Integration test: run against one real device on local machine, assert non-empty `detected_type`

### 1.6 — SMART Collector
- Implement `agent/collector.py`: `collect_device(device_info: DeviceInfo, timeout_seconds: int) -> SmartResult`
- Run `sudo smartctl -H -j --device=<type> <path>`, parse `smart_status.passed` from JSON
- Set `health_status = "PASSED"` / `"FAILED"` / `"UNKNOWN"` (never null — FM-2 mitigation)
- Per-device subprocess timeout; set `health_status = "UNKNOWN"`, `error = "timeout"` on expiry
- Unit tests: mock JSON output for healthy, failed, and malformed/partial responses; assert `health_status` is never null
- Unit test: mock timeout — assert `health_status = "UNKNOWN"`, no exception raised

### 1.7 — DB Writer
- Implement `agent/db_writer.py`: `write_readings(readings: list[DeviceReading], conn) -> list[WriteResult]`
- Append-only INSERT per ARCH.md §4.4; no ON CONFLICT clause
- Per-record failure: log error, continue with remaining records (NFR-09)
- Startup connection test with exponential backoff: 2s, 4s, 8s, 16s, max 60s wait (FM-4 mitigation)
- Unit tests: mock psycopg2 connection; assert correct SQL issued, WriteResult populated
- Unit test: mock insert failure on one record — assert remaining records attempted, no exception raised
- Integration test: write one DeviceReading to test DB, assert row exists with correct values

### 1.8 — Scheduler and agent entry point
- Implement `agent/scheduler.py`: configurable polling loop; first cycle within 30s of startup (NFR-03)
- Implement `agent/__main__.py`: load config from env, initialise DB connection with backoff, run scheduler
- Structured log on each collection cycle: host_id, devices_discovered, devices_succeeded, devices_failed, duration_ms (NFR-11)
- Structured log on each per-device failure: device_path, exit_code, flags_attempted (NFR-12)
- Structured log on each DB write failure: error_message, records_failed (NFR-13)
- Integration test: run one full collection cycle locally, assert records appear in `device_reading` table

**Phase 1 complete when:** `python -m agent` runs on the local machine, collects SMART data for all attached disks, and rows appear in `device_reading` with non-null `health_status` and correct `device_type` for each device.

---

## Phase 2 — Web server and table display (Days 3–4)

**Milestone:** A browser-accessible table shows current SMART data for all devices, readable without any CLI access.

### 2.1 — Web server scaffold
- Add `flask` and `jinja2` to `requirements.txt`
- Implement `web/app.py`: Flask app, single route `GET /`, reads DB and renders table
- Implement `web/templates/index.html`: HTML table with columns — Host, Device, Type, Health Status, Flags Used, Collected At
- `collected_at` displayed in local time with UTC marker (FM-6 staleness mitigation)
- HTTP request log on each request: timestamp, method, path, status, response_ms (NFR-14)
- Return HTTP 503 with plain-text error body if PostgreSQL unreachable (ARCH.md §4.3)

### 2.2 — Query implementation
- Implement `DISTINCT ON (host_id, device_path) ... ORDER BY host_id, device_path, collected_at DESC` per ARCH.md §4.3
- Unit test: mock DB result set, assert table renders correct number of rows
- Integration test: insert 3 readings for 2 devices, assert web response contains 2 rows (latest per device)

### 2.3 — End-to-end smoke test (local)
- Run agent for one cycle, run web server, open `http://localhost:8080` in browser
- Verify: table renders within 3 seconds (NFR-01), each device has a row, `collected_at` is recent
- Verify: HTTP 503 returned when Postgres connection string is wrong

**Phase 2 complete when:** `python -m web` on the central host shows a browser-accessible table with all local disk devices, health status, and timestamps — no terminal commands required after startup.

---

## Phase 3 — Multi-machine support and deployment (Days 5–7)

**Milestone:** Data from at least two separate Linux machines appears in the same web table, collected without manual intervention on each machine after initial agent deployment.

### 3.1 — Host identity
- Agent derives `host_id` from `socket.gethostname()` at startup; log the value on first cycle
- Verify `host_id` is unique and stable across restarts on each target machine

### 3.2 — Remote agent deployment (per remote host)
- Document deployment procedure in `README.md`:
  1. SSH key exchange: `ssh-copy-id user@remote-host`
  2. Copy agent code: `scp -r agent/ shared/ requirements.txt user@remote-host:~/smart-agent/`
  3. Create non-root user and add sudoers entry: `user ALL=(ALL) NOPASSWD: /usr/bin/smartctl`
  4. Install smartmontools: `sudo apt install smartmontools` (or distro equivalent)
  5. Create `.env` with `DATABASE_URL` pointing to central host IP (not localhost)
  6. Install and enable systemd unit (see `infra/smart-agent.service`)
- Create `infra/smart-agent.service` systemd unit file: `Restart=on-failure`, `RestartSec=10`
- **Rollback per host:** `systemctl stop smart-agent && systemctl disable smart-agent` — agent stops; Postgres rows from that host remain but no new rows are added

### 3.3 — PostgreSQL access from remote hosts
- Confirm `pg_hba.conf` allows connections from remote agent host IPs (ADR-004)
- Confirm Postgres port 5432 is reachable from each remote host: `psql $DATABASE_URL -c 'SELECT 1'`
- **Risk:** If Postgres is not accessible from remote hosts, agents will log connection failures and retry. No data loss — just gaps in collection until connectivity is established.
- **Rollback / recovery:** If direct TCP to Postgres is blocked and cannot be unblocked (firewall policy, network topology), establish an SSH tunnel from the remote host to the central host and update `DATABASE_URL` on the remote agent to use the tunnel endpoint (`localhost:<tunnel_port>`). Restart the agent after updating the env. See ADR-004 §Alternatives Rejected for the SSH tunnel configuration pattern.

### 3.4 — Multi-machine end-to-end test
- Deploy agent to at least one remote host
- Wait one polling interval (≤5 minutes)
- Load web UI — assert rows from both local host and remote host appear, each with correct `host_id`
- Assert: devices from different machines are not cross-attributed (AC-05-01)

### 3.5 — New disk auto-discovery test
- Verify: attach a new device to a monitored machine (or simulate by creating a loop device)
- Wait one polling interval
- Assert: new device row appears in web UI without agent restart or config change (AC-04-01)

**Phase 3 complete when:** the web table shows devices from at least two machines, each row correctly attributed, with no manual intervention after initial deployment.

---

## Risk Register

| Risk | Severity | Mitigation | Rollback |
|---|---|---|---|
| Schema migration fails on apply | Low | Schema is additive, no existing data | `DROP TABLE` — no data exists yet at this point |
| `smartctl -i -j` not available (smartmontools < 7.0) | Medium | Test on each target host before deployment; fall back to text parsing if needed | Pin flag detection to non-JSON path for affected hosts |
| Postgres port blocked by firewall on remote hosts | Medium | Verify with `psql` test before deploying agent (Step 3.3) | Use SSH tunnel per ADR-004 alternatives |
| Remote host `sudo` for `smartctl` misconfigured | Low | Test `sudo smartctl --scan` manually before starting agent | Fix sudoers entry; no data at risk |
| Agent logs too verbose in production | Low | Set log level via env var; default to INFO | Restart agent with `LOG_LEVEL=WARNING` |

---

## Success Criteria

The plan is complete when all four PROJECT.md success metrics can be demonstrated:

1. Open web UI — see all attached disk devices across all monitored machines with no SSH.
2. Inspect DB — zero devices with `health_status = NULL`; no `smartctl` flag errors in logs.
3. Restart agent on any host — prior rows in DB unchanged; new rows accumulate.
4. Attach a new disk — it appears in the web UI within 10 minutes (two polling intervals) without any config change.
