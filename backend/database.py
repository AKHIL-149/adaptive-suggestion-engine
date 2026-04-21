from supabase import create_client, Client
from backend.config import SUPABASE_URL, SUPABASE_SERVICE_KEY

_client: Client | None = None


def get_db() -> Client:
    global _client
    if _client is None:
        if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
        _client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    return _client


SCHEMA = """
-- Run this once in Supabase SQL Editor

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sessions (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID REFERENCES users(id) ON DELETE CASCADE,
    context        TEXT NOT NULL,
    started_at     TIMESTAMPTZ DEFAULT NOW(),
    ended_at       TIMESTAMPTZ,
    outcome_score  INTEGER CHECK (outcome_score BETWEEN 1 AND 5),
    outcome_notes  TEXT,
    metadata       JSONB DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS suggestions (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id       UUID REFERENCES sessions(id) ON DELETE CASCADE,
    prompt           TEXT NOT NULL,
    suggestion_text  TEXT NOT NULL,
    suggestion_type  TEXT,
    accepted         BOOLEAN DEFAULT NULL,
    response_time_ms INTEGER,
    ts               TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS outcome_patterns (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
    context         TEXT,
    suggestion_type TEXT,
    success_rate    FLOAT DEFAULT 0.5,
    sample_count    INTEGER DEFAULT 0,
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, context, suggestion_type)
);
"""
