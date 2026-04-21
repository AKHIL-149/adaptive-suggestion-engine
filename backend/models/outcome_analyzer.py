from __future__ import annotations
from backend.database import get_db

EWMA_ALPHA = 0.3


def _normalize(score: int) -> float:
    return (score - 1) / 4.0


def _ewma(current: float, new_value: float) -> float:
    return EWMA_ALPHA * new_value + (1 - EWMA_ALPHA) * current


async def process_outcome(user_id: str, session_id: str, context: str, outcome_score: int) -> dict:
    db = get_db()
    success = _normalize(outcome_score)

    suggestions = db.get_session_suggestions(session_id)
    if not suggestions:
        return {"learned": [], "outcome_success": round(success, 2)}

    # Weight accepted suggestions more
    type_weights: dict[str, float] = {}
    for s in suggestions:
        stype = s["suggestion_type"] or "other"
        weight = 1.5 if s.get("accepted") == 1 else 0.5
        type_weights[stype] = type_weights.get(stype, 0) + weight

    total = sum(type_weights.values()) or 1
    learned = []

    for stype, weight in type_weights.items():
        weighted_success = success * (weight / total)
        existing = db.get_patterns(user_id, context)
        existing_map = {p["suggestion_type"]: p for p in existing}

        if stype in existing_map:
            old = existing_map[stype]
            new_rate = _ewma(old["success_rate"], weighted_success)
            db.upsert_pattern(user_id, context, stype, new_rate, old["sample_count"] + 1)
            learned.append({"type": stype, "old_rate": round(old["success_rate"], 2), "new_rate": round(new_rate, 2)})
        else:
            db.upsert_pattern(user_id, context, stype, weighted_success, 1)
            learned.append({"type": stype, "old_rate": None, "new_rate": round(weighted_success, 2)})

    return {"learned": learned, "outcome_success": round(success, 2)}
