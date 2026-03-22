# Agent Dashboard

A web-based dashboard for tracking Claude Code agent sessions across multiple projects. See at a glance which agents are active, what they're working on, how long they've been running, and what they cost.

Accessible from any device on your local network — desktop, phone, or tablet.

## Screenshot

```
+-------------------------------------------+
| AGENT DASH              [2 active] $10.67 |
+-------------------------------------------+
| MUZEUMZ                           1 active|
|   "Build dashboard..."     42m   $10.67   |
|   opus-4-6     last: Write     3.2M in    |
+-------------------------------------------+
| CASTLEZ                             idle  |
| THEATERZ                            idle  |
| ZOOZ                                idle  |
+-------------------------------------------+
```

## Requirements

- **macOS** (Linux works but without auto-start service)
- **Python 3.10+** with pip
- **Claude Code** installed (`~/.claude/` directory must exist)

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/JohnSkiffington/Agent_Dashboard.git
cd Agent_Dashboard

# 2. Run the installer
bash install.sh
```

That's it. The installer will:

1. Install the Python dependency (Flask)
2. Initialize the SQLite database
3. Import your existing Claude Code session history
4. Configure Claude Code hooks for live tracking
5. Start the dashboard as a background service (macOS)

Open **http://localhost:5111/** when it's done.

## Accessing from Other Devices

The installer prints your local network URL (e.g., `http://192.168.1.x:5111/`). Open this on any device connected to the same WiFi network — phones, tablets, other computers.

## How It Works

```
Claude Code session
  | (hooks: SessionStart, PostToolUse, Stop)
  v
hook.py  -->  POST to localhost:5111/api/hook
  |
  v
Flask server (app.py)  -->  SQLite database
  |                          ^
  v                          |
Web dashboard (polling)    scanner.py (reads token usage from transcripts)
```

**Active tracking:** Three Claude Code hooks fire automatically during every session:

| Hook | When | What it captures |
|------|------|------------------|
| `SessionStart` | Agent begins | Project, working directory |
| `PostToolUse` | After each tool call | Tool name, timestamp |
| `Stop` | Agent finishes | End time, final status |

**Token & cost tracking:** A background thread reads Claude Code's JSONL transcript files every 30 seconds to calculate token counts and estimated costs.

**Staleness detection:** Another background thread checks every 60 seconds whether active sessions are still running (by PID). Dead sessions are automatically marked as completed.

## Project Detection

The dashboard groups sessions by project. It detects the project name from the working directory:

- `/Users/you/DEV/PRODUCTS/MUZEUMZ/...` → **MUZEUMZ**
- `/Users/you/DEV/PRODUCTS/CASTLEZ/src/...` → **CASTLEZ**
- `/Users/you/some/other/path` → uses the directory name as the project

To customize detection, edit the `detect_project()` function in `scanner.py`.

## Managing the Service

```bash
# Check if the dashboard is running
curl -s http://localhost:5111/api/sessions | head -5

# Restart the service (macOS)
launchctl kickstart -k gui/$(id -u)/com.agentdash.server

# Stop the service
launchctl bootout gui/$(id -u)/com.agentdash.server

# Start the service
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.agentdash.server.plist

# Run manually (foreground, for debugging)
cd /path/to/Agent_Dashboard && python3 app.py
```

## Uninstalling

```bash
bash uninstall.sh
```

This stops the service, removes the Claude Code hooks, and preserves your database. To fully delete everything:

```bash
bash uninstall.sh
rm -rf /path/to/Agent_Dashboard
```

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Dashboard web page |
| `/api/sessions` | GET | All sessions grouped by project |
| `/api/session/<id>` | GET | Detail for one session with event timeline |
| `/api/hook` | POST | Receives events from Claude Code hooks |

## File Structure

```
Agent_Dashboard/
  app.py                # Flask server and API
  hook.py               # Claude Code hook (stdin JSON -> POST)
  db.py                 # SQLite schema and queries
  cost.py               # Model pricing and cost calculation
  scanner.py            # JSONL transcript reader and backfill
  install.sh            # Installer
  uninstall.sh          # Uninstaller
  requirements.txt      # Python dependencies
  com.agentdash.server.plist  # macOS launchd template
  static/
    style.css           # Responsive CSS with dark/light mode
    dash.js             # Dashboard polling and rendering
  templates/
    index.html          # Dashboard HTML template
```

## Customization

- **Port:** Change `5111` in `app.py` and `hook.py`
- **Polling interval:** Change `POLL_INTERVAL` in `static/dash.js` (default: 5 seconds)
- **Token scan interval:** Change `time.sleep(30)` in `app.py` `token_scanner_loop`
- **Model pricing:** Update `MODEL_PRICING` in `cost.py` when new models release
- **Project detection:** Edit `detect_project()` in `scanner.py`
