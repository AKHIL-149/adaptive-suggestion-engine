from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.database import get_db

router = APIRouter(prefix="/sessions", tags=["sessions"])


class StartSession(BaseModel):
    user_id: str
    context: str  # e.g. "software engineering interview", "sales meeting"


class EndSession(BaseModel):
    outcome_score: int   # 1–5
    outcome_notes: str = ""


@router.post("/")
async def start_session(body: StartSession):
    db = get_db()

    # Ensure user exists
    existing = db.table("users").select("id").eq("id", body.user_id).execute().data
    if not existing:
        db.table("users").insert({"id": body.user_id}).execute()

    row = db.table("sessions").insert({
        "user_id": body.user_id,
        "context": body.context,
    }).execute().data[0]

    return {"session_id": row["id"], "context": row["context"], "started_at": row["started_at"]}


@router.get("/{session_id}")
async def get_session(session_id: str):
    db = get_db()
    rows = db.table("sessions").select("*").eq("id", session_id).execute().data
    if not rows:
        raise HTTPException(404, "Session not found")
    return rows[0]


@router.post("/{session_id}/end")
async def end_session(session_id: str, body: EndSession):
    if not (1 <= body.outcome_score <= 5):
        raise HTTPException(400, "outcome_score must be 1–5")

    db = get_db()
    rows = db.table("sessions").select("user_id, context").eq("id", session_id).execute().data
    if not rows:
        raise HTTPException(404, "Session not found")

    session = rows[0]

    db.table("sessions").update({
        "ended_at": "NOW()",
        "outcome_score": body.outcome_score,
        "outcome_notes": body.outcome_notes,
    }).eq("id", session_id).execute()

    # Trigger learning loop
    from backend.models.outcome_analyzer import process_outcome
    learning = await process_outcome(
        user_id=session["user_id"],
        session_id=session_id,
        context=session["context"],
        outcome_score=body.outcome_score,
    )

    return {"ok": True, "learning": learning}


@router.get("/{session_id}/suggestions")
async def get_session_suggestions(session_id: str):
    db = get_db()
    rows = db.table("suggestions").select("*").eq("session_id", session_id).order("ts").execute().data
    return rows
