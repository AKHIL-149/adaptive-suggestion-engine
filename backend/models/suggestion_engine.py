"""
Suggestion engine — runs on Ollama (local, free) by default.
Falls back to Groq (free cloud) or OpenAI based on LLM_PROVIDER env var.
"""
from __future__ import annotations

import json
import re
import time
from typing import Literal

from openai import AsyncOpenAI

from backend.config import (
    LLM_PROVIDER,
    OLLAMA_BASE_URL, OLLAMA_MODEL,
    GROQ_API_KEY, GROQ_MODEL,
    OPENAI_API_KEY, OPENAI_MODEL,
)
from backend.database import get_db

SuggestionType = Literal["technical", "behavioral", "situational", "creative", "other"]


def _make_client() -> tuple[AsyncOpenAI, str]:
    """Returns (client, model_name) based on configured provider."""
    if LLM_PROVIDER == "groq":
        return AsyncOpenAI(base_url="https://api.groq.com/openai/v1", api_key=GROQ_API_KEY), GROQ_MODEL
    if LLM_PROVIDER == "openai":
        return AsyncOpenAI(api_key=OPENAI_API_KEY), OPENAI_MODEL
    # Default: Ollama (local, free)
    return AsyncOpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama"), OLLAMA_MODEL


CLASSIFY_SYSTEM = """Classify the question into one word:
technical, behavioral, situational, creative, or other.
Reply with only that single word."""

SUGGEST_SYSTEM = """You are a real-time assistant helping someone in a {context}.

They were asked: "{prompt}"

{pattern_note}

Generate exactly {n} short response suggestions they can say right now (2-4 sentences each).
Return ONLY a JSON array, no other text:
[
  {{"text": "...", "type": "{stype}", "angle": "short label"}}
]"""


async def _call_llm(system: str, user: str, temperature: float = 0.0, max_tokens: int = 20) -> str:
    client, model = _make_client()
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return (resp.choices[0].message.content or "").strip()


async def classify_prompt(prompt: str) -> SuggestionType:
    raw = await _call_llm(CLASSIFY_SYSTEM, prompt, temperature=0.0, max_tokens=10)
    raw = raw.lower().split()[0] if raw else "other"
    valid: list[SuggestionType] = ["technical", "behavioral", "situational", "creative", "other"]
    return raw if raw in valid else "other"  # type: ignore[return-value]


def _extract_json_array(text: str) -> list[dict]:
    """Robustly extract a JSON array from LLM output — handles markdown fences etc."""
    # strip markdown fences
    text = re.sub(r"```(?:json)?", "", text).strip()
    # try direct parse
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
        # {suggestions: [...]} wrapper
        for v in parsed.values():
            if isinstance(v, list):
                return v
    except json.JSONDecodeError:
        pass
    # fallback: find first [...] block
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return []


async def generate_suggestions(
    user_id: str,
    session_id: str,
    context: str,
    prompt: str,
    n: int = 3,
) -> list[dict]:
    t0 = time.monotonic()
    db = get_db()

    stype = await classify_prompt(prompt)
    patterns = {r["suggestion_type"]: r["success_rate"] for r in db.get_patterns(user_id, context)}

    if patterns:
        best = max(patterns, key=patterns.get)  # type: ignore[arg-type]
        pattern_note = f"Note: for this user, {best} responses have the highest success rate ({patterns[best]:.0%}). Favour that style."
    else:
        pattern_note = ""

    system = SUGGEST_SYSTEM.format(
        context=context,
        prompt=prompt,
        pattern_note=pattern_note,
        n=n,
        stype=stype,
    )

    raw = await _call_llm(system, "Generate the suggestions now.", temperature=0.7, max_tokens=800)
    items = _extract_json_array(raw)

    # Fallback: if model returned nothing parseable, build a generic item
    if not items:
        items = [{"text": raw[:400] if raw else "No suggestion generated.", "type": stype, "angle": "general"}]

    elapsed_ms = int((time.monotonic() - t0) * 1000)

    result = []
    for item in items[:n]:
        item_type = item.get("type", stype)
        item["predicted_success"] = round(patterns.get(item_type, 0.5), 2)
        item["response_time_ms"] = elapsed_ms
        # persist
        item["id"] = db.insert_suggestion(
            session_id=session_id,
            prompt=prompt,
            text=item.get("text", ""),
            stype=item_type,
            ms=elapsed_ms,
        )
        result.append(item)

    result.sort(key=lambda x: x["predicted_success"], reverse=True)
    return result
