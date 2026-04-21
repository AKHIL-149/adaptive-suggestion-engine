from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.database import get_db
from backend.models.suggestion_engine import generate_suggestions

router = APIRouter(prefix="/suggest", tags=["suggestions"])


class SuggestRequest(BaseModel):
    user_id: str
    session_id: str
    context: str
    prompt: str
    n: int = 3


class FeedbackRequest(BaseModel):
    suggestion_id: str
    accepted: bool


@router.post("/")
async def suggest(body: SuggestRequest):
    if not (1 <= body.n <= 5):
        raise HTTPException(400, "n must be between 1 and 5")
    suggestions = await generate_suggestions(
        user_id=body.user_id,
        session_id=body.session_id,
        context=body.context,
        prompt=body.prompt,
        n=body.n,
    )
    return {"suggestions": suggestions}


@router.post("/feedback")
async def feedback(body: FeedbackRequest):
    get_db().mark_accepted(body.suggestion_id, body.accepted)
    return {"ok": True}
