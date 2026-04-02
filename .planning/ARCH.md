# ARCH.md — SMART Disk Health Monitor

**Date:** 2026-04-01
**Status:** Accepted

---

## Table of Contents

1. System Context
2. Component Diagram
3. Data Model
4. Interface Contracts
5. Deployment Model
6. Failure Mode Mitigations
7. References

---

## 1. System Context

The system consists of a collection agent deployed on each monitored Linux host and a web server running on the central host alongside PostgreSQL. No external services, cloud dependencies, or authentication infrastructure are involved in v1.

```
  ┌────────────────────────────────────────────────────────────────────────┐
  │  System Boundary                                                       │
  │                                                                        │
  │  ┌──────────────────────────┐       ┌──────────────────────────────┐  │
  │  │  Remote Host A           │       │  Central Host                │  │
  │  │  (collection agent)      │       │                              │  │
  │  │                          │──────▶│  PostgreSQL                  │  │
  │  └──────────────────────────┘  TCP  │  smart_disk_monitor DB       │  │
  │                                     │                              │  │
  │  ┌──────────────────────────┐       │  Web Server                  │  │
  │  │  Remote Host B           │       │  (reads DB, serves HTML)     │  │
  │  │  (collection agent)      │──────▶│                              │  │
  │  └──────────────────────────┘  TCP  └──────────────┬───────────────┘  │
  │                                                     │                  │
  │  ┌──────────────────────────┐                       │ HTTP             │
  │  │  Central Host            │                       │                  │
  │  │  (collection agent,      │──────▶ (loopback)     │                  │
  │  │   if disks attached)     │                       │                  │
  │  └──────────────────────────┘                       │                  │
  │                                                     │                  │
  └─────────────────────────────────────────────────────┼──────────────────┘
                                                        │
                                               ┌────────▼────────┐
                                               │  Sysadmin /     │
                                               │  Developer      │
                                               │  (browser)      │
                                               └─────────────────┘
```

**External actors:**

| Actor | Role | Interaction |
|---|---|---|
| Sysadmin / Developer | Reads the web UI | HTTP GET to Web Server |
| Monitored Linux Hosts (1–5) | Run the collection agent | Agent writes to central Postgres over TCP |
| PostgreSQL | Central data store | Receives inserts from agents; serves SELECT queries to Web Server |
| smartmontools (`smartctl`) | Disk query tool | Invoked by agent as a subprocess via sudo |

**What is outside the system boundary:**

- Email / alerting services (not in scope for v1)
- Reverse proxy / TLS termination (not required for v1)
- Authentication / authorisation (explicitly excluded from v1)
- External data transmission of any kind

---

## 2. Component Diagram

All components within the agent process are in-process function/module calls unless otherwise noted. The agent is a single OS process per host.

```
  ┌─────────────────────────────────────────────────────────┐
  │  Agent Process (one per monitored host)                 │
  │                                                         │
  │  ┌─────────────┐                                        │
  │  │  Scheduler  │  Fires collection pipeline on          │
  │  │             │  configurable interval (≤5 min).       │
  │  │             │  First cycle within 30s of startup.    │
  │  └──────┬──────┘                                        │
  │         │ triggers (in-process call)                    │
  │         ▼                                               │
  │  ┌──────────────────┐                                   │
  │  │ Device Enumerator│  Reads /proc/partitions or uses   │
  │  │                  │  lsblk to list block devices.     │
  │  └────────┬─────────┘                                   │
  │           │ list of device paths (in-process)           │
  │           ▼                                             │
  │  ┌──────────────────┐                                   │
  │  │  Flag Detector   │  For each device: runs            │
  │  │                  │  `sudo smartctl -i -j <dev>`      │
  │  │                  │  and parses device.type from      │
  │  │                  │  JSON output to select flags.     │
  │  │                  │  Subprocess with per-device       │
  │  │                  │  timeout (see §6).                │
  │  └────────┬─────────┘                                   │
  │           │ (device_path, detected_type, flags)         │
  │           │ per-device (in-process)                     │
  │           ▼                                             │
  │  ┌──────────────────┐                                   │
  │  │ SMART Collector  │  Invokes `sudo smartctl -H -j`    │
  │  │                  │  (plus detected flags) per device.│
  │  │                  │  Parses output, normalises to     │
  │  │                  │  internal schema.                 │
  │  │                  │  Subprocess with per-device       │
  │  │                  │  timeout (see §6).                │
  │  └────────┬─────────┘                                   │
  │           │ list of DeviceReading records (in-process)  │
  │           ▼                                             │
  │  ┌──────────────────┐                                   │
  │  │   DB Writer      │  Inserts records to PostgreSQL.   │
  │  │                  │  Logs per-record failures and      │
  │  │                  │  continues (no full-cycle abort). │
  │  │                  │  Retries connection on startup    │
  │  │                  │  with exponential backoff.        │
  │  └────────┬─────────┘                                   │
  │           │ TCP connection                              │
  └───────────┼─────────────────────────────────────────────┘
              │
              ▼
  ┌───────────────────────┐
  │  PostgreSQL           │
  │  smart_disk_monitor   │
  └───────────┬───────────┘
              │ SQL SELECT (TCP loopback on central host)
              ▼
  ┌───────────────────────────────────────────┐
  │  Web Server Process (central host only)   │
  │                                           │
  │  ┌─────────────────┐  ┌────────────────┐  │
  │  │  HTTP Handler   │─▶│ Table Renderer │  │
  │  │  (GET /)        │  │ (server-side   │  │
  │  └─────────────────┘  │  HTML, Jinja2) │  │
  │                       └────────────────┘  │
  └───────────────────────────────────────────┘
```

**Communication summary:**

| Link | Style | Notes |
|---|---|---|
| Scheduler → Device Enumerator | Synchronous in-process call | Single-threaded pipeline per cycle |
| Device Enumerator → Flag Detector | Synchronous in-process call | Iterates device list |
| Flag Detector → SMART Collector | Synchronous in-process call | Per-device flags passed as value |
| SMART Collector → DB Writer | Synchronous in-process call | Passes list of normalised records |
| DB Writer → PostgreSQL | TCP (psycopg2) | Append-only INSERT; retry on connect failure |
| Web Server → PostgreSQL | TCP (psycopg2) | SELECT on each HTTP request |
| Browser → Web Server | HTTP | Synchronous request/response |

---

## 3. Data Model

The data model is append-only. No record is ever updated or deleted in v1.

```
  ┌──────────────────────────────────────────────────────┐
  │  host                                                │
  │                                                      │
  │  host_id       TEXT  PK  (e.g. hostname or UUID)     │
  │  hostname      TEXT                                  │
  │  last_seen     TIMESTAMPTZ                           │
  └───────────────────────────┬──────────────────────────┘
                              │ 1
                              │
                              │ many
  ┌───────────────────────────▼──────────────────────────┐
  │  device_reading                                      │
  │                                                      │
  │  id              BIGSERIAL  PK                       │
  │  host_id         TEXT       FK → host.host_id        │
  │  device_path     TEXT       (e.g. /dev/sda)          │
  │  device_type     TEXT       (SATA / NVMe / USB / ...) │
  │  smart_flags_used TEXT      (flags that succeeded)   │
  │  health_status   TEXT       (PASSED / FAILED /       │
  │                              UNKNOWN)                │
  │  raw_output      TEXT       (full smartctl JSON or   │
  │                              text output)            │
  │  collected_at    TIMESTAMPTZ  (UTC, set by agent)    │
  └──────────────────────────────────────────────────────┘
```

**Key constraints:**

- No unique constraint on `(host_id, device_path, collected_at)`. Concurrent inserts from multiple agents must not conflict (AC-04 / failure mode 3).
- `device_reading` rows are never updated. The web server queries for the latest row per `(host_id, device_path)` using `DISTINCT ON` or a window function.
- `host` is an optional registry updated by the agent on each successful cycle (`INSERT ... ON CONFLICT DO UPDATE` for `last_seen`). Its absence does not block inserts to `device_reading`.
- `health_status` must be non-null before a row is written (see failure mode 2 mitigation in §6).

---

## 4. Interface Contracts

### 4.1 Flag Detector → SMART Collector

**Purpose:** Provide the SMART Collector with the device path, classified type, and the smartctl flags that successfully identified the device.

**Input (per device):**

```
DeviceInfo {
  device_path:    str   # e.g. "/dev/sda"
  detected_type:  str   # "sata" | "nvme" | "usb" | "raid" | "unknown"
  smartctl_flags: list[str]  # e.g. ["--device=sat"] or []
}
```

**Output (per device):**

```
SmartResult {
  device_path:   str
  device_type:   str
  flags_used:    list[str]
  health_status: str   # "PASSED" | "FAILED" | "UNKNOWN"
  raw_output:    str   # full smartctl stdout
  error:         str | None  # non-null if collection failed for this device
}
```

**Error conditions:**

- If `smartctl` exits non-zero and no health status can be parsed, `error` is populated and `health_status` is set to `"UNKNOWN"`.
- If the subprocess times out (see §6), `error` is set to `"timeout"` and the record is skipped (not written to DB).
- The contract does not raise exceptions across the boundary; errors are carried in the result value.

**SLA:** Each device probe must complete within the configured per-device timeout (default: 30 seconds).

---

### 4.2 SMART Collector → DB Writer

**Purpose:** Hand off a batch of normalised device reading records for persistence.

**Input:**

```
list[DeviceReading] where DeviceReading {
  host_id:         str
  device_path:     str
  device_type:     str
  smart_flags_used: str
  health_status:   str   # must be non-null; "UNKNOWN" is acceptable
  raw_output:      str
  collected_at:    datetime (UTC)
}
```

**Output (per record):**

```
WriteResult {
  device_path: str
  success:     bool
  error:       str | None
}
```

**Error conditions:**

- A failure to write one record is logged and skipped; the remaining records in the batch are attempted (NFR-08, NFR-09).
- If the database connection is lost mid-batch, the DB Writer attempts reconnect once before marking remaining records as failed and logging.

**SLA:** No throughput SLA beyond completing the full batch before the next scheduler cycle.

---

### 4.3 Web Server → PostgreSQL

**Purpose:** Retrieve the latest reading for every known (host_id, device_path) pair.

**Query contract:**

```sql
SELECT DISTINCT ON (host_id, device_path)
    host_id,
    device_path,
    device_type,
    health_status,
    smart_flags_used,
    collected_at
FROM device_reading
ORDER BY host_id, device_path, collected_at DESC;
```

**Output:** One row per distinct `(host_id, device_path)`. Rows ordered by `host_id` then `device_path` for stable table rendering.

**Error conditions:** If PostgreSQL is unreachable, the web server returns HTTP 503 with a plain-text error body. No partial HTML is rendered.

**SLA:** Query must return within 5 seconds under expected data volumes (≤5 hosts × ≤20 devices × history rows). No index beyond the default primary key is required for v1 data volumes, but an index on `(host_id, device_path, collected_at DESC)` is recommended.

---

### 4.4 Agent → PostgreSQL (Insert Contract)

**Purpose:** Append a new device reading row after each successful collection.

**Statement contract:**

```sql
INSERT INTO device_reading
    (host_id, device_path, device_type, smart_flags_used,
     health_status, raw_output, collected_at)
VALUES
    ($1, $2, $3, $4, $5, $6, $7);
```

No `ON CONFLICT` clause. No unique constraint on `(host_id, device_path)`. Multiple agents inserting simultaneously produce independent rows without conflict.

**Precondition:** `health_status` is non-null (validated by SMART Collector before hand-off).

**Error conditions:** On insert failure, DB Writer logs the error with device path and timestamp, then continues with the next record.

---

## 5. Deployment Model

```
  ┌─────────────────────────────────────────────────────────────────┐
  │  Central Host  (e.g. monitor.local)                             │
  │                                                                 │
  │  ┌─────────────────────┐    ┌──────────────────────────────┐   │
  │  │  Web Server         │    │  PostgreSQL                  │   │
  │  │  Python / Flask     │    │  database: smart_disk_monitor│   │
  │  │  port 8080 (default)│◀──▶│  port 5432 (loopback)        │   │
  │  │  systemd service    │    │  already provisioned         │   │
  │  └─────────────────────┘    └──────────────────────────────┘   │
  │                                          ▲                      │
  │  ┌───────────────────────────┐           │ TCP loopback         │
  │  │  Agent (if local disks)   │───────────┘                      │
  │  │  systemd service          │                                  │
  │  │  non-root user + sudoers  │                                  │
  │  └───────────────────────────┘                                  │
  └─────────────────────────────────────────────────────────────────┘
           ▲                        ▲
           │ TCP (pg port)          │ TCP (pg port)
           │                        │
  ┌────────┴──────────┐   ┌─────────┴──────────┐
  │  Remote Host A    │   │  Remote Host B      │
  │                   │   │                     │
  │  Agent            │   │  Agent              │
  │  systemd service  │   │  systemd service    │
  │  non-root user +  │   │  non-root user +    │
  │  sudoers          │   │  sudoers            │
  │  smartmontools    │   │  smartmontools      │
  └───────────────────┘   └─────────────────────┘
```

**Infrastructure dependencies:**

| Dependency | Where | Notes |
|---|---|---|
| PostgreSQL | Central host | Already provisioned; database `smart_disk_monitor` must exist |
| smartmontools | Each monitored host | Must be installed; agent will fail enumeration if absent |
| Python 3.x runtime | Each monitored host + central host | Required for agent and web server |
| systemd | Each host | Manages agent process lifecycle; restarts on failure |
| sudo | Each monitored host | Non-root agent user must have a sudoers entry for `smartctl` only |
| Network connectivity | Remote hosts → central host | TCP to Postgres port; no Postgres port exposed to untrusted networks |

**Agent deployment procedure (per remote host):**

1. SSH key exchange between central host and remote host (one-time, performed by sysadmin).
2. Copy agent code to remote host (e.g. via `scp` or config management).
3. Create non-root user; add sudoers entry restricted to `smartctl`.
4. Install smartmontools.
5. Install systemd unit file; enable and start service.

**Web server startup:**

- Listens on `0.0.0.0:8080` by default; port is configurable via environment variable or config file.
- No reverse proxy required for v1.
- Database connection parameters are supplied via environment variable or config file. Credentials are never stored in source code.

---

## 6. Failure Mode Mitigations

The following failure modes are addressed explicitly in this architecture. Items 3 (concurrent agent writes) and 5 (new device mid-cycle) are handled by design and require no additional mitigation.

### FM-1: smartctl probe loop hangs (hung USB device or unresponsive disk)

**Mitigation:** Every `smartctl` subprocess invocation — both in Flag Detector and SMART Collector — is wrapped with a configurable per-device timeout (default: 30 seconds). If the subprocess does not exit within the timeout, it is killed, the device is marked with `health_status = "UNKNOWN"` and `error = "timeout"`, and the pipeline continues with the next device. The timed-out record is not written to the database.

### FM-2: Flag detection false positive (smartctl exits 0 but returns partial or corrupt data)

**Mitigation:** After SMART Collector parses the output, it validates that `health_status` is a non-null, non-empty string before producing a `DeviceReading`. If the field cannot be determined, `health_status` is set to `"UNKNOWN"` (never null). The DB Writer contract requires `health_status` to be non-null; this is enforced at the SMART Collector → DB Writer boundary. Rows with `health_status = "UNKNOWN"` are still written so that the operator can see the device was seen but not queryable.

### FM-4: PostgreSQL unreachable at agent startup

**Mitigation:** The DB Writer performs an explicit connection test at agent startup before the first collection cycle. If the connection fails, it retries with exponential backoff (e.g. 2s, 4s, 8s, …) up to a configurable maximum wait. Once connected, transient connection losses during a cycle cause the affected batch records to be logged and skipped; the agent does not exit. The Scheduler continues issuing cycles; the next cycle will attempt reconnection.

### FM-6: Web table shows stale data (agent on one host has been down for hours)

**Mitigation:** The `collected_at` timestamp is displayed as a column in the HTML table for every device row. The operator can see immediately which readings are recent and which are stale. No automatic alerting is provided in v1; the timestamp is the sole staleness indicator.

---

## 7. References

No external URLs were fetched during this architecture design. All decisions are grounded in PROJECT.md, SPEC.md, and the confirmed requirements provided inline.
