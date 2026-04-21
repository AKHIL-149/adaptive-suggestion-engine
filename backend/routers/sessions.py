from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.database import get_db

router = APIRouter(prefix="/sessions", tags=["sessions"])


class StartSession(BaseModel):
    user_id: str
    context: str


class EndSession(BaseModel):
    outcome_score: int
    outcome_notes: str = ""


@router.post("/")
async def start_session(body: StartSession):
    db = get_db()
    db.upsert_user(body.user_id)
    session = db.create_session(body.user_id, body.context)
    return {"session_id": session["id"], "context": session["context"], "started_at": session["started_at"]}


@router.get("/{session_id}")
async def get_session(session_id: str):
    session = get_db().get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return session


@router.post("/{session_id}/end")
async def end_session(session_id: str, body: EndSession):
    if not (1 <= body.outcome_score <= 5):
        raise HTTPException(400, "outcome_score must be 1–5")
    db = get_db()
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    db.end_session(session_id, body.outcome_score, body.outcome_notes)

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
    return get_db().get_session_suggestions(session_id)
