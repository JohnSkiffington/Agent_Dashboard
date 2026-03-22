#!/bin/bash
set -euo pipefail

DASH_DIR="$HOME/DEV/TOOLS/AGENT-DASH"
PLIST_NAME="com.agentdash.server"
PLIST_DEST="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"
PYTHON3=$(which python3)

echo "=== Agent Dashboard Uninstaller ==="

# 1. Stop and remove launchd service
echo "[1/3] Stopping service..."
launchctl bootout "gui/$(id -u)/$PLIST_NAME" 2>/dev/null || true
rm -f "$PLIST_DEST"
echo "  Service removed."

# 2. Remove hooks from settings.json
echo "[2/3] Removing Claude Code hooks..."
$PYTHON3 -c "
import json, os

settings_path = os.path.expanduser('~/.claude/settings.json')
try:
    with open(settings_path) as f:
        settings = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    print('  No settings to clean.')
    exit(0)

hooks = settings.get('hooks', {})
modified = False
for event in ['SessionStart', 'Stop', 'PostToolUse']:
    if event in hooks:
        before = len(hooks[event])
        hooks[event] = [h for h in hooks[event] if 'AGENT-DASH' not in h.get('command', '')]
        if len(hooks[event]) < before:
            modified = True
            print(f'  Removed {event} hook')
        if not hooks[event]:
            del hooks[event]

if not hooks:
    settings.pop('hooks', None)

if modified:
    with open(settings_path, 'w') as f:
        json.dump(settings, f, indent=2)
    print('  Settings saved.')
else:
    print('  No hooks found to remove.')
"

# 3. Note about data
echo "[3/3] Cleanup notes:"
echo "  Database preserved at: $DASH_DIR/dashboard.db"
echo "  To fully remove: rm -rf $DASH_DIR"
echo ""
echo "=== Uninstall Complete ==="
