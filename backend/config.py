import os
from dotenv import load_dotenv

load_dotenv()

# LLM — defaults to local Ollama (free, no API key needed)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")   # "ollama" | "groq" | "openai"
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")          # free tier at console.groq.com
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama3-70b-8192")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

# Database — defaults to local SQLite (no Supabase needed)
DB_TYPE = os.getenv("DB_TYPE", "sqlite")               # "sqlite" | "supabase"
SQLITE_PATH = os.getenv("SQLITE_PATH", "data.db")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

PORT = int(os.getenv("PORT", 8000))
