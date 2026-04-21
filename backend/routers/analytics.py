from fastapi import APIRouter
from backend.database import get_db

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/{user_id}/improvement")
async def improvement_curve(user_id: str):
    sessions = get_db().get_user_sessions(user_id)
    curve = [{"session_id": s["id"], "context": s["context"], "date": s["started_at"], "score": s["outcome_score"]}
             for s in sessions if s["outcome_score"] is not None]
    if not curve:
        return {"curve": [], "message": "No completed sessions yet"}
    avg = sum(c["score"] for c in curve) / len(curve)
    half = len(curve) // 2
    trend = "improving" if half and (
        sum(c["score"] for c in curve[half:]) / len(curve[half:]) >
        sum(c["score"] for c in curve[:half]) / len(curve[:half])
    ) else "stable"
    return {"curve": curve, "average_score": round(avg, 2), "trend": trend}


@router.get("/{user_id}/patterns")
async def top_patterns(user_id: str):
    return {"patterns": get_db().get_all_patterns(user_id)}


@router.get("/{user_id}/summary")
async def summary(user_id: str):
    db = get_db()
    sessions = db.get_user_sessions(user_id)
    completed = [s for s in sessions if s["outcome_score"] is not None]
    avg_score = round(sum(s["outcome_score"] for s in completed) / len(completed), 2) if completed else None
    patterns = db.get_all_patterns(user_id)
    best_type = patterns[0]["suggestion_type"] if patterns else None
    return {
        "total_sessions": len(sessions),
        "completed_sessions": len(completed),
        "average_outcome_score": avg_score,
        "best_performing_style": best_type,
        "patterns": patterns,
    }
