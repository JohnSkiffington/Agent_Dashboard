"""Scans Claude Code JSONL transcripts for token usage and historical session data."""

import glob
import json
import os
import signal
import time

import db
import cost


CLAUDE_DIR = os.path.expanduser("~/.claude")
SESSIONS_DIR = os.path.join(CLAUDE_DIR, "sessions")
PROJECTS_DIR = os.path.join(CLAUDE_DIR, "projects")
PRODUCTS_ROOT = os.path.expanduser("~/DEV/PRODUCTS")


def detect_project(cwd):
    """Derive project name and path from a working directory."""
    if cwd.startswith(PRODUCTS_ROOT):
        relative = cwd[len(PRODUCTS_ROOT):].strip("/")
        if relative:
            project_name = relative.split("/")[0]
            return project_name, os.path.join(PRODUCTS_ROOT, project_name)
    # Fallback: last directory component
    return os.path.basename(cwd), cwd


def find_jsonl_for_session(session_id):
    """Find the JSONL transcript file for a given session ID."""
    for jsonl in glob.glob(os.path.join(PROJECTS_DIR, "*", f"{session_id}.jsonl")):
        return jsonl
    return None


def parse_jsonl_tokens(jsonl_path):
    """Parse a JSONL transcript and return aggregated token counts, model, and first user prompt."""
    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read": 0,
        "cache_create": 0,
    }
    model = None
    first_prompt = None

    try:
        with open(jsonl_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Capture first user prompt
                if first_prompt is None and entry.get("type") == "user":
                    msg = entry.get("message", {})
                    content = msg.get("content", "")
                    if isinstance(content, str) and content:
                        first_prompt = content[:500]  # Truncate long prompts
                    elif isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                first_prompt = block.get("text", "")[:500]
                                break

                # Aggregate token usage from assistant messages
                if entry.get("type") == "assistant":
                    msg = entry.get("message", {})
                    usage = msg.get("usage", {})
                    if usage:
                        totals["input_tokens"] += usage.get("input_tokens", 0)
                        totals["output_tokens"] += usage.get("output_tokens", 0)
                        totals["cache_read"] += usage.get("cache_read_input_tokens", 0)
                        totals["cache_create"] += usage.get("cache_creation_input_tokens", 0)
                    if not model and msg.get("model"):
                        model = msg["model"]
    except (OSError, IOError):
        pass

    return totals, model, first_prompt


def is_pid_running(pid):
    """Check if a process with the given PID is still running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def scan_tokens_for_active_sessions():
    """Scan JSONL files for all active sessions and update token totals."""
    active_ids = db.get_active_session_ids()
    for session_id in active_ids:
        jsonl_path = find_jsonl_for_session(session_id)
        if not jsonl_path:
            continue

        totals, model, first_prompt = parse_jsonl_tokens(jsonl_path)

        cost_usd = cost.estimate_cost(
            model or "claude-sonnet-4-6",
            totals["input_tokens"],
            totals["output_tokens"],
            totals["cache_read"],
            totals["cache_create"],
        )
        db.update_token_totals(
            session_id,
            totals["input_tokens"],
            totals["output_tokens"],
            totals["cache_read"],
            totals["cache_create"],
            cost_usd,
        )

        # Update model and prompt if we found them
        if model or first_prompt:
            conn = db.get_conn()
            if model:
                conn.execute("UPDATE sessions SET model = ? WHERE session_id = ? AND model IS NULL",
                             (model, session_id))
            if first_prompt:
                conn.execute("UPDATE sessions SET initial_prompt = ? WHERE session_id = ? AND initial_prompt IS NULL",
                             (first_prompt, session_id))
            conn.commit()
            conn.close()


def check_staleness():
    """Check active sessions for staleness: PID dead or no recent events."""
    active_ids = db.get_active_session_ids()

    # Build a map of session_id -> pid from session files
    pid_map = {}
    if os.path.isdir(SESSIONS_DIR):
        for fname in os.listdir(SESSIONS_DIR):
            if fname.endswith(".json"):
                try:
                    with open(os.path.join(SESSIONS_DIR, fname)) as f:
                        sdata = json.load(f)
                    pid_map[sdata.get("sessionId")] = sdata.get("pid")
                except (json.JSONDecodeError, OSError):
                    continue

    for session_id in active_ids:
        pid = pid_map.get(session_id)
        if pid and not is_pid_running(pid):
            db.end_session(session_id)
            continue

        # Check for event staleness (no events in 30 min)
        conn = db.get_conn()
        row = conn.execute(
            "SELECT MAX(timestamp) as last_ts FROM events WHERE session_id = ?",
            (session_id,)
        ).fetchone()
        conn.close()

        if row and row["last_ts"]:
            age_minutes = (time.time() * 1000 - row["last_ts"]) / 60000
            if age_minutes > 30:
                db.mark_stale(session_id)


def backfill_historical():
    """Scan ~/.claude/ for historical sessions and import them."""
    if not os.path.isdir(SESSIONS_DIR):
        print("No sessions directory found.")
        return

    imported = 0
    for fname in os.listdir(SESSIONS_DIR):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(SESSIONS_DIR, fname)
        try:
            with open(fpath) as f:
                sdata = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        session_id = sdata.get("sessionId")
        cwd = sdata.get("cwd", "")
        started_at = sdata.get("startedAt", 0)
        pid = sdata.get("pid")

        if not session_id or not cwd:
            continue

        project_name, project_path = detect_project(cwd)

        # Find and parse the JSONL
        jsonl_path = find_jsonl_for_session(session_id)
        model = None
        first_prompt = None
        totals = {"input_tokens": 0, "output_tokens": 0, "cache_read": 0, "cache_create": 0}

        if jsonl_path:
            totals, model, first_prompt = parse_jsonl_tokens(jsonl_path)

        # Determine status
        status = "active" if pid and is_pid_running(pid) else "completed"

        db.upsert_session(
            session_id=session_id,
            project_name=project_name,
            project_path=project_path,
            started_at=started_at,
            model=model,
            initial_prompt=first_prompt,
        )

        # Set status
        if status == "completed":
            db.end_session(session_id, started_at)  # Use start time as fallback end time

        # Update token totals
        if any(v > 0 for v in totals.values()):
            cost_usd = cost.estimate_cost(
                model or "claude-sonnet-4-6",
                totals["input_tokens"],
                totals["output_tokens"],
                totals["cache_read"],
                totals["cache_create"],
            )
            db.update_token_totals(
                session_id,
                totals["input_tokens"],
                totals["output_tokens"],
                totals["cache_read"],
                totals["cache_create"],
                cost_usd,
            )

        imported += 1

    print(f"Backfilled {imported} sessions.")


if __name__ == "__main__":
    db.init_db()
    backfill_historical()
