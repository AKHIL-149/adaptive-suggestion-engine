from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn
import os

from backend.routers import sessions, suggestions, analytics

app = FastAPI(
    title="Adaptive Suggestion Engine",
    description="Closed-loop AI that learns which suggestions lead to real outcomes.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sessions.router)
app.include_router(suggestions.router)
app.include_router(analytics.router)

# Serve frontend
frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

    @app.get("/")
    async def serve_frontend():
        return FileResponse(os.path.join(frontend_dir, "index.html"))

    @app.get("/dashboard")
    async def serve_dashboard():
        return FileResponse(os.path.join(frontend_dir, "dashboard.html"))


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    from backend.config import PORT
    uvicorn.run("backend.main:app", host="0.0.0.0", port=PORT, reload=True)
