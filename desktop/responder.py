"""
Suggestions + outcome learning.

Latency strategy:
  1. Ask Ollama for ONE suggestion first → appears in ~3-4s
  2. Stream remaining suggestions as they arrive
  3. Use a tighter prompt (1 suggestion at a time) for faster first response
  4. on_partial callback lets UI show each suggestion as soon as it's ready
"""
from __future__ import annotations

import json
import os
import re
import uuid
from typing import Callable

import httpx

API_BASE    = "http://localhost:8000"
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
        self.user_id   = _load_or_create_user_id()
        self.context   = context
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
            self.session_id = str(uuid.uuid4())
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

    def get_suggestions(
        self,
        prompt: str,
        n: int = 3,
        on_partial: Callable[[list], None] | None = None,
    ) -> list[dict]:
        """
        Returns all suggestions when done.
        If on_partial is provided, calls it after EACH suggestion is ready
        so the UI can show results progressively (first one in ~3-4s).
        """
        try:
            r = httpx.post(f"{API_BASE}/suggest/", json={
                "user_id":    self.user_id,
                "session_id": self.session_id,
                "context":    self.context,
                "prompt":     prompt,
                "n":          n,
            }, timeout=45)
            return r.json().get("suggestions", [])
        except Exception:
            return _direct_ollama_progressive(
                prompt, self.context, n, on_partial)

    def mark_used(self, suggestion_id: str):
        try:
            httpx.post(f"{API_BASE}/suggest/feedback", json={
                "suggestion_id": suggestion_id,
                "accepted": True,
            }, timeout=5)
        except Exception:
            pass


# ── Progressive Ollama (one suggestion at a time for low latency) ─────────────

_SINGLE_PROMPT = """You are helping someone respond in a {context}.
They were asked: "{prompt}"

Give ONE short response suggestion (2-3 sentences) they can say right now.
Reply ONLY with this JSON object (no array, no extra text):
{{"text": "...", "type": "behavioral", "angle": "brief label"}}"""

def _direct_ollama_progressive(
    prompt: str,
    context: str,
    n: int,
    on_partial: Callable[[list], None] | None,
) -> list[dict]:
    """
    Generates suggestions one at a time.
    Each suggestion is shown to the user immediately as it arrives
    rather than waiting for all 3 to finish (~3s vs ~12s total wait).
    """
    results: list[dict] = []

    for i in range(n):
        try:
            r = httpx.post(f"{OLLAMA_BASE}/chat/completions", json={
                "model": OLLAMA_MODEL,
                "messages": [{"role": "user", "content": _SINGLE_PROMPT.format(
                    context=context, prompt=prompt
                )}],
                "temperature": 0.7,
                "max_tokens": 200,    # single suggestion — much shorter = much faster
            }, timeout=20)

            raw = r.json()["choices"][0]["message"]["content"] or ""
            raw = re.sub(r"```(?:json)?", "", raw).strip()

            # parse single object or first item in array
            item = None
            try:
                parsed = json.loads(raw)
                item = parsed if isinstance(parsed, dict) else (parsed[0] if parsed else None)
            except json.JSONDecodeError:
                m = re.search(r"\{.*?\}", raw, re.DOTALL)
                if m:
                    try:
                        item = json.loads(m.group())
                    except Exception:
                        pass

            if item:
                item.setdefault("predicted_success", 0.5)
                item.setdefault("id", str(uuid.uuid4()))
                results.append(item)

                # ← show immediately, don't wait for all 3
                if on_partial:
                    on_partial(list(results))

        except Exception as e:
            err = {"text": f"Could not generate suggestion: {e}",
                   "type": "other", "angle": "error",
                   "predicted_success": 0.0, "id": str(uuid.uuid4())}
            results.append(err)
            if on_partial:
                on_partial(list(results))

    return results


# ── User ID ───────────────────────────────────────────────────────────────────

_ID_FILE = os.path.expanduser("~/.ase_user_id")

def _load_or_create_user_id() -> str:
    if os.path.exists(_ID_FILE):
        return open(_ID_FILE).read().strip()
    uid = str(uuid.uuid4())
    open(_ID_FILE, "w").write(uid)
    return uid
