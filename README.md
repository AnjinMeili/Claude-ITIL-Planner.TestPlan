# SMART Disk Health Monitor

A SMART disk health monitoring system. A collection agent runs on each monitored Linux machine, queries all attached disk devices via `smartctl` with auto-detected per-device options, and writes results to a central PostgreSQL database. A web application reads from PostgreSQL and renders a single table showing all devices across all machines.

## Requirements

- Python 3.11+ on all hosts
- `smartmontools` ≥ 7.0 on each monitored host
- PostgreSQL with database `smart_disk_monitor` on the central host
- Linux only

## Quick start (local, single machine)

```bash
pip install -r requirements.txt
cp .env.example .env
# edit .env — set DATABASE_URL to your Postgres instance
psql $DATABASE_URL -f db/schema.sql

# Run the agent (requires sudo smartctl — see Privileges below)
python -m agent

# In a separate terminal, run the web server
python -m web
# Open http://localhost:8080
```

## Deploying to remote hosts

### 1. SSH key exchange (one-time per host)

```bash
ssh-copy-id smartmon@remote-host
```

### 2. Create the agent user and sudoers entry on the remote host

```bash
sudo useradd -r -s /bin/false smartmon
echo 'smartmon ALL=(ALL) NOPASSWD: /usr/bin/smartctl' | sudo tee /etc/sudoers.d/smartmon
sudo chmod 440 /etc/sudoers.d/smartmon
```

### 3. Install smartmontools on the remote host

```bash
sudo apt install smartmontools      # Debian/Ubuntu
sudo dnf install smartmontools      # RHEL/Fedora
```

Verify version: `smartctl --version` — must be ≥ 7.0 for JSON output support.

### 4. Copy agent code to the remote host

```bash
scp -r agent/ shared/ requirements.txt smartmon@remote-host:/opt/smart-agent/
```

### 5. Create the .env file on the remote host

```bash
ssh smartmon@remote-host
cat > /opt/smart-agent/.env <<EOF
DATABASE_URL=postgresql://postgres:password@<central-host-ip>:5432/smart_disk_monitor
AGENT_POLLING_INTERVAL_SECONDS=300
AGENT_DEVICE_TIMEOUT_SECONDS=30
EOF
```

**Note:** Use the central host's network IP address — not `localhost`.

### 6. Verify PostgreSQL is reachable from the remote host

```bash
psql $DATABASE_URL -c 'SELECT 1'
```

If blocked, see *PostgreSQL network access* below.

### 7. Install and start the systemd service

```bash
scp infra/smart-agent.service smartmon@remote-host:/etc/systemd/system/
ssh smartmon@remote-host sudo systemctl daemon-reload
ssh smartmon@remote-host sudo systemctl enable --now smart-agent
ssh smartmon@remote-host sudo systemctl status smart-agent
```

### 8. Deploy the web server (central host only)

```bash
cp infra/smart-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now smart-web
```

## PostgreSQL network access

Remote agents connect to PostgreSQL directly over TCP (port 5432). Two options:

**Option A — Allow remote connections in pg_hba.conf (recommended for local networks)**

Add to `/etc/postgresql/*/main/pg_hba.conf`:
```
host    smart_disk_monitor    postgres    <agent-host-ip>/32    md5
```
Then: `sudo systemctl reload postgresql`

**Option B — SSH tunnel (if direct port access is not available)**

On the remote agent host, create a persistent tunnel:
```bash
ssh -N -L 5433:localhost:5432 user@central-host &
```
Then set `DATABASE_URL=postgresql://postgres:password@localhost:5433/smart_disk_monitor` in the agent's `.env`.

## Privileges

The agent runs as a non-root user (`smartmon`) with a sudoers entry restricted to `smartctl` only. No broader privileges are required or granted.

## Running tests

```bash
# Unit tests (no external dependencies)
python -m pytest tests/ -m "not integration"

# Integration tests (require live Postgres + smartctl on Linux)
DATABASE_URL=postgresql://... python -m pytest tests/ -m integration
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | *(required)* | PostgreSQL connection string |
| `AGENT_POLLING_INTERVAL_SECONDS` | `300` | Collection interval in seconds |
| `AGENT_DEVICE_TIMEOUT_SECONDS` | `30` | Per-device smartctl timeout |
| `WEB_PORT` | `8080` | Web server listen port |
| `LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
