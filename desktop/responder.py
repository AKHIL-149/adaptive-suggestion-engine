"""
Calls the FastAPI backend for suggestions + outcome learning.
Falls back to direct Ollama if the backend is offline.
"""
from __future__ import annotations

import json
import re
import uuid
import httpx

API_BASE = "http://localhost:8000"
OLLAMA_BASE = "http://localhost:11434/v1"
OLLAMA_MODEL = "llama3.2"

# ── Question detection ────────────────────────────────────────────────────────

_QUESTION_STARTERS = (
    "what", "how", "why", "when", "where", "who", "which", "can you",
    "could you", "tell me", "describe", "explain", "walk me through",
    "have you", "do you", "did you", "would you", "are you",
    "talk about", "give me", "share",
)

def is_question(text: str) -> bool:
    t = text.lower().strip()
    if "?" in t:
        return True
    return any(t.startswith(q) for q in _QUESTION_STARTERS)


# ── Session management ────────────────────────────────────────────────────────

class Session:
    def __init__(self, context: str):
        self.user_id = _load_or_create_user_id()
        self.context = context
        self.session_id: str | None = None

    def start(self) -> bool:
        try:
            r = httpx.post(f"{API_BASE}/sessions/", json={
                "user_id": self.user_id,
                "context": self.context,
            }, timeout=5)
            self.session_id = r.json()["session_id"]
            return True
        except Exception:
            self.session_id = str(uuid.uuid4())   # offline fallback
            return False

    def end(self, score: int, notes: str = "") -> dict:
        if not self.session_id:
            return {}
        try:
            r = httpx.post(f"{API_BASE}/sessions/{self.session_id}/end", json={
                "outcome_score": score,
                "outcome_notes": notes,
            }, timeout=10)
            return r.json()
        except Exception:
            return {}

    def get_suggestions(self, prompt: str, n: int = 3) -> list[dict]:
        if not self.session_id:
            return _direct_ollama(prompt, self.context, n)
        try:
            r = httpx.post(f"{API_BASE}/suggest/", json={
                "user_id": self.user_id,
                "session_id": self.session_id,
                "context": self.context,
                "prompt": prompt,
                "n": n,
            }, timeout=30)
            return r.json().get("suggestions", [])
        except Exception:
            return _direct_ollama(prompt, self.context, n)

    def mark_used(self, suggestion_id: str):
        try:
            httpx.post(f"{API_BASE}/suggest/feedback", json={
                "suggestion_id": suggestion_id,
                "accepted": True,
            }, timeout=5)
        except Exception:
            pass


# ── Direct Ollama fallback ────────────────────────────────────────────────────

_PROMPT_TMPL = """You are helping someone in a {context}.
They were asked: "{prompt}"
Give {n} short response suggestions (2-3 sentences each) they can say right now.
Return ONLY a JSON array:
[{{"text": "...", "type": "behavioral", "angle": "label"}}]"""

def _direct_ollama(prompt: str, context: str, n: int) -> list[dict]:
    try:
        r = httpx.post(f"{OLLAMA_BASE}/chat/completions", json={
            "model": OLLAMA_MODEL,
            "messages": [{"role": "user", "content": _PROMPT_TMPL.format(
                context=context, prompt=prompt, n=n
            )}],
            "temperature": 0.7,
            "max_tokens": 600,
        }, timeout=30)
        raw = r.json()["choices"][0]["message"]["content"]
        raw = re.sub(r"```(?:json)?", "", raw).strip()
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        items = json.loads(m.group()) if m else []
        for i, item in enumerate(items):
            item.setdefault("predicted_success", 0.5)
            item.setdefault("id", str(uuid.uuid4()))
        return items
    except Exception as e:
        return [{"text": f"Error: {e}", "type": "other", "angle": "error",
                 "predicted_success": 0.0, "id": str(uuid.uuid4())}]


# ── User ID persistence ───────────────────────────────────────────────────────

import os

_ID_FILE = os.path.expanduser("~/.ase_user_id")

def _load_or_create_user_id() -> str:
    if os.path.exists(_ID_FILE):
        return open(_ID_FILE).read().strip()
    uid = str(uuid.uuid4())
    open(_ID_FILE, "w").write(uid)
    return uid
