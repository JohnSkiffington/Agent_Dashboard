#!/usr/bin/env python3
"""Claude Code hook — forwards event data to the Agent Dashboard server.

This script is called by Claude Code on SessionStart, PostToolUse, and Stop events.
It reads JSON from stdin, adds project context, and POSTs to the dashboard API.
Designed to be fast and never block Claude Code.
"""

import json
import os
import sys
import urllib.request

DASH_URL = "http://127.0.0.1:5111/api/hook"


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    data["project_dir"] = os.environ.get("CLAUDE_PROJECT_DIR", "")

    req = urllib.request.Request(
        DASH_URL,
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=2)
    except Exception:
        pass  # Fire-and-forget; never block Claude Code

    sys.exit(0)


if __name__ == "__main__":
    main()
