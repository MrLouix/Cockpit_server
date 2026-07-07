---
name: systemd-user-service
description: Create systemd user-level services (systemctl --user) + update scripts for user's applications, managed via cockpit_server.
---

# Systemd User Service Pattern

## When to use

User asks to manage any application they use — create a service, update it, restart it, or monitor it. Always: **user-level** (`systemctl --user`), never system-level.

## Workflow

### Step 1: Create service file

Write `~/.config/systemd/user/<app>.service`:

```ini
[Unit]
Description=<App name>
After=network.target

[Service]
Type=simple
WorkingDirectory=<app directory>
ExecStart=<full path to executable/command>
Restart=on-failure
RestartSec=5
StandardOutput=append:<app dir>/server.log
StandardError=append:<app dir>/server.log

[Install]
WantedBy=default.target
```

**Key rules:**
- NO `User=`/`Group=` — user-level services run as current user
- Install to `~/.config/systemd/user/`
- Use `WantedBy=default.target` (not `multi-user.target`)
- Log to `<app dir>/server.log` via append

### Step 2: Install service

```bash
mkdir -p ~/.config/systemd/user
cp <app>/<app>.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now <app>.service
```

### Step 3: Create update script

Write `<app>-update.sh` in the app directory:

```bash
#!/bin/bash
set -e
SERVICE="<app>.service"

echo "=== <App Name> Update ==="

# 1. Stop
echo "[1/3] Stopping service..."
systemctl --user stop "$SERVICE"
echo "  ✓ Stopped"

# 2. Reinstall/upgrade (app-specific)
echo "[2/3] Reinstalling..."
# Replace with app-specific install: pip install, npm install, git pull, etc.
echo "  ✓ Reinstalled"

# 3. Restart
echo "[3/3] Restarting service..."
systemctl --user daemon-reload
systemctl --user start "$SERVICE"
sleep 2

# Verify
if systemctl --user is-active --quiet "$SERVICE"; then
    echo "  ✓ Service active"
    echo "  Logs: journalctl --user -u $SERVICE --tail=30 -f"
    exit 0
else
    echo "  ✗ Service failed to start"
    echo "  Logs: journalctl --user -u $SERVICE --no-pager -n 50"
    exit 1
fi
```

### Step 4: Verify

```bash
systemctl --user status <app>.service
journalctl --user -u <app>.service --tail=30
```

## Pitfalls

- **NEVER use `sudo systemctl` or `/etc/systemd/system/`** — always `systemctl --user` and `~/.config/systemd/user/`
- **NEVER set `User=` or `Group=`** in user-level services — they are already user-scoped
- If `systemctl --user` returns empty/error, the user session may need `loginctl enable-linger <user>` (system persists services after logout)
- Always `daemon-reload` before first use and after changes
- The service file is a TEMPLATE — see `templates/` for ready-to-use starters
- App-specific headless flags (Electron apps): see `references/aionui-service.md`

## WSL / Headless Pitfall: XDG_RUNTIME_DIR

On WSL or any environment where `XDG_RUNTIME_DIR` is not set, `systemctl --user` fails:
```
Failed to connect to bus: No medium found
```
Fix before every `systemctl --user` call:
```bash
export XDG_RUNTIME_DIR=/run/user/$(id -u)
```
Add to `~/.bashrc` if you use `systemctl --user` regularly in interactive shells.

## Headless Electron Apps — Required Flags

Electron-based apps (AionUi, VS Code, etc.) require these flags when running headless on Linux without a display server:

| Flag | Purpose |
|------|---------|
| `--no-sandbox` | Required on Linux as root/WSL |
| `--headless=new` | New headless mode (not deprecated `--headless`) |
| `--disable-gpu` | No GPU hardware available |
| `--disable-dev-shm-usage` | Avoid shared-memory issues |
| `--remote` | Expose WebUI for remote access |

Example service ExecStart:
```ini
ExecStart=/usr/bin/AionUi --no-sandbox --headless=new --webui --remote --disable-gpu --disable-dev-shm-usage
```
