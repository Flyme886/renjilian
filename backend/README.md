# 人机恋 Companion API

FastAPI + SQLite backend for persona-based, long-running companion chats. It is
provider-agnostic: set one API key for an OpenAI-compatible endpoint, or run
without a key to use the deterministic local demo provider.

## Run

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

The interactive API is at `http://localhost:8000/docs`.
When the repository also contains `frontend/`, the same server serves the UI
at `http://localhost:8000/` (so no second dev server is required).

```bash
export LLM_API_KEY=your-key
export LLM_BASE_URL=https://api.openai.com/v1  # optional
export LLM_MODEL=gpt-4o-mini                  # optional
```

Without `LLM_API_KEY`, `/api/sessions/{id}/messages` returns a small local
reply so the UI can be tested before connecting a model.

## Core endpoints

- `GET /health` and `GET /api/state`
- `GET /api/personas`, `POST /api/personas`
- `GET/POST /api/sessions`, `GET/DELETE /api/sessions/{id}`
- `GET /api/sessions/{id}/messages`, `POST /api/sessions/{id}/messages`
- `POST /api/sessions/{id}/messages/stream` (SSE)
- `GET/POST /api/sessions/{id}/memories`, `DELETE .../memories/{memory_id}`

Messages explicitly prefixed with `记住` / `请记住` / `remember that` create a
memory. This conservative rule avoids silently storing everything a user says.
