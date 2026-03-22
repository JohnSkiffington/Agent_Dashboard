#!/bin/bash
set -euo pipefail

DASH_DIR="$HOME/DEV/TOOLS/AGENT-DASH"
PLIST_NAME="com.agentdash.server"
PLIST_DEST="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"
PYTHON3=$(which python3)

echo "=== Agent Dashboard Installer ==="

# 1. Install Python dependencies
echo "[1/5] Installing Python dependencies..."
pip3 install -q flask

# 2. Create logs directory
echo "[2/5] Creating logs directory..."
mkdir -p "$DASH_DIR/logs"

# 3. Initialize database
echo "[3/5] Initializing database..."
cd "$DASH_DIR"
$PYTHON3 db.py

# 4. Inject hooks into ~/.claude/settings.json
echo "[4/5] Configuring Claude Code hooks..."
$PYTHON3 -c "
import json, os

settings_path = os.path.expanduser('~/.claude/settings.json')

# Read existing settings
try:
    with open(settings_path) as f:
        settings = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    settings = {}

# Ensure hooks key exists
if 'hooks' not in settings:
    settings['hooks'] = {}

hook_cmd = '$PYTHON3 $DASH_DIR/hook.py'
hook_entry = {'type': 'command', 'command': hook_cmd, 'timeout': 5}

for event in ['SessionStart', 'Stop', 'PostToolUse']:
    if event not in settings['hooks']:
        settings['hooks'][event] = []
    # Avoid duplicates
    existing_cmds = [h.get('command', '') for h in settings['hooks'][event]]
    if hook_cmd not in existing_cmds:
        settings['hooks'][event].append(hook_entry)
        print(f'  Added {event} hook')
    else:
        print(f'  {event} hook already exists')

with open(settings_path, 'w') as f:
    json.dump(settings, f, indent=2)
print('  Settings saved.')
"

# 5. Install launchd service
echo "[5/5] Installing launchd service..."
if [ -f "$PLIST_DEST" ]; then
    launchctl bootout "gui/$(id -u)/$PLIST_NAME" 2>/dev/null || true
fi
sed "s|__PYTHON3__|$PYTHON3|g; s|__DASH_DIR__|$DASH_DIR|g" "$DASH_DIR/com.agentdash.server.plist" > "$PLIST_DEST"
launchctl bootstrap "gui/$(id -u)" "$PLIST_DEST"

# Get local IP
LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || echo "localhost")

echo ""
echo "=== Installation Complete ==="
echo "Dashboard: http://${LOCAL_IP}:5111/"
echo "Local:     http://localhost:5111/"
echo ""
echo "To uninstall: bash $DASH_DIR/uninstall.sh"
