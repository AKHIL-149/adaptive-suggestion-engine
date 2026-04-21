# Adaptive Suggestion Engine

> Real-time AI suggestions for meetings & interviews — with a closed-loop learning system that improves based on your actual outcomes.

## The Problem This Solves

Every real-time AI assistant (including Cluely) fires suggestions without knowing if they worked. There is no feedback loop. The model never learns.

This project closes that loop:

```
Real-time suggestion → User outcome → Model retraining → Better suggestions
```

## How It Works

1. **Start a session** — set context (interview type, meeting type)
2. **Paste a question** — get ranked AI suggestions in real-time
3. **Mark what you used** — acceptance signal strengthens learning
4. **Rate the outcome** — 1–5 score after the session ends
5. **Model updates** — EWMA-weighted success rates per suggestion type, per user
6. **Next session** — suggestions are ranked by your personal success history

## Architecture

```
backend/
├── main.py                      # FastAPI app
├── config.py                    # Env vars
├── database.py                  # Supabase client + schema
├── models/
│   ├── suggestion_engine.py     # Classify → pattern lookup → OpenAI → rank
│   └── outcome_analyzer.py      # EWMA learning loop
└── routers/
    ├── sessions.py              # Session lifecycle
    ├── suggestions.py           # Real-time suggestion + feedback
    └── analytics.py             # Improvement curve + pattern summary

frontend/
├── index.html                   # Live demo UI
├── dashboard.html               # Learning dashboard
├── app.js                       # Frontend logic
└── style.css                    # Styling
```

## Setup

```bash
# 1. Clone
git clone https://github.com/AKHIL-149/adaptive-suggestion-engine
cd adaptive-suggestion-engine

# 2. Install
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 3. Configure
cp .env.example .env
# Fill in OPENAI_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY

# 4. Create DB tables
# Run the SQL in backend/database.py → SCHEMA in your Supabase SQL Editor

# 5. Run
python -m backend.main
# → http://localhost:8000
```

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/sessions/` | Start a new session |
| POST | `/sessions/{id}/end` | End session + submit outcome score |
| GET | `/sessions/{id}/suggestions` | Get all suggestions for a session |
| POST | `/suggest/` | Get real-time suggestions |
| POST | `/suggest/feedback` | Mark a suggestion accepted/rejected |
| GET | `/analytics/{user_id}/summary` | Full user intelligence summary |
| GET | `/analytics/{user_id}/improvement` | Outcome score curve over time |
| GET | `/analytics/{user_id}/patterns` | What suggestion types work best |

## Built by

Akhil Mettu — [akhilportfolio.com](https://www.akhilportfolio.com) · [GitHub](https://github.com/AKHIL-149)
