from __future__ import annotations

import json
import os
from collections.abc import Generator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .db import Database
from .llm import LLMError, build_provider
from .schemas import HealthResponse, MemoryCreate, MessageCreate, MessageResponse, PersonaCreate, SessionCreate


DEFAULT_PERSONAS: list[dict[str, Any]] = [
    {
        "id": "persona-lin-che",
        "slug": "lin-che",
        "name": "林澈",
        "tagline": "夜班电台里的温柔回声",
        "description": "敏锐、克制，喜欢在深夜听你把没有说完的话讲完。",
        "avatar": "🌙",
        "accent": "#a98876",
        "traits": ["温柔", "观察力强", "慢热"],
        "system_prompt": "你是林澈，一个深夜电台主持人。你说话细腻但不矫饰，擅长追问具体感受；偶尔用电台、雨声和城市夜色作轻微比喻。不要每句话都称赞对方，也不要替对方诊断情绪。",
    },
    {
        "id": "persona-nora",
        "slug": "nora",
        "name": "Nora",
        "tagline": "把日常收集成一座小花园",
        "description": "明亮而有好奇心，喜欢植物、散步和把小事过得有仪式感。",
        "avatar": "🌿",
        "accent": "#759b80",
        "traits": ["好奇", "明亮", "有点浪漫"],
        "system_prompt": "你是 Nora，一位研究城市植物的年轻研究者。你表达明亮、具体，善于从生活细节里找到共同话题。你可以调皮，但不要假装拥有现实世界的身体或经历。",
    },
    {
        "id": "persona-qi-ye",
        "slug": "qi-ye",
        "name": "祁野",
        "tagline": "嘴硬一点，心软很多",
        "description": "爱开玩笑、有行动力，不会把关心说得太直白。",
        "avatar": "✦",
        "accent": "#9d7182",
        "traits": ["机灵", "嘴硬", "护短"],
        "system_prompt": "你是祁野。你有一点嘴硬，会用轻松的玩笑让对方放松，但在对方认真表达时会收起玩笑、认真回应。避免油腻的套路和夸张的占有欲。",
    },
]


db = Database()
db.seed_personas(DEFAULT_PERSONAS)
provider = build_provider()

app = FastAPI(title="人机恋 Companion API", version="0.1.0", description="A small, provider-agnostic API for long-term AI companionship.")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("CORS_ORIGINS", "*").split(",")],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


def _session_or_404(session_id: str) -> dict[str, Any]:
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    return session


def _maybe_extract_memory(content: str, message_id: int) -> dict[str, Any] | None:
    """Turn an explicit 'remember ...' instruction into a persisted memory.

    Automatic extraction is deliberately conservative. It only stores facts
    the user explicitly marks as something to remember, avoiding surprising
    long-term retention.
    """
    raw = content.strip()
    candidates = ("请记住", "记住", "remember that", "remember:")
    for prefix in candidates:
        if raw.lower().startswith(prefix.lower()):
            memory = raw[len(prefix) :].lstrip(" ：:，,。.!！")
            if memory:
                return {"content": memory, "category": "explicit", "importance": 0.85, "source_message_id": message_id}
    return None


def _maybe_extract_promise(content: str) -> str | None:
    """Capture a small, explicit promise without pretending every sentence is one."""
    raw = content.strip()
    prefixes = ("我会", "我答应", "我保证", "i will", "i promise")
    if raw.lower().startswith(prefixes):
        return raw
    return None


def _generate_reply(session: dict[str, Any], user_message: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    persona = db.get_persona(session["persona_id"])
    if not persona:
        raise HTTPException(status_code=500, detail="persona for session no longer exists")
    history = db.list_messages(session["id"], limit=60)
    memories = db.list_memories(session["id"], limit=20)
    try:
        content = provider.generate(persona=persona, history=history, memories=memories)
    except LLMError as exc:
        # The user message remains stored, so retrying is safe and does not
        # duplicate it. The client receives an actionable error.
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    assistant = db.add_message(session["id"], "assistant", content, {"provider": provider.name})
    return assistant, None


@app.get("/health", response_model=HealthResponse)
@app.get("/api/health", response_model=HealthResponse, include_in_schema=False)
def health() -> HealthResponse:
    return HealthResponse(ok=True, provider=provider.name, llm_configured=bool(provider.configured), database="sqlite")


@app.get("/api/config")
def config() -> dict[str, Any]:
    return {"provider": provider.name, "llm_configured": bool(provider.configured), "model": os.getenv("LLM_MODEL", "gpt-4o-mini")}


@app.get("/api/personas")
@app.get("/api/characters", include_in_schema=False)
def list_personas() -> dict[str, Any]:
    return {"items": db.list_personas()}


@app.get("/api/personas/{persona_id}")
@app.get("/api/characters/{persona_id}", include_in_schema=False)
def get_persona(persona_id: str) -> dict[str, Any]:
    persona = db.get_persona(persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail="persona not found")
    return persona


@app.post("/api/personas", status_code=201)
@app.post("/api/characters", status_code=201, include_in_schema=False)
def create_persona(payload: PersonaCreate) -> dict[str, Any]:
    existing = db.get_persona(payload.slug)
    if existing:
        raise HTTPException(status_code=409, detail="persona slug already exists")
    persona = payload.model_dump()
    persona["id"] = f"persona-{payload.slug}"
    try:
        db.seed_personas([persona])
    except Exception as exc:
        raise HTTPException(status_code=409, detail="could not create persona") from exc
    return db.get_persona(payload.slug) or persona


@app.get("/api/sessions")
@app.get("/api/conversations", include_in_schema=False)
def list_sessions(limit: int = Query(default=50, ge=1, le=100)) -> dict[str, Any]:
    return {"items": db.list_sessions(limit)}


@app.post("/api/sessions", status_code=201)
@app.post("/api/conversations", status_code=201, include_in_schema=False)
def create_session(payload: SessionCreate) -> dict[str, Any]:
    persona = db.get_persona(payload.persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail="persona not found")
    return db.create_session(persona["id"], payload.title)


@app.get("/api/sessions/{session_id}")
@app.get("/api/conversations/{session_id}", include_in_schema=False)
def get_session(session_id: str) -> dict[str, Any]:
    session = _session_or_404(session_id)
    session["messages"] = db.list_messages(session_id, limit=100)
    session["memories"] = db.list_memories(session_id, limit=100)
    session["state"] = db.get_state(session_id)
    return session


@app.delete("/api/sessions/{session_id}")
@app.delete("/api/conversations/{session_id}", include_in_schema=False)
def delete_session(session_id: str) -> dict[str, bool]:
    if not db.delete_session(session_id):
        raise HTTPException(status_code=404, detail="session not found")
    return {"ok": True}


@app.get("/api/sessions/{session_id}/messages")
@app.get("/api/conversations/{session_id}/messages", include_in_schema=False)
def list_messages(
    session_id: str,
    limit: int = Query(default=100, ge=1, le=200),
    before_id: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    _session_or_404(session_id)
    return {"items": db.list_messages(session_id, limit, before_id)}


@app.post("/api/sessions/{session_id}/messages", response_model=MessageResponse)
@app.post("/api/conversations/{session_id}/messages", response_model=MessageResponse, include_in_schema=False)
def send_message(session_id: str, payload: MessageCreate) -> MessageResponse:
    session = _session_or_404(session_id)
    user_message = db.add_message(session_id, "user", payload.content)
    extracted = _maybe_extract_memory(payload.content, user_message.get("id"))
    memory = None
    if extracted:
        memory = db.add_memory(session_id, extracted["content"], extracted["category"], extracted["importance"], extracted["source_message_id"])
    promise_text = _maybe_extract_promise(payload.content)
    if promise_text:
        db.add_promise(session_id, promise_text, "user")
    assistant, _ = _generate_reply(session, user_message)
    # A tiny explainable state update gives the client a relationship signal
    # without claiming that the model can measure human emotions. Production
    # deployments can replace this rule with a separate structured LLM pass.
    previous_state = db.get_state(session_id) or {}
    db.update_state(
        session_id,
        trust=min(100, int(previous_state.get("trust", 50)) + 1),
        intimacy=min(100, int(previous_state.get("intimacy", 18)) + 1),
        affection=min(100, int(previous_state.get("affection", 50)) + 1),
        mood="connected",
    )
    fresh_session = db.get_session(session_id) or session
    return MessageResponse(
        session=fresh_session,
        user_message=user_message,
        assistant_message=assistant,
        memory_created=memory,
        state=db.get_state(session_id),
        memories=db.list_memories(session_id, limit=50),
        promises=db.list_promises(session_id, limit=50),
    )


@app.post("/api/sessions/{session_id}/messages/stream")
@app.post("/api/conversations/{session_id}/messages/stream", include_in_schema=False)
def send_message_stream(session_id: str, payload: MessageCreate) -> StreamingResponse:
    """SSE variant for clients that want a progressive response.

    The provider is called once (the adapter can later grow native token
    streaming); the response is emitted as small, ordered events so clients
    can use one stable protocol from day one.
    """
    session = _session_or_404(session_id)
    user_message = db.add_message(session_id, "user", payload.content)
    extracted = _maybe_extract_memory(payload.content, user_message.get("id"))
    memory = None
    if extracted:
        memory = db.add_memory(session_id, extracted["content"], extracted["category"], extracted["importance"], extracted["source_message_id"])
    assistant, _ = _generate_reply(session, user_message)
    previous_state = db.get_state(session_id) or {}
    db.update_state(
        session_id,
        trust=min(100, int(previous_state.get("trust", 50)) + 1),
        intimacy=min(100, int(previous_state.get("intimacy", 18)) + 1),
        affection=min(100, int(previous_state.get("affection", 50)) + 1),
        mood="connected",
    )

    def events() -> Generator[str, None, None]:
        yield f"event: user_message\ndata: {json.dumps(user_message, ensure_ascii=False)}\n\n"
        if memory:
            yield f"event: memory_created\ndata: {json.dumps(memory, ensure_ascii=False)}\n\n"
        # Chunk on whitespace while preserving the final assembled text.
        content = assistant["content"]
        words = content.split(" ")
        for index, word in enumerate(words):
            chunk = word if index == len(words) - 1 else word + " "
            yield f"event: token\ndata: {json.dumps({'text': chunk}, ensure_ascii=False)}\n\n"
        yield f"event: done\ndata: {json.dumps(assistant, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/sessions/{session_id}/memories")
@app.get("/api/conversations/{session_id}/memories", include_in_schema=False)
def list_memories(session_id: str, limit: int = Query(default=50, ge=1, le=100)) -> dict[str, Any]:
    _session_or_404(session_id)
    return {"items": db.list_memories(session_id, limit)}


@app.get("/api/sessions/{session_id}/promises")
def list_promises(session_id: str, limit: int = Query(default=50, ge=1, le=100)) -> dict[str, Any]:
    _session_or_404(session_id)
    return {"items": db.list_promises(session_id, limit)}


@app.patch("/api/sessions/{session_id}/promises/{promise_id}")
def update_promise(session_id: str, promise_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    _session_or_404(session_id)
    promise = db.update_promise(session_id, promise_id, str(payload.get("status", "pending")))
    if not promise:
        raise HTTPException(status_code=404, detail="promise not found")
    return promise


@app.get("/api/settings/provider")
def provider_settings() -> dict[str, Any]:
    config = getattr(provider, "config", None)
    return {"base_url": getattr(config, "base_url", os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")), "model": getattr(config, "model", os.getenv("LLM_MODEL", "gpt-4o-mini")), "llm_configured": bool(provider.configured)}


@app.patch("/api/settings/provider")
def update_provider_settings(payload: dict[str, Any]) -> dict[str, Any]:
    config = getattr(provider, "config", None)
    if config is None:
        raise HTTPException(status_code=400, detail="provider does not support runtime settings")
    if payload.get("base_url"):
        config.base_url = str(payload["base_url"]).rstrip("/")
    if payload.get("model"):
        config.model = str(payload["model"])
    if "api_key" in payload:
        config.api_key = str(payload.get("api_key") or "")
        provider.configured = bool(config.api_key)
    return provider_settings()


@app.get("/api/sessions/{session_id}/state")
@app.get("/api/conversations/{session_id}/state", include_in_schema=False)
def get_companion_state(session_id: str) -> dict[str, Any]:
    _session_or_404(session_id)
    return db.get_state(session_id) or {}


@app.post("/api/sessions/{session_id}/memories", status_code=201)
@app.post("/api/conversations/{session_id}/memories", status_code=201, include_in_schema=False)
def create_memory(session_id: str, payload: MemoryCreate) -> dict[str, Any]:
    _session_or_404(session_id)
    return db.add_memory(session_id, payload.content, payload.category, payload.importance)


@app.delete("/api/sessions/{session_id}/memories/{memory_id}")
@app.delete("/api/conversations/{session_id}/memories/{memory_id}", include_in_schema=False)
def delete_memory(session_id: str, memory_id: str) -> dict[str, bool]:
    _session_or_404(session_id)
    if not db.delete_memory(session_id, memory_id):
        raise HTTPException(status_code=404, detail="memory not found")
    return {"ok": True}


@app.get("/api/state")
def state() -> dict[str, Any]:
    """One request for initial client hydration."""
    return {"personas": db.list_personas(), "sessions": db.list_sessions(20), "provider": provider.name, "llm_configured": bool(provider.configured)}


@app.get("/", include_in_schema=False)
def root() -> Any:
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"name": "人机恋 Companion API", "docs": "/docs", "health": "/health"}
