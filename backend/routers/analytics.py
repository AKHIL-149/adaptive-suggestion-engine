from fastapi import APIRouter
from backend.models.outcome_analyzer import get_improvement_curve, get_top_patterns
from backend.database import get_db

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/{user_id}/improvement")
async def improvement_curve(user_id: str):
    """Session-by-session outcome scores — shows the learning curve."""
    curve = await get_improvement_curve(user_id)
    if not curve:
        return {"curve": [], "message": "No completed sessions yet"}

    avg = sum(c["score"] for c in curve) / len(curve)
    first_half = curve[: len(curve) // 2]
    second_half = curve[len(curve) // 2 :]
    trend = "improving" if (
        second_half and first_half and
        (sum(s["score"] for s in second_half) / len(second_half)) >
        (sum(s["score"] for s in first_half) / len(first_half))
    ) else "stable"

    return {"curve": curve, "average_score": round(avg, 2), "trend": trend}


@router.get("/{user_id}/patterns")
async def top_patterns(user_id: str):
    """What suggestion types work best for this user."""
    patterns = await get_top_patterns(user_id)
    return {"patterns": patterns}


@router.get("/{user_id}/summary")
async def summary(user_id: str):
    """Full user intelligence summary."""
    db = get_db()

    sessions = db.table("sessions").select("id, context, outcome_score, started_at").eq("user_id", user_id).execute().data
    total_sessions = len(sessions)
    completed = [s for s in sessions if s["outcome_score"] is not None]
    avg_score = round(sum(s["outcome_score"] for s in completed) / len(completed), 2) if completed else None

    suggestions = db.table("suggestions").select("suggestion_type, accepted").execute().data
    total_suggestions = len(suggestions)
    accepted_count = sum(1 for s in suggestions if s["accepted"])

    patterns = await get_top_patterns(user_id)
    best_type = patterns[0]["suggestion_type"] if patterns else None

    return {
        "total_sessions": total_sessions,
        "completed_sessions": len(completed),
        "average_outcome_score": avg_score,
        "total_suggestions_served": total_suggestions,
        "acceptance_rate": round(accepted_count / total_suggestions, 2) if total_suggestions else None,
        "best_performing_style": best_type,
        "patterns": patterns,
    }
