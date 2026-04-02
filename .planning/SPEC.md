# SPEC.md

Generated from: `.planning/PROJECT.md`
Date: 2026-04-01

---

## 1. Foundation

### Target Audience

**Primary actor:** A solo system administrator or developer managing 1–5 Linux machines personally. This person wants disk health visibility without maintaining per-machine scripts or opening SSH sessions on demand.

**Secondary actor:** A single infrastructure owner within a small team who needs a passive, always-current view of disk status across machines they are responsible for.

All use cases below are written from the perspective of the primary actor unless otherwise noted.

### Problem Statement

SMART data is available on Linux via `smartmontools`, but retrieving it correctly requires knowing device-specific flags (SATA, NVMe, USB-attached, behind RAID controllers) for each drive. There is no single `smartctl` invocation that works for all devices. Without a centralized view, degraded drives go unnoticed. The manual process of SSH-ing into each machine, knowing the right flags, and mentally tracking trends is unsustainable even for a small personal fleet.

### Success Metrics (from PROJECT.md)

1. All attached disk devices across monitored machines are visible in a single web table without any manual SSH or CLI interaction after initial setup.
2. Each device is queried with the correct `smartctl` options for its type — no device returns an error due to wrong flags.
3. SMART data is stored in PostgreSQL and persists across agent restarts, enabling trend visibility over time.
4. A new disk added to a monitored machine appears in the web UI without requiring configuration changes.

---

## 2. Use Cases

```
UC-01: View current disk health for all machines in a single table
Actor: Solo sysadmin/developer
Precondition: At least one agent is running on at least one monitored machine and has
              written at least one collection record to PostgreSQL.
Summary: The operator opens a browser and sees a table listing every disk device
         discovered across all monitored machines, with current SMART health data for
         each device, without any SSH or CLI interaction.
```

```
UC-02: Collect SMART data from all disk devices on a single monitored machine
Actor: Data collection agent (automated, runs on each Linux host)
Precondition: The agent process is running on a Linux machine where smartmontools is
              installed. PostgreSQL is reachable from the agent.
Summary: The agent discovers all disk devices on the host, determines the correct
         smartctl options for each device, queries each device, and writes the results
         to PostgreSQL.
```

```
UC-03: Auto-detect correct smartctl options per device without hardcoded configuration
Actor: Data collection agent (automated)
Precondition: The agent is performing a collection run. One or more disk devices are
              present on the host. Device types may be mixed (SATA, NVMe, USB, RAID).
Summary: For each discovered device, the agent determines which smartctl flags are
         required for a successful query, using probing or enumeration rather than a
         static device map, so that no device fails due to wrong flags.
```

```
UC-04: Auto-discover a newly attached disk without configuration changes
Actor: Data collection agent (automated); observable outcome verified by sysadmin/developer
Precondition: The agent is already running and has completed at least one prior
              collection cycle. A new disk device is attached to the monitored machine.
Summary: On the next collection cycle after the disk is attached, the agent discovers
         the new device, determines the correct smartctl options for it, and writes its
         SMART data to PostgreSQL. The device then appears in the web UI without any
         manual intervention.
```

```
UC-05: Collect and unify SMART data from multiple machines into one view
Actor: Data collection agent (one instance per machine); solo sysadmin/developer (consumer)
Precondition: Agents are deployed and running on two or more Linux machines. All agents
              write to the same PostgreSQL instance.
Summary: Each agent independently collects data from its host and writes records tagged
         with the host machine identity. The web UI presents all records in a single
         table, distinguishable by machine.
```

```
UC-06: Persist SMART data across agent restarts to support trend visibility
Actor: Data collection agent (automated)
Precondition: The agent has previously written SMART data records to PostgreSQL and is
              then stopped and restarted.
Summary: Historical records written before the restart remain in PostgreSQL and continue
         to be accessible in the web UI. On restart, the agent resumes collecting and
         writing new records without overwriting or deleting prior records.
```

---

## 3. Acceptance Criteria

### UC-01: View current disk health for all machines in a single table

```
AC-01-01 [End-to-end]
Given the web UI is open in a browser and at least one collection record exists in
PostgreSQL,
When the page loads,
Then a table is rendered containing one row per discovered disk device, with columns
for at minimum: host machine identifier, device name, overall SMART health status,
and data collection timestamp. The table must render within 3 seconds on a local
network connection.
```

```
AC-01-02 [End-to-end]
Given disk devices are present across two or more monitored machines and their agents
have each completed at least one collection cycle,
When the operator views the web UI,
Then rows from all monitored machines appear in the same table, each row labeled with
the originating host identifier, with no machine's devices omitted.
```

```
AC-01-03 [End-to-end]
Given the web UI is loaded,
When the operator views the table,
Then no SSH session, terminal command, or manual data retrieval step is required to
see any data shown in the table.
```

### UC-02: Collect SMART data from all disk devices on a single monitored machine

```
AC-02-01 [Integration]
Given the agent is started on a Linux machine with one or more disk devices and
PostgreSQL is reachable,
When one collection cycle completes,
Then a record exists in PostgreSQL for each disk device present on the host at the
time of collection, containing the device identifier, host identifier, SMART health
status, and a UTC timestamp of collection.
```

```
AC-02-02 [Integration]
Given a collection cycle has completed,
When the PostgreSQL records for that cycle are inspected,
Then no device that was present on the host and successfully returned SMART data is
missing from the written records.
```

```
AC-02-03 [Integration]
Given the agent is configured with a polling interval,
When that interval elapses,
Then a new collection cycle begins automatically without operator intervention, and
new records are written to PostgreSQL.
```

### UC-03: Auto-detect correct smartctl options per device without hardcoded configuration

```
AC-03-01 [Integration]
Given a Linux host has at least one SATA disk and at least one NVMe disk attached,
When the agent completes a collection cycle,
Then both devices return valid SMART data (no "device not found" or "invalid flag"
error from smartctl), and each device's record in PostgreSQL contains a non-null
SMART health status.
```

```
AC-03-02 [Integration]
Given a disk device requires a non-default smartctl flag (e.g., a type flag for
USB or RAID-attached devices) to return SMART data successfully,
When the agent queries that device,
Then the agent applies the required flag and writes a successful SMART data record
to PostgreSQL. No record for that device is written with an error status when the
correct flag can be determined.
```

```
AC-03-03 [Unit]
Given a device identifier for which the agent has not seen prior flag configuration,
When the agent performs option detection for that device,
Then the detection procedure executes without reading any hardcoded device-to-flag
mapping file or static configuration entry for that specific device.
```

### UC-04: Auto-discover a newly attached disk without configuration changes

```
AC-04-01 [End-to-end]
Given the agent is running and has completed at least one collection cycle with N
devices recorded, and a new disk is then attached to the host,
When the next collection cycle completes,
Then a record for the new device exists in PostgreSQL and the device appears in the
web UI table, without any restart of the agent or change to any configuration file.
```

```
AC-04-02 [Integration]
Given a new device is attached between two collection cycles,
When the second collection cycle runs,
Then the new device's record is present in PostgreSQL alongside all previously known
device records; no previously known device record is missing.
```

### UC-05: Collect and unify SMART data from multiple machines into one view

```
AC-05-01 [End-to-end]
Given agents are running on two physically separate Linux machines (Machine A and
Machine B), both writing to the same PostgreSQL instance,
When the web UI is loaded after both agents have each completed at least one
collection cycle,
Then the table contains rows from both Machine A and Machine B, each row carries
the correct host identifier, and devices from one machine are not attributed to
the other.
```

```
AC-05-02 [Integration]
Given two agents write records concurrently to the same PostgreSQL instance,
When both writes occur within the same polling interval,
Then all records are persisted without data loss or constraint violation, and the
total row count matches the sum of devices discovered across both machines.
```

### UC-06: Persist SMART data across agent restarts to support trend visibility

```
AC-06-01 [Integration]
Given the agent has written M records to PostgreSQL, and the agent process is then
stopped and restarted,
When the restart completes,
Then all M prior records remain in PostgreSQL with unchanged content, and subsequent
collection cycles append new records rather than replacing existing ones.
```

```
AC-06-02 [Integration]
Given the agent is restarted,
When the first post-restart collection cycle completes,
Then new records are written to PostgreSQL with timestamps later than the pre-restart
records, and the total record count is greater than M.
```

---

## 4. Non-Functional Requirements

### Performance

```
NFR-01: The web UI table must complete its initial render within 3 seconds of the
HTTP request being received, measured on a local network connection with up to
5 monitored machines each having up to 20 disk devices (100 rows total).
```

```
NFR-02: The data collection agent must complete one full collection cycle — device
enumeration, option detection, smartctl queries, and PostgreSQL writes — within
60 seconds per monitored machine under normal conditions (up to 20 devices per host).
```

```
NFR-03: The agent must begin its first collection cycle within 30 seconds of process
startup.
```

```
NFR-04: The agent polling interval must be configurable and must default to no longer
than 5 minutes, so that the web UI reflects the state of a newly attached disk within
two polling intervals of its attachment (within 10 minutes by default).
[NEEDS CONFIRMATION: exact default polling interval not specified in PROJECT.md]
```

### Security

```
NFR-05: The v1 web UI has no authentication or authorization layer. Any client that
can reach the web server's port can view the disk health table. This is an explicit
v1 scope constraint per PROJECT.md.
```

```
NFR-06: All data is stored solely in the local PostgreSQL instance. No SMART data,
host identifiers, or device information is transmitted to any external service or
third-party API.
```

```
NFR-07: The agent must run with only the OS privileges required to invoke smartctl
on the local machine. It must not require broader system access than necessary.
[NEEDS CONFIRMATION: exact required privilege level (e.g., root vs. sudoers entry)
depends on host OS configuration and is not specified in PROJECT.md]
```

### Reliability

```
NFR-08: If PostgreSQL is unavailable when the agent attempts to write a collection
result, the agent must log the failure, must not crash, and must retry on the next
polling cycle. Data collected during the outage that was not written may be discarded
(no in-memory queue required in v1).
[NEEDS CONFIRMATION: whether in-flight data must be buffered during Postgres outages
is not addressed in PROJECT.md]
```

```
NFR-09: If a single disk device fails to return SMART data (e.g., smartctl returns
an error for that device), the agent must log the per-device error and continue
collecting from all remaining devices on the same cycle. A single device failure
must not abort the entire collection cycle.
```

```
NFR-10: The agent must recover automatically from a process crash and resume normal
collection cycles when restarted by the host's process supervisor (e.g., systemd).
The agent itself need not implement crash recovery — it relies on the host process
manager for restart.
[NEEDS CONFIRMATION: the specific process supervisor to be used is not specified
in PROJECT.md]
```

### Observability

```
NFR-11: The agent must emit a structured log entry for each collection cycle that
includes: the host identifier, the number of devices discovered, the number of
devices successfully queried, the number of devices that failed, and the cycle
duration in milliseconds.
```

```
NFR-12: The agent must emit a log entry for each per-device failure that includes:
the device identifier, the smartctl exit code or error message, and the flags that
were attempted.
```

```
NFR-13: The agent must emit a log entry for each PostgreSQL write failure that
includes: the error message returned by PostgreSQL and the number of records that
failed to write.
```

```
NFR-14: The web server must emit a log entry for each HTTP request that includes:
the request timestamp, HTTP method, path, response status code, and response time
in milliseconds.
```

---

## 5. External Dependencies

| # | Dependency | Integration Type | Version | SLA / Availability | Failure Mode | Owner |
|---|---|---|---|---|---|---|
| DEP-01 | PostgreSQL | TCP socket, SQL over libpq or equivalent driver | Confirmed: instance on central host, database `smart_disk_monitor` | Self-hosted, always-on assumed; no formal SLA | Agent logs error and skips write for that cycle; web UI shows stale or no data if Postgres is down | Solo developer (self-hosted) |
| DEP-02 | smartmontools (`smartctl`) | Local process execution (fork/exec) on each agent host, stdout parsing | Any version present on host [NEEDS CONFIRMATION: minimum version for NVMe support — 6.6+ recommended] | Available as long as package is installed; no network dependency | Per-device: agent logs error and skips that device for the cycle. If `smartctl` binary is missing, agent logs fatal error and exits. | Solo developer (self-installed on each host) |
| DEP-03 | Each monitored Linux host | SSH key exchange for agent deployment; agent runs locally on host | Linux (kernel version unspecified) | Availability equals host uptime | Agent process goes down with the host; central Postgres retains all previously written records | Solo developer |

### Dependency Notes

- **DEP-01 — PostgreSQL topology:** PostgreSQL runs on the central host (same machine as the web server), database `smart_disk_monitor`. Agents on remote machines must connect to it using the central host's network address — not `localhost`. Connection credentials are stored in environment variables on each agent host; not hardcoded.
- **DEP-01 — PostgreSQL remote agent access:** Remote agents connect to Postgres over the local network. If direct Postgres port exposure is undesirable, an SSH tunnel per agent host is an alternative — confirm at arch-design.
- **DEP-02 — smartmontools minimum version:** NVMe SMART support requires smartmontools ≥ 6.6 (released 2016). Confirm minimum acceptable version across all monitored hosts. `[NEEDS CONFIRMATION]`
- **DEP-03 — Agent deployment:** Agents are deployed to each monitored machine via SSH key exchange. The deployment method (manual copy, script, or config management) is an operational concern to be defined in the release runbook.
- **DEP-03 — Agent privilege:** The agent runs as a non-root user with a sudoers entry granting `smartctl` execution. No broader privilege is required or granted.

---

## 6. Out of Scope (v1)

The following items are explicitly excluded per PROJECT.md and must not be implemented in v1:

- Authentication or authorization on the web UI.
- Alerting, notifications, email, or SMS for any disk health condition.
- Windows or macOS monitored hosts.
- Hardcoded per-device `smartctl` flag configuration (auto-detection is required).
- Any external data transmission — all data remains in the local PostgreSQL instance.

---

## 7. Open Items Requiring Confirmation

| # | Item | Status | Location Referenced |
|---|---|---|---|
| OI-01 | Default agent polling interval (NFR-04) | Open | Not specified in PROJECT.md |
| OI-02 | Whether in-flight collection data must be buffered during PostgreSQL outages (NFR-08) | Open | Not specified in PROJECT.md |
| OI-03 | Process supervisor to be used for agent restart (NFR-10) | Open | Not specified in PROJECT.md |
| OI-04 | Minimum PostgreSQL version required (DEP-01) | Open | Not specified in PROJECT.md |
| OI-05 | PostgreSQL network topology | **Resolved** | PostgreSQL on central host, database `smart_disk_monitor`; agents connect via network address |
| OI-06 | Minimum smartmontools version for NVMe support (DEP-02) | Open | Recommend ≥ 6.6; confirm across all hosts |
| OI-07 | Agent deployment method to each monitored machine | **Resolved** | SSH key exchange |
| OI-08 | Agent privilege level required to run smartctl | **Resolved** | Non-root user with sudoers entry for `smartctl` |
