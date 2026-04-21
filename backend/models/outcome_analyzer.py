"""
Outcome analyzer — the learning loop.

After a session ends with an outcome score, this module:
1. Finds all accepted suggestions in that session
2. Determines which suggestion types were used
3. Updates the user's outcome_patterns table with weighted rolling average
4. Returns a summary of what was learned
"""
from __future__ import annotations

from backend.database import get_db

# Exponential weighted moving average factor (recent outcomes weighted more)
EWMA_ALPHA = 0.3


def _normalize_score(score: int) -> float:
    """Convert 1–5 outcome score to 0–1 success probability."""
    return (score - 1) / 4.0


def _ewma(current: float, new_value: float, alpha: float = EWMA_ALPHA) -> float:
    return alpha * new_value + (1 - alpha) * current


async def process_outcome(
    user_id: str,
    session_id: str,
    context: str,
    outcome_score: int,
) -> dict:
    """
    Called after session.outcome_score is set.
    Updates outcome_patterns and returns what was learned.
    """
    db = get_db()
    success = _normalize_score(outcome_score)

    # Get accepted suggestions for this session
    rows = (
        db.table("suggestions")
        .select("suggestion_type, accepted")
        .eq("session_id", session_id)
        .execute()
        .data
    )

    if not rows:
        return {"learned": [], "outcome_success": success}

    # Group by type — weigh accepted suggestions more
    type_weights: dict[str, float] = {}
    for r in rows:
        stype = r["suggestion_type"] or "other"
        weight = 1.5 if r["accepted"] else 0.5  # accepted = stronger signal
        type_weights[stype] = type_weights.get(stype, 0) + weight

    total_weight = sum(type_weights.values()) or 1
    learned = []

    for stype, weight in type_weights.items():
        # Weighted success signal for this type
        weighted_success = success * (weight / total_weight)

        # Fetch existing pattern
        existing = (
            db.table("outcome_patterns")
            .select("success_rate, sample_count")
            .eq("user_id", user_id)
            .eq("context", context)
            .eq("suggestion_type", stype)
            .execute()
            .data
        )

        if existing:
            old_rate = existing[0]["success_rate"]
            old_count = existing[0]["sample_count"]
            new_rate = _ewma(old_rate, weighted_success)
            db.table("outcome_patterns").update({
                "success_rate": round(new_rate, 4),
                "sample_count": old_count + 1,
                "updated_at": "NOW()",
            }).eq("user_id", user_id).eq("context", context).eq("suggestion_type", stype).execute()
            learned.append({"type": stype, "old_rate": round(old_rate, 2), "new_rate": round(new_rate, 2)})
        else:
            db.table("outcome_patterns").insert({
                "user_id": user_id,
                "context": context,
                "suggestion_type": stype,
                "success_rate": round(weighted_success, 4),
                "sample_count": 1,
            }).execute()
            learned.append({"type": stype, "old_rate": None, "new_rate": round(weighted_success, 2)})

    return {"learned": learned, "outcome_success": round(success, 2)}


async def get_improvement_curve(user_id: str) -> list[dict]:
    """
    Returns per-session outcome scores to show improvement over time.
    """
    db = get_db()
    rows = (
        db.table("sessions")
        .select("id, context, started_at, outcome_score")
        .eq("user_id", user_id)
        .not_.is_("outcome_score", "null")
        .order("started_at", desc=False)
        .execute()
        .data
    )
    return [
        {
            "session_id": r["id"],
            "context": r["context"],
            "date": r["started_at"],
            "score": r["outcome_score"],
        }
        for r in rows
    ]


async def get_top_patterns(user_id: str) -> list[dict]:
    """Returns what suggestion types work best for this user, ranked."""
    db = get_db()
    rows = (
        db.table("outcome_patterns")
        .select("context, suggestion_type, success_rate, sample_count")
        .eq("user_id", user_id)
        .order("success_rate", desc=True)
        .execute()
        .data
    )
    return rows
