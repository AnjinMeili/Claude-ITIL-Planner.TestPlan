# Scope: SMART Disk Health Monitor — v1

Derived from: PROJECT.md, SPEC.md, PLAN.md
Date: 2026-04-01

---

## Audience

**Primary:** A solo system administrator or developer managing 1–5 Linux machines personally. Interacts with the system via a browser (web UI) and a terminal (agent deployment, initial setup only).

**Secondary:** A single infrastructure owner in a small team needing a passive, always-current view of disk health across machines they manage.

---

## Platform and Stack

- **Agent:** Python 3.11+, runs as a systemd service on each monitored Linux host
- **Web server:** Python 3.11+, Flask, Jinja2, runs as a systemd service on the central host
- **Database:** PostgreSQL (`smart_disk_monitor` on `localhost:5432`), psycopg2 driver
- **Disk data source:** `smartmontools` (`smartctl` ≥ 7.0 recommended), invoked via subprocess with `sudo`
- **Deployment target:** Linux hosts only (agent); any Linux host with Python and Postgres access (web server)

---

## Scope Boundaries

### In Scope

- Collection agent that enumerates all block devices on a Linux host
- Per-device smartctl flag auto-detection using `smartctl -i -j` JSON info probe (no hardcoded device maps)
- SMART health data collection per device with per-device subprocess timeout
- Append-only persistence of device readings to PostgreSQL (`device_reading` table)
- `host` registry table updated on each successful cycle
- Configurable polling interval (default ≤5 minutes); first cycle within 30s of startup
- Agent fault isolation: single-device failure does not abort the collection cycle
- Agent resilience: PostgreSQL unavailability is logged and retried; no crash
- Web server serving a single HTML table (server-side rendered, Jinja2) of the latest reading per device per host
- `collected_at` timestamp column in the table as the staleness indicator
- HTTP 503 response when PostgreSQL is unreachable
- Structured logging from agent (cycle summary, per-device failure, DB write failure) and web server (HTTP request log)
- Database schema: `host` and `device_reading` tables
- Agent deployment via SSH key exchange to remote hosts; systemd unit file
- PostgreSQL connectivity from remote agents via direct TCP to central host

### Out of Scope (v1)

- Authentication or authorization on the web UI
- Alerting, notifications, email, or SMS for any disk health condition
- Windows or macOS monitored hosts
- Hardcoded per-device `smartctl` flag configuration
- Any external data transmission (all data stays in local PostgreSQL)
- Reverse proxy, TLS termination, or HTTPS
- Table sorting, filtering, or auto-refresh in the browser
- Dashboard, charting, or trend visualization
- Agent auto-update or central management of remote agents
- Notification of agent downtime (staleness is shown via `collected_at` timestamp only)

---

## Success Criteria

All four PROJECT.md success metrics must be demonstrable:

1. All attached disk devices across all monitored machines are visible in the web table with no SSH or terminal interaction after initial setup.
2. Zero devices in the database have `health_status = NULL`; no `smartctl` flag errors appear in agent logs for any device that is physically present and queryable.
3. Stopping and restarting the agent on any host leaves all prior `device_reading` rows intact and unchanged; new rows accumulate after restart.
4. Attaching a new disk to a monitored host causes a row for that device to appear in the web table within 10 minutes (two polling intervals at the default interval) with no configuration change and no agent restart.

---

## Constraints and Assumptions

- **smartmontools version:** `smartctl -i -j` (JSON output) requires smartmontools ≥ 7.0. Target hosts must be verified before deployment. (Assumed — confirm on each host.)
- **PostgreSQL access from remote hosts:** Requires `pg_hba.conf` to permit connections from remote agent host IPs and network path to port 5432. (Assumed accessible — verify in Phase 3.)
- **Agent privilege:** Runs as non-root user; requires a sudoers entry restricted to `/usr/bin/smartctl`. No broader privileges.
- **Solo developer:** No CI/CD pipeline, no staging environment beyond local testing. Pre-commit hooks (`black`, `ruff`, `commitlint`) are the primary quality gate.
- **Single database instance:** All agents write to the same PostgreSQL instance on the central host. No replication, failover, or backup strategy in v1.
- **No data retention policy:** Rows are never deleted in v1. Storage growth is assumed acceptable at the scale of 1–5 machines with ≤20 devices each.
