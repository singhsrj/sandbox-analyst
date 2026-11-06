"""HTTP endpoints.

GET    /api/health
GET    /api/examples                         anonymous: example question chips
GET    /api/schema                           anonymous: schema browser data
POST   /api/session                          access code -> bearer token
POST   /api/chat                             SSE (AI SDK UI message stream)        [auth]
GET    /api/threads                          this visitor's threads                [auth]
GET    /api/threads/{id}                     thread + run history (replayable)     [auth]
DELETE /api/threads/{id}                                                           [auth]
GET    /api/threads/{id}/artifacts/{name}    chart / CSV / report download         [auth]
"""

from __future__ import annotations

import mimetypes
import time
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app import __version__
from app.api.deps import ServicesDep, SessionDep, client_ip
from app.artifacts import artifact_path
from app.auth import code_is_valid, issue_token, normalize_client_id
from app.db.analyst import fetch_catalog
from app.db.app_store import ThreadNotFound
from app.service.chat import ServerBusy, ThreadBusy
from app.streaming.sse import SSE_HEADERS, sse_stream

router = APIRouter(prefix="/api")

EXAMPLE_QUESTIONS = [
    "Why did revenue drop in March 2025, and which regions were affected?",
    "Which product category has the highest return rate, and what do its reviews say?",
    "Which customer segment churns the most, and how large is the gap?",
    "How does revenue seasonality look across 2024 and 2025?",
    "Which marketing channel brings in the most valuable customers?",
    "What will our revenue be in 2027?",  # unanswerable on purpose: should be declined
]

_THREAD_ID_PATTERN = r"^[A-Za-z0-9_-]{8,64}$"


# --------------------------------------------------------------------------- models
class SessionRequest(BaseModel):
    code: str = Field(min_length=1, max_length=200)
    client_id: str | None = Field(default=None, max_length=64)


class ChatPart(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: str
    text: str | None = None


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="allow")
    role: str
    parts: list[ChatPart] | None = None
    content: str | None = None


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str = Field(pattern=_THREAD_ID_PATTERN)
    messages: list[ChatMessage] = Field(min_length=1, max_length=500)
    model: str | None = Field(default=None, max_length=120)


def last_user_text(request: ChatRequest) -> str:
    for message in reversed(request.messages):
        if message.role != "user":
            continue
        if message.parts:
            return "".join(p.text or "" for p in message.parts if p.type == "text").strip()
        return (message.content or "").strip()
    return ""


# --------------------------------------------------------------------------- public
@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    """Liveness. Never depends on the database or other services, so a load balancer does not
    kill a healthy process that is still connecting. Extra detail appears once services are up."""
    body: dict[str, Any] = {"status": "ok", "version": __version__}
    services = getattr(request.app.state, "services", None)
    if services is not None:
        body.update(
            env=services.settings.app_env,
            live_runs_enabled=services.settings.demo_access_code is not None,
            active_runs=services.chat.active_runs,
        )
    return body


@router.get("/examples")
async def examples() -> dict[str, list[str]]:
    return {"questions": EXAMPLE_QUESTIONS}


_schema_cache: dict[str, Any] = {"at": 0.0, "value": None}


@router.get("/schema")
async def schema(services: ServicesDep) -> dict[str, Any]:
    """Tables, columns and business notes of the analytics schema (cached for 5 minutes)."""
    if _schema_cache["value"] is not None and time.monotonic() - _schema_cache["at"] < 300:
        cached: dict[str, Any] = _schema_cache["value"]
        return cached
    settings = services.settings
    tables = await fetch_catalog(
        settings,
        "SELECT c.relname, GREATEST(c.reltuples, 0)::bigint, "
        "coalesce(obj_description(c.oid, 'pg_class'), '') "
        "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'analytics' AND c.relkind = 'r' ORDER BY c.relname",
    )
    columns = await fetch_catalog(
        settings,
        "SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod), NOT a.attnotnull, "
        "coalesce(col_description(a.attrelid, a.attnum), '') "
        "FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'analytics' AND c.relkind = 'r' AND a.attnum > 0 "
        "AND NOT a.attisdropped ORDER BY c.relname, a.attnum",
    )
    by_table: dict[str, list[dict[str, Any]]] = {}
    for table, name, type_, nullable, note in columns:
        by_table.setdefault(table, []).append(
            {"name": name, "type": type_, "nullable": bool(nullable), "note": note}
        )
    value = {
        "tables": [
            {
                "name": name,
                "approx_rows": int(rows),
                "description": desc,
                "columns": by_table.get(name, []),
            }
            for name, rows, desc in tables
        ]
    }
    _schema_cache.update(at=time.monotonic(), value=value)
    return value


@router.post("/session")
async def create_session(
    body: SessionRequest, request: Request, services: ServicesDep
) -> dict[str, Any]:
    settings = services.settings
    ip = client_ip(request)
    if not services.login_limiter.allow(ip):
        retry = services.login_limiter.retry_after(ip)
        raise HTTPException(
            status_code=429, detail="Too many attempts.", headers={"Retry-After": str(retry)}
        )
    if settings.demo_access_code is None or settings.session_token_secret is None:
        raise HTTPException(status_code=503, detail="Live runs are not enabled on this server.")
    if not code_is_valid(settings, body.code):
        raise HTTPException(status_code=401, detail="Invalid access code.")
    owner = normalize_client_id(body.client_id)
    token, expires_at = issue_token(settings, owner)
    return {"token": token, "expires_at": expires_at, "client_id": owner}


# --------------------------------------------------------------------------- authenticated
@router.post("/chat")
async def chat(body: ChatRequest, session: SessionDep, services: ServicesDep) -> StreamingResponse:
    settings = services.settings
    question = last_user_text(body)
    if not question:
        raise HTTPException(status_code=422, detail="The message is empty.")
    if len(question) > settings.max_question_chars:
        raise HTTPException(
            status_code=422,
            detail=f"The question is too long (max {settings.max_question_chars} characters).",
        )
    if body.model and body.model != settings.model and body.model not in settings.allowed_models:
        raise HTTPException(status_code=400, detail="That model is not available.")
    if not services.chat_limiter.allow(session.owner_id):
        retry = services.chat_limiter.retry_after(session.owner_id)
        raise HTTPException(
            status_code=429,
            detail="You are sending requests too quickly.",
            headers={"Retry-After": str(retry)},
        )
    try:
        turn = await services.chat.prepare(
            thread_id=body.id, owner_id=session.owner_id, question=question, model=body.model
        )
    except ThreadNotFound as exc:
        raise HTTPException(status_code=404, detail="Thread not found.") from exc
    except ThreadBusy as exc:
        raise HTTPException(status_code=409, detail="This thread is still answering.") from exc
    except ServerBusy as exc:
        raise HTTPException(
            status_code=429,
            detail="The server is busy. Try again shortly.",
            headers={"Retry-After": "10"},
        ) from exc
    return StreamingResponse(
        sse_stream(services.chat.stream(turn)), media_type="text/event-stream", headers=SSE_HEADERS
    )


@router.get("/threads")
async def list_threads(session: SessionDep, services: ServicesDep) -> dict[str, Any]:
    threads = await services.store.list_threads(session.owner_id)
    return {"threads": [t.as_dict() for t in threads]}


@router.get("/threads/{thread_id}")
async def get_thread(
    thread_id: Annotated[str, Field(pattern=_THREAD_ID_PATTERN)],
    session: SessionDep,
    services: ServicesDep,
) -> dict[str, Any]:
    try:
        thread = await services.store.get_thread(thread_id, session.owner_id)
        runs = await services.store.list_runs(thread_id, session.owner_id)
    except ThreadNotFound as exc:
        raise HTTPException(status_code=404, detail="Thread not found.") from exc
    return {"thread": thread.as_dict(), "runs": runs}


@router.delete("/threads/{thread_id}", status_code=204)
async def delete_thread(thread_id: str, session: SessionDep, services: ServicesDep) -> None:
    if not await services.store.delete_thread(thread_id, session.owner_id):
        raise HTTPException(status_code=404, detail="Thread not found.")
    await services.sandboxes.close(thread_id)


@router.get("/threads/{thread_id}/artifacts/{name}")
async def get_artifact(
    thread_id: str, name: str, session: SessionDep, services: ServicesDep
) -> FileResponse:
    try:
        await services.store.get_thread(thread_id, session.owner_id)  # ownership check
    except ThreadNotFound as exc:
        raise HTTPException(status_code=404, detail="Not found.") from exc
    path = artifact_path(services.settings.artifacts_dir, thread_id, name)
    if path is None:
        raise HTTPException(status_code=404, detail="Not found.")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if path.suffix.lower() in {".md", ".txt", ".json"}:
        media_type = "text/plain; charset=utf-8"  # never rendered as HTML by the browser
    return FileResponse(
        path,
        media_type=media_type,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Cache-Control": "private, max-age=300",
        },
    )
