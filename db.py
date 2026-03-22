"""SQLite database schema and helpers."""

import os
import sqlite3
import time
import json

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.db")


def get_conn():
    """Get a SQLite connection with WAL mode for concurrent reads."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id    TEXT PRIMARY KEY,
            project_name  TEXT NOT NULL,
            project_path  TEXT NOT NULL,
            agent_type    TEXT NOT NULL DEFAULT 'claude-code',
            started_at    INTEGER NOT NULL,
            ended_at      INTEGER,
            status        TEXT NOT NULL DEFAULT 'active',
            initial_prompt TEXT,
            model         TEXT
        );

        CREATE TABLE IF NOT EXISTS events (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id    TEXT NOT NULL REFERENCES sessions(session_id),
            event_type    TEXT NOT NULL,
            tool_name     TEXT,
            timestamp     INTEGER NOT NULL,
            metadata      TEXT
        );

        CREATE TABLE IF NOT EXISTS token_totals (
            session_id          TEXT PRIMARY KEY REFERENCES sessions(session_id),
            total_input_tokens  INTEGER DEFAULT 0,
            total_output_tokens INTEGER DEFAULT 0,
            total_cache_read    INTEGER DEFAULT 0,
            total_cache_create  INTEGER DEFAULT 0,
            estimated_cost_usd  REAL DEFAULT 0.0,
            last_updated        INTEGER NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
        CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_name);
        CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
    """)
    conn.commit()
    conn.close()


def upsert_session(session_id, project_name, project_path, started_at, agent_type="claude-code", model=None, initial_prompt=None):
    """Insert or update a session."""
    conn = get_conn()
    conn.execute("""
        INSERT INTO sessions (session_id, project_name, project_path, agent_type, started_at, model, initial_prompt)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            model = COALESCE(excluded.model, sessions.model),
            initial_prompt = COALESCE(excluded.initial_prompt, sessions.initial_prompt)
    """, (session_id, project_name, project_path, agent_type, started_at, model, initial_prompt))
    conn.commit()
    conn.close()


def end_session(session_id, ended_at=None):
    """Mark a session as completed."""
    conn = get_conn()
    conn.execute("""
        UPDATE sessions SET status = 'completed', ended_at = ?
        WHERE session_id = ? AND status != 'completed'
    """, (ended_at or int(time.time() * 1000), session_id))
    conn.commit()
    conn.close()


def mark_stale(session_id):
    """Mark a session as stale."""
    conn = get_conn()
    conn.execute("""
        UPDATE sessions SET status = 'stale'
        WHERE session_id = ? AND status = 'active'
    """, (session_id,))
    conn.commit()
    conn.close()


def insert_event(session_id, event_type, tool_name=None, timestamp=None, metadata=None):
    """Insert an event for a session."""
    conn = get_conn()
    conn.execute("""
        INSERT INTO events (session_id, event_type, tool_name, timestamp, metadata)
        VALUES (?, ?, ?, ?, ?)
    """, (session_id, event_type, tool_name, timestamp or int(time.time() * 1000),
          json.dumps(metadata) if metadata else None))
    conn.commit()
    conn.close()


def update_token_totals(session_id, input_tokens, output_tokens, cache_read, cache_create, cost_usd):
    """Upsert token totals for a session."""
    conn = get_conn()
    conn.execute("""
        INSERT INTO token_totals (session_id, total_input_tokens, total_output_tokens,
                                  total_cache_read, total_cache_create, estimated_cost_usd, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            total_input_tokens = excluded.total_input_tokens,
            total_output_tokens = excluded.total_output_tokens,
            total_cache_read = excluded.total_cache_read,
            total_cache_create = excluded.total_cache_create,
            estimated_cost_usd = excluded.estimated_cost_usd,
            last_updated = excluded.last_updated
    """, (session_id, input_tokens, output_tokens, cache_read, cache_create, cost_usd, int(time.time() * 1000)))
    conn.commit()
    conn.close()


def get_sessions_grouped():
    """Get all sessions grouped by project with token totals."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT s.*, t.total_input_tokens, t.total_output_tokens,
               t.total_cache_read, t.total_cache_create, t.estimated_cost_usd
        FROM sessions s
        LEFT JOIN token_totals t ON s.session_id = t.session_id
        ORDER BY s.started_at DESC
    """).fetchall()

    # Get last event per session
    last_events = {}
    for row in conn.execute("""
        SELECT session_id, tool_name, timestamp
        FROM events
        WHERE id IN (SELECT MAX(id) FROM events GROUP BY session_id)
    """).fetchall():
        last_events[row["session_id"]] = {"tool_name": row["tool_name"], "timestamp": row["timestamp"]}

    conn.close()

    projects = {}
    for row in rows:
        proj = row["project_name"]
        if proj not in projects:
            projects[proj] = {"active_sessions": [], "recent_sessions": []}

        session = dict(row)
        session["last_event"] = last_events.get(row["session_id"])

        now_ms = int(time.time() * 1000)
        if session["status"] == "active":
            session["running_for_seconds"] = (now_ms - session["started_at"]) // 1000

        bucket = "active_sessions" if session["status"] in ("active", "stale") else "recent_sessions"
        projects[proj][bucket].append(session)

    # Limit recent to 5 per project
    for proj in projects:
        projects[proj]["recent_sessions"] = projects[proj]["recent_sessions"][:5]

    return projects


def get_session_detail(session_id):
    """Get a single session with its events."""
    conn = get_conn()
    session = conn.execute("""
        SELECT s.*, t.total_input_tokens, t.total_output_tokens,
               t.total_cache_read, t.total_cache_create, t.estimated_cost_usd
        FROM sessions s
        LEFT JOIN token_totals t ON s.session_id = t.session_id
        WHERE s.session_id = ?
    """, (session_id,)).fetchone()

    events = conn.execute("""
        SELECT * FROM events WHERE session_id = ? ORDER BY timestamp ASC
    """, (session_id,)).fetchall()

    conn.close()

    if not session:
        return None

    return {
        "session": dict(session),
        "events": [dict(e) for e in events],
    }


def get_active_session_ids():
    """Get IDs of all active sessions."""
    conn = get_conn()
    rows = conn.execute("SELECT session_id FROM sessions WHERE status = 'active'").fetchall()
    conn.close()
    return [r["session_id"] for r in rows]


def get_monthly_summary():
    """Get token and cost totals for the current month, plus daily breakdown."""
    conn = get_conn()
    import calendar
    now = time.localtime()
    month_start_ms = int(time.mktime((now.tm_year, now.tm_mon, 1, 0, 0, 0, 0, 0, -1)) * 1000)

    # Monthly totals
    row = conn.execute("""
        SELECT
            COUNT(DISTINCT s.session_id) as session_count,
            COALESCE(SUM(t.total_input_tokens), 0) as input_tokens,
            COALESCE(SUM(t.total_output_tokens), 0) as output_tokens,
            COALESCE(SUM(t.total_cache_read), 0) as cache_read,
            COALESCE(SUM(t.total_cache_create), 0) as cache_create,
            COALESCE(SUM(t.estimated_cost_usd), 0) as total_cost
        FROM sessions s
        LEFT JOIN token_totals t ON s.session_id = t.session_id
        WHERE s.started_at >= ?
    """, (month_start_ms,)).fetchone()

    # Daily breakdown for the current month
    days = []
    _, days_in_month = calendar.monthrange(now.tm_year, now.tm_mon)
    for day in range(1, days_in_month + 1):
        day_start_ms = int(time.mktime((now.tm_year, now.tm_mon, day, 0, 0, 0, 0, 0, -1)) * 1000)
        day_end_ms = day_start_ms + 86400000
        day_row = conn.execute("""
            SELECT
                COUNT(DISTINCT s.session_id) as sessions,
                COALESCE(SUM(t.total_input_tokens), 0) + COALESCE(SUM(t.total_cache_read), 0) as input_tokens,
                COALESCE(SUM(t.total_output_tokens), 0) as output_tokens,
                COALESCE(SUM(t.estimated_cost_usd), 0) as cost
            FROM sessions s
            LEFT JOIN token_totals t ON s.session_id = t.session_id
            WHERE s.started_at >= ? AND s.started_at < ?
        """, (day_start_ms, day_end_ms)).fetchone()

        if day_row["sessions"] > 0:
            days.append({
                "date": f"{now.tm_year}-{now.tm_mon:02d}-{day:02d}",
                "sessions": day_row["sessions"],
                "input_tokens": day_row["input_tokens"],
                "output_tokens": day_row["output_tokens"],
                "cost": round(day_row["cost"], 2),
            })

    conn.close()

    return {
        "month": f"{now.tm_year}-{now.tm_mon:02d}",
        "session_count": row["session_count"],
        "input_tokens": row["input_tokens"],
        "output_tokens": row["output_tokens"],
        "cache_read": row["cache_read"],
        "cache_create": row["cache_create"],
        "total_cost": round(row["total_cost"], 2),
        "days": days,
    }


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
