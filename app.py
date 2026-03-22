#!/usr/bin/env python3
"""Agent Dashboard — Flask server for tracking Claude Code agents."""

import json
import os
import threading
import time

from flask import Flask, jsonify, render_template, request

import db
import scanner

app = Flask(__name__)

PRODUCTS_ROOT = os.path.expanduser("~/DEV/PRODUCTS")

# Known products — auto-discovered from filesystem
def get_known_products():
    """List product directories under ~/DEV/PRODUCTS/."""
    if not os.path.isdir(PRODUCTS_ROOT):
        return []
    return sorted([
        d for d in os.listdir(PRODUCTS_ROOT)
        if os.path.isdir(os.path.join(PRODUCTS_ROOT, d))
    ])


# --- API Endpoints ---

@app.route("/")
def index():
    """Serve the dashboard page."""
    return render_template("index.html")


@app.route("/api/sessions")
def api_sessions():
    """Return all sessions grouped by project with token totals."""
    projects = db.get_sessions_grouped()

    # Ensure all known products appear even if no sessions
    for product in get_known_products():
        if product not in projects:
            projects[product] = {"active_sessions": [], "recent_sessions": []}

    # Summary stats
    total_active = sum(
        len(p["active_sessions"]) for p in projects.values()
    )
    total_cost_today = 0.0
    today_start_ms = int(time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1)) * 1000)
    for p in projects.values():
        for s in p["active_sessions"] + p["recent_sessions"]:
            if s.get("started_at", 0) >= today_start_ms:
                total_cost_today += s.get("estimated_cost_usd") or 0.0

    monthly = db.get_monthly_summary()

    return jsonify({
        "projects": dict(sorted(projects.items())),
        "summary": {
            "total_active": total_active,
            "total_cost_today_usd": round(total_cost_today, 2),
        },
        "monthly": monthly,
    })


@app.route("/api/session/<session_id>")
def api_session_detail(session_id):
    """Return detail for a single session."""
    detail = db.get_session_detail(session_id)
    if not detail:
        return jsonify({"error": "Session not found"}), 404
    return jsonify(detail)


@app.route("/api/hook", methods=["POST"])
def api_hook():
    """Receive hook events from Claude Code agents."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "No JSON body"}), 400

    event_type = data.get("hook_event_name", "")
    session_id = data.get("session_id", "")
    cwd = data.get("cwd", "")
    project_dir = data.get("project_dir", "") or cwd

    if not session_id:
        return jsonify({"error": "No session_id"}), 400

    now_ms = int(time.time() * 1000)

    if event_type == "SessionStart":
        project_name, project_path = scanner.detect_project(project_dir)
        db.upsert_session(
            session_id=session_id,
            project_name=project_name,
            project_path=project_path,
            started_at=now_ms,
        )
        db.insert_event(session_id, event_type, timestamp=now_ms)

        # Try to read initial prompt from JSONL (may not be available yet)
        jsonl_path = scanner.find_jsonl_for_session(session_id)
        if jsonl_path:
            _, model, prompt = scanner.parse_jsonl_tokens(jsonl_path)
            if model or prompt:
                conn = db.get_conn()
                if model:
                    conn.execute("UPDATE sessions SET model = ? WHERE session_id = ?",
                                 (model, session_id))
                if prompt:
                    conn.execute("UPDATE sessions SET initial_prompt = ? WHERE session_id = ?",
                                 (prompt, session_id))
                conn.commit()
                conn.close()

    elif event_type == "PostToolUse":
        tool_name = data.get("tool_name", "")
        db.insert_event(
            session_id, event_type,
            tool_name=tool_name,
            timestamp=now_ms,
            metadata={"tool_input_preview": str(data.get("tool_input", ""))[:200]},
        )

    elif event_type == "Stop":
        db.insert_event(session_id, event_type, timestamp=now_ms)
        db.end_session(session_id, now_ms)

    return jsonify({"ok": True})


# --- Background Threads ---

def token_scanner_loop():
    """Periodically scan JSONL files for token usage on active sessions."""
    while True:
        try:
            scanner.scan_tokens_for_active_sessions()
        except Exception as e:
            print(f"[token_scanner] Error: {e}")
        time.sleep(30)


def staleness_checker_loop():
    """Periodically check for stale/dead sessions."""
    while True:
        try:
            scanner.check_staleness()
        except Exception as e:
            print(f"[staleness_checker] Error: {e}")
        time.sleep(60)


def start_background_threads():
    """Start background worker threads."""
    t1 = threading.Thread(target=token_scanner_loop, daemon=True)
    t2 = threading.Thread(target=staleness_checker_loop, daemon=True)
    t1.start()
    t2.start()


# --- Main ---

if __name__ == "__main__":
    db.init_db()
    # Backfill on first run
    scanner.backfill_historical()
    start_background_threads()
    print("Agent Dashboard running on http://0.0.0.0:5111/")
    app.run(host="0.0.0.0", port=5111, debug=False)
