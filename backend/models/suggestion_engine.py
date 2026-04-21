"""
Core suggestion engine.

1. Classifies the incoming prompt (technical / behavioral / situational / other)
2. Looks up the user's outcome patterns to weight which style works best
3. Calls OpenAI to generate ranked suggestions
4. Returns suggestions with predicted success scores
"""
from __future__ import annotations

import time
from typing import Literal

from openai import AsyncOpenAI

from backend.config import OPENAI_API_KEY
from backend.database import get_db

SuggestionType = Literal["technical", "behavioral", "situational", "creative", "other"]

_openai = AsyncOpenAI(api_key=OPENAI_API_KEY)

CLASSIFY_PROMPT = """You are a classifier. Given a question or prompt from a meeting or interview,
classify it into exactly one category:
- technical: coding, architecture, system design, data, algorithms
- behavioral: past experience, team conflicts, leadership, stories (STAR format)
- situational: hypothetical scenarios, "what would you do if…"
- creative: brainstorming, product ideas, open-ended design
- other: anything else

Reply with only the category word, nothing else."""

SUGGEST_PROMPT = """You are an expert real-time assistant helping someone in a {context}.

The person was asked: "{prompt}"

Based on data showing that {style_note}, generate {n} distinct, concise response suggestions.
Each suggestion should be 2-4 sentences max — something they can actually say right now.

Format your response as a JSON array of objects:
[
  {{"text": "...", "type": "{suggestion_type}", "angle": "brief descriptor of this angle"}}
]

Only return valid JSON, nothing else."""


async def classify_prompt(prompt: str) -> SuggestionType:
    resp = await _openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": CLASSIFY_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
        max_tokens=10,
    )
    raw = resp.choices[0].message.content.strip().lower()
    valid: list[SuggestionType] = ["technical", "behavioral", "situational", "creative", "other"]
    return raw if raw in valid else "other"  # type: ignore[return-value]


async def get_user_patterns(user_id: str, context: str) -> dict[str, float]:
    """Returns {suggestion_type: success_rate} for this user + context."""
    db = get_db()
    rows = (
        db.table("outcome_patterns")
        .select("suggestion_type, success_rate, sample_count")
        .eq("user_id", user_id)
        .eq("context", context)
        .execute()
        .data
    )
    return {r["suggestion_type"]: r["success_rate"] for r in rows} if rows else {}


def _style_note(patterns: dict[str, float], suggestion_type: SuggestionType) -> str:
    if not patterns:
        return "no prior data is available yet, use your best judgment"
    if suggestion_type in patterns:
        rate = patterns[suggestion_type]
        return f"{suggestion_type} responses have a {rate:.0%} success rate for this user"
    # fall back to overall best
    best = max(patterns, key=patterns.get)  # type: ignore[arg-type]
    return f"{best} framing has worked best for this user ({patterns[best]:.0%} success rate)"


async def generate_suggestions(
    user_id: str,
    session_id: str,
    context: str,
    prompt: str,
    n: int = 3,
) -> list[dict]:
    t0 = time.monotonic()

    suggestion_type = await classify_prompt(prompt)
    patterns = await get_user_patterns(user_id, context)
    style_note = _style_note(patterns, suggestion_type)

    system_msg = SUGGEST_PROMPT.format(
        context=context,
        prompt=prompt,
        style_note=style_note,
        n=n,
        suggestion_type=suggestion_type,
    )

    resp = await _openai.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": system_msg}],
        temperature=0.7,
        max_tokens=600,
        response_format={"type": "json_object"},
    )

    import json
    raw = resp.choices[0].message.content or "[]"
    # model returns {"suggestions": [...]} or bare array
    parsed = json.loads(raw)
    items: list[dict] = parsed if isinstance(parsed, list) else parsed.get("suggestions", list(parsed.values())[0] if parsed else [])

    elapsed_ms = int((time.monotonic() - t0) * 1000)

    # Attach predicted score based on patterns
    for item in items:
        stype = item.get("type", suggestion_type)
        item["predicted_success"] = round(patterns.get(stype, 0.5), 2)
        item["response_time_ms"] = elapsed_ms

    # Sort: highest predicted success first
    items.sort(key=lambda x: x["predicted_success"], reverse=True)

    # Persist to DB
    db = get_db()
    for item in items:
        db.table("suggestions").insert({
            "session_id": session_id,
            "prompt": prompt,
            "suggestion_text": item["text"],
            "suggestion_type": item.get("type", suggestion_type),
            "response_time_ms": elapsed_ms,
        }).execute()

    return items
