# PROJECT.md

## Problem Statement

Monitoring disk health across even a small fleet of Linux machines is operationally fragile. SMART data is available via `smartmontools`, but retrieving it requires SSH-ing into each machine and running `smartctl` with device-specific flags — the correct options vary by drive type (SATA, NVMe, USB-attached, drives behind RAID controllers), and there is no single command that works for all devices. Without a centralized view, degraded drives go unnoticed until failure. The manual process of checking each machine, knowing the right flags per device, and mentally tracking trends across drives is unsustainable even for a small homelab or personal server fleet.

## Target Audience

**Primary:** A solo system administrator or developer managing 1–5 Linux machines personally, who wants disk health visibility without maintaining per-machine scripts or SSH sessions to retrieve SMART data on demand.

**Secondary:** Small teams where one person is responsible for infrastructure health and needs a passive, always-current view of disk status.

## Success Metrics

1. All attached disk devices across monitored machines are visible in a single web table without any manual SSH or CLI interaction after initial setup.
2. Each device is queried with the correct `smartctl` options for its type — no device returns an error due to wrong flags.
3. SMART data collected from each machine is stored in PostgreSQL and persists across agent restarts, enabling trend visibility over time.
4. A new disk added to a monitored machine appears in the web UI without requiring configuration changes.

## Timeline and Milestones

**Phase 1 — Data collection (Days 1–2)**
Milestone: `smartctl` output for all disk devices on the host machine is parsed, normalized, and written to PostgreSQL with correct per-device options applied automatically.

**Phase 2 — Web display (Days 3–4)**
Milestone: A browser-accessible table shows current SMART data for all devices, readable without any CLI access.

**Phase 3 — Multi-machine support (Days 5–7)**
Milestone: Data from at least two separate Linux machines appears in the same web table, collected without manual intervention on each machine after initial agent deployment.

## Constraints

- **Technical:** Linux only; `smartmontools` must be installed on each monitored machine. PostgreSQL is available and will serve as the sole data store.
- **Technical:** The data collection agent must handle per-device `smartctl` option discovery automatically — no hardcoded device maps.
- **Resource:** Solo developer; no team, no budget.
- **Scope (v1):** No alerting, no email/SMS notifications, no authentication on the web UI. Display only.
- **Scope (v1):** Windows and macOS hosts are out of scope.
