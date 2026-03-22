#!/bin/bash
set -euo pipefail

# Agent Dashboard Installer
# Works from wherever the repo is cloned.

DASH_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_NAME="com.agentdash.server"
PLIST_DEST="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"

echo "=== Agent Dashboard Installer ==="
echo "Install from: $DASH_DIR"
echo ""

# --- Preflight checks ---

echo "[preflight] Checking requirements..."

# Python 3
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Install Python 3.10+ and try again."
    exit 1
fi
PYTHON3="$(command -v python3)"
PY_VERSION=$($PYTHON3 --version 2>&1)
echo "  Found $PY_VERSION at $PYTHON3"

# pip3
if ! command -v pip3 &>/dev/null; then
    echo "ERROR: pip3 not found. Install pip and try again."
    exit 1
fi

# Claude Code
CLAUDE_DIR="$HOME/.claude"
if [ ! -d "$CLAUDE_DIR" ]; then
    echo "ERROR: ~/.claude directory not found. Install Claude Code first."
    exit 1
fi
echo "  Found Claude Code at $CLAUDE_DIR"

# Check for port conflict
if lsof -iTCP:5111 -sTCP:LISTEN &>/dev/null; then
    echo "WARNING: Port 5111 is already in use."
    echo "  Another instance may be running. Stop it first or the install will fail."
    read -rp "  Continue anyway? (y/N) " response
    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 1
    fi
fi

echo ""

# --- Step 1: Install Python dependencies ---

echo "[1/5] Installing Python dependencies..."
pip3 install -q flask
echo "  Done."

# --- Step 2: Create logs directory ---

echo "[2/5] Creating logs directory..."
mkdir -p "$DASH_DIR/logs"
echo "  Done."

# --- Step 3: Initialize database ---

echo "[3/5] Initializing database..."
cd "$DASH_DIR"
$PYTHON3 db.py

# --- Step 4: Backfill historical sessions ---

echo "[4/5] Backfilling historical Claude Code sessions..."
$PYTHON3 scanner.py

# --- Step 5: Configure Claude Code hooks ---

echo "[5/5] Configuring Claude Code hooks..."
$PYTHON3 - "$PYTHON3" "$DASH_DIR" <<'PYEOF'
import json, os, sys

python3_path = sys.argv[1]
dash_dir = sys.argv[2]
settings_path = os.path.expanduser("~/.claude/settings.json")

# Read existing settings
try:
    with open(settings_path) as f:
        settings = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    settings = {}

# Ensure hooks key exists
if "hooks" not in settings:
    settings["hooks"] = {}

hook_cmd = f"{python3_path} {dash_dir}/hook.py"
hook_entry = {"type": "command", "command": hook_cmd, "timeout": 5}

for event in ["SessionStart", "Stop", "PostToolUse"]:
    if event not in settings["hooks"]:
        settings["hooks"][event] = []
    # Remove any old AGENT-DASH hooks (in case of reinstall with different path)
    settings["hooks"][event] = [
        h for h in settings["hooks"][event]
        if "AGENT-DASH" not in h.get("command", "") and "agent-dash" not in h.get("command", "")
    ]
    settings["hooks"][event].append(hook_entry)
    print(f"  Configured {event} hook")

with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)
print("  Settings saved.")
PYEOF

# --- Step 6: Install launchd service (macOS only) ---

if [[ "$OSTYPE" == darwin* ]]; then
    echo ""
    echo "[launchd] Installing background service..."
    if [ -f "$PLIST_DEST" ]; then
        launchctl bootout "gui/$(id -u)/$PLIST_NAME" 2>/dev/null || true
    fi
    sed "s|__PYTHON3__|$PYTHON3|g; s|__DASH_DIR__|$DASH_DIR|g" \
        "$DASH_DIR/com.agentdash.server.plist" > "$PLIST_DEST"
    launchctl bootstrap "gui/$(id -u)" "$PLIST_DEST"
    echo "  Service installed and started."
    echo "  The dashboard will auto-start on login."
else
    echo ""
    echo "[note] Not macOS — skipping launchd service."
    echo "  Start the server manually: cd $DASH_DIR && python3 app.py"
fi

# --- Done ---

# Get local IP
LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")

echo ""
echo "========================================="
echo "  Agent Dashboard installed successfully"
echo "========================================="
echo ""
echo "  Local:   http://localhost:5111/"
echo "  Network: http://${LOCAL_IP}:5111/"
echo ""
echo "  Open the network URL on your phone or"
echo "  other devices on the same WiFi."
echo ""
echo "  To uninstall: bash $DASH_DIR/uninstall.sh"
echo ""
