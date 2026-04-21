"""
Database abstraction — supports SQLite (local, zero config) and Supabase (cloud).
Set DB_TYPE=sqlite (default) or DB_TYPE=supabase in your .env.
"""
from __future__ import annotations

import sqlite3
import json
import uuid
from datetime import datetime, timezone
from backend.config import DB_TYPE, SQLITE_PATH, SUPABASE_URL, SUPABASE_SERVICE_KEY

# ── SQLite backend ────────────────────────────────────────────────────────────

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    context TEXT NOT NULL,
    started_at TEXT DEFAULT (datetime('now')),
    ended_at TEXT,
    outcome_score INTEGER,
    outcome_notes TEXT,
    metadata TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS suggestions (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    prompt TEXT NOT NULL,
    suggestion_text TEXT NOT NULL,
    suggestion_type TEXT,
    accepted INTEGER DEFAULT NULL,
    response_time_ms INTEGER,
    ts TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS outcome_patterns (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    context TEXT,
    suggestion_type TEXT,
    success_rate REAL DEFAULT 0.5,
    sample_count INTEGER DEFAULT 0,
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE (user_id, context, suggestion_type)
);
"""


def _get_sqlite() -> sqlite3.Connection:
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_sqlite():
    conn = _get_sqlite()
    conn.executescript(SQLITE_SCHEMA)
    conn.commit()
    conn.close()


# ── Unified DB interface ──────────────────────────────────────────────────────

class DB:
    """Thin wrapper that normalises SQLite and Supabase into one API."""

    def __init__(self):
        if DB_TYPE == "supabase":
            from supabase import create_client
            self._supa = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
        else:
            init_sqlite()
            self._supa = None

    # ── users ──────────────────────────────────────────────────────────────

    def upsert_user(self, user_id: str):
        if self._supa:
            existing = self._supa.table("users").select("id").eq("id", user_id).execute().data
            if not existing:
                self._supa.table("users").insert({"id": user_id}).execute()
        else:
            conn = _get_sqlite()
            conn.execute("INSERT OR IGNORE INTO users (id) VALUES (?)", (user_id,))
            conn.commit(); conn.close()

    # ── sessions ───────────────────────────────────────────────────────────

    def create_session(self, user_id: str, context: str) -> dict:
        sid = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        if self._supa:
            return self._supa.table("sessions").insert({"user_id": user_id, "context": context}).execute().data[0]
        conn = _get_sqlite()
        conn.execute(
            "INSERT INTO sessions (id, user_id, context, started_at) VALUES (?,?,?,?)",
            (sid, user_id, context, now),
        )
        conn.commit(); conn.close()
        return {"id": sid, "user_id": user_id, "context": context, "started_at": now}

    def get_session(self, session_id: str) -> dict | None:
        if self._supa:
            rows = self._supa.table("sessions").select("*").eq("id", session_id).execute().data
            return rows[0] if rows else None
        conn = _get_sqlite()
        row = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def end_session(self, session_id: str, outcome_score: int, outcome_notes: str):
        now = datetime.now(timezone.utc).isoformat()
        if self._supa:
            self._supa.table("sessions").update({"ended_at": now, "outcome_score": outcome_score, "outcome_notes": outcome_notes}).eq("id", session_id).execute()
        else:
            conn = _get_sqlite()
            conn.execute("UPDATE sessions SET ended_at=?, outcome_score=?, outcome_notes=? WHERE id=?", (now, outcome_score, outcome_notes, session_id))
            conn.commit(); conn.close()

    def get_user_sessions(self, user_id: str) -> list[dict]:
        if self._supa:
            return self._supa.table("sessions").select("id,context,outcome_score,started_at").eq("user_id", user_id).execute().data
        conn = _get_sqlite()
        rows = conn.execute("SELECT id,context,outcome_score,started_at FROM sessions WHERE user_id=? ORDER BY started_at", (user_id,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # ── suggestions ────────────────────────────────────────────────────────

    def insert_suggestion(self, session_id: str, prompt: str, text: str, stype: str, ms: int) -> str:
        sid = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        if self._supa:
            row = self._supa.table("suggestions").insert({"session_id": session_id, "prompt": prompt, "suggestion_text": text, "suggestion_type": stype, "response_time_ms": ms}).execute().data[0]
            return row["id"]
        conn = _get_sqlite()
        conn.execute("INSERT INTO suggestions (id,session_id,prompt,suggestion_text,suggestion_type,response_time_ms,ts) VALUES (?,?,?,?,?,?,?)", (sid, session_id, prompt, text, stype, ms, now))
        conn.commit(); conn.close()
        return sid

    def mark_accepted(self, suggestion_id: str, accepted: bool):
        if self._supa:
            self._supa.table("suggestions").update({"accepted": accepted}).eq("id", suggestion_id).execute()
        else:
            conn = _get_sqlite()
            conn.execute("UPDATE suggestions SET accepted=? WHERE id=?", (1 if accepted else 0, suggestion_id))
            conn.commit(); conn.close()

    def get_session_suggestions(self, session_id: str) -> list[dict]:
        if self._supa:
            return self._supa.table("suggestions").select("*").eq("session_id", session_id).order("ts").execute().data
        conn = _get_sqlite()
        rows = conn.execute("SELECT * FROM suggestions WHERE session_id=? ORDER BY ts", (session_id,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # ── outcome patterns ────────────────────────────────────────────────────

    def get_patterns(self, user_id: str, context: str) -> list[dict]:
        if self._supa:
            return self._supa.table("outcome_patterns").select("suggestion_type,success_rate,sample_count").eq("user_id", user_id).eq("context", context).execute().data
        conn = _get_sqlite()
        rows = conn.execute("SELECT suggestion_type,success_rate,sample_count FROM outcome_patterns WHERE user_id=? AND context=?", (user_id, context)).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def upsert_pattern(self, user_id: str, context: str, stype: str, new_rate: float, new_count: int):
        now = datetime.now(timezone.utc).isoformat()
        if self._supa:
            existing = self._supa.table("outcome_patterns").select("id").eq("user_id", user_id).eq("context", context).eq("suggestion_type", stype).execute().data
            if existing:
                self._supa.table("outcome_patterns").update({"success_rate": new_rate, "sample_count": new_count, "updated_at": now}).eq("user_id", user_id).eq("context", context).eq("suggestion_type", stype).execute()
            else:
                self._supa.table("outcome_patterns").insert({"user_id": user_id, "context": context, "suggestion_type": stype, "success_rate": new_rate, "sample_count": new_count}).execute()
        else:
            conn = _get_sqlite()
            conn.execute("""
                INSERT INTO outcome_patterns (id,user_id,context,suggestion_type,success_rate,sample_count,updated_at)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(user_id,context,suggestion_type) DO UPDATE SET success_rate=excluded.success_rate, sample_count=excluded.sample_count, updated_at=excluded.updated_at
            """, (str(uuid.uuid4()), user_id, context, stype, round(new_rate, 4), new_count, now))
            conn.commit(); conn.close()

    def get_all_patterns(self, user_id: str) -> list[dict]:
        if self._supa:
            return self._supa.table("outcome_patterns").select("context,suggestion_type,success_rate,sample_count").eq("user_id", user_id).order("success_rate", desc=True).execute().data
        conn = _get_sqlite()
        rows = conn.execute("SELECT context,suggestion_type,success_rate,sample_count FROM outcome_patterns WHERE user_id=? ORDER BY success_rate DESC", (user_id,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]


_db: DB | None = None

def get_db() -> DB:
    global _db
    if _db is None:
        _db = DB()
    return _db
