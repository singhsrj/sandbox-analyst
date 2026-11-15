"""HTTP endpoints.

GET    /api/health
GET    /api/examples                         anonymous: example question chips
GET    /api/schema                           anonymous: schema browser data
POST   /api/suggestions                      anonymous: "what else should there be?"
GET    /api/me                               the signed-in user, live access or not [auth]
POST   /api/access                           access code -> live access, once       [auth]
POST   /api/chat                             SSE (AI SDK UI message stream)        [live]
                                             new question, or `approvals` to resume
                                             a run paused for human approval
GET    /api/threads                          this user's threads                   [auth]
GET    /api/threads/{id}                     thread + run history (replayable)     [auth]
DELETE /api/threads/{id}                                                           [auth]
GET    /api/threads/{id}/artifacts/{name}    chart / CSV / report download         [auth]
GET    /api/replays[/{slug}[/files/{name}]]  recorded, checked runs (replay mode)   public

[auth] = a Clerk session token (Authorization: Bearer); [live] = [auth] + access code entered.
"""

from __future__ import annotations

import mimetypes
import time
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app import __version__
from app.agent.approvals import MAX_REASON_CHARS, ApprovalAnswer, ApprovalMismatch
from app.api.deps import LiveSessionDep, ServicesDep, SessionDep, client_ip
from app.artifacts import artifact_path
from app.auth import code_is_valid
from app.db.analyst import fetch_catalog
from app.db.app_store import ThreadNotFound
from app.ratelimit import RateLimiter
from app.security.sql_validator import MAX_SQL_CHARS
from app.service.chat import (
    ApprovalPending,
    BudgetExhausted,
    ServerBusy,
    ThreadBusy,
)
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
class AccessRequest(BaseModel):
    code: str = Field(min_length=1, max_length=200)


class SuggestionRequest(BaseModel):
    text: str = Field(max_length=2000)
    # Honeypot: hidden from people, filled in by naive bots. A filled one is accepted and dropped.
    website: str | None = Field(default=None, max_length=200)


class ChatPart(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: str
    text: str | None = None


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="allow")
    role: str
    parts: list[ChatPart] | None = None
    content: str | None = None


class ApprovalIn(BaseModel):
    """The reviewer's answer to one approval card."""

    id: str = Field(min_length=1, max_length=100)
    approved: bool
    reason: str | None = Field(default=None, max_length=MAX_REASON_CHARS)
    edited_query: str | None = Field(default=None, max_length=MAX_SQL_CHARS)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str = Field(pattern=_THREAD_ID_PATTERN)
    messages: list[ChatMessage] = Field(min_length=1, max_length=500)
    model: str | None = Field(default=None, max_length=120)
    # The browser may make approvals stricter for its questions ("strict"), never turn them off.
    approval_mode: Literal["normal", "strict"] | None = None
    # The browser's IANA timezone ("Asia/Kolkata"); unknown values fall back to UTC. A request
    # hint, not part of the identity, so it works the same with or without authentication.
    timezone: str | None = Field(default=None, max_length=64)
    # Present = this request resumes a run paused for approval (no new question).
    approvals: list[ApprovalIn] | None = Field(default=None, min_length=1, max_length=20)


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
            sign_in_enabled=services.verifier is not None,
            live_runs_enabled=services.verifier is not None
            and services.settings.demo_access_code is not None,
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


@router.post("/suggestions", status_code=204)
async def suggest(body: SuggestionRequest, request: Request, services: ServicesDep) -> None:
    """Anyone may suggest a feature. Stored without IP, email or user id; read in the database."""
    _limit(services.suggestion_limiter, client_ip(request), "Thanks! That's enough for now.")
    if body.website:
        return  # a bot filled the hidden field: pretend it worked
    text = " ".join(body.text.split())
    if len(text) < 3:
        raise HTTPException(status_code=422, detail="Write a few words first.")
    await services.store.add_suggestion(text)


# --------------------------------------------------------------------------- authenticated
@router.get("/me")
async def me(session: SessionDep, services: ServicesDep) -> dict[str, Any]:
    return {
        "user_id": session.owner_id,
        "live_access": session.live_access,
        "live_runs_enabled": services.settings.demo_access_code is not None,
    }


@router.post("/access")
async def grant_access(
    body: AccessRequest, request: Request, session: SessionDep, services: ServicesDep
) -> dict[str, Any]:
    """Enter the demo access code once; the account keeps live access from then on."""
    if session.live_access:
        return {"live_access": True}
    if services.settings.demo_access_code is None:
        raise HTTPException(status_code=503, detail="Live runs are not enabled on this server.")
    # Per user AND per network: neither a new account nor a new IP resets the guessing budget.
    for key in (session.owner_id, f"ip:{client_ip(request)}"):
        _limit(services.login_limiter, key, "Too many attempts.")
    if not code_is_valid(services.settings, body.code):
        raise HTTPException(status_code=401, detail="Invalid access code.")
    await services.store.grant_live_access(session.owner_id)
    services.users.forget_owner(session.owner_id)
    return {"live_access": True}


def _limit(limiter: RateLimiter, key: str, detail: str) -> None:
    if not limiter.allow(key):
        raise HTTPException(
            status_code=429, detail=detail, headers={"Retry-After": str(limiter.retry_after(key))}
        )


@router.post("/chat")
async def chat(
    body: ChatRequest, request: Request, session: LiveSessionDep, services: ServicesDep
) -> StreamingResponse:
    """A new question, or (with `approvals`) the reviewer's answers to a paused run."""
    settings = services.settings
    resuming = body.approvals is not None
    question = "" if resuming else last_user_text(body)
    if not resuming:
        if not question:
            raise HTTPException(status_code=422, detail="The message is empty.")
        if len(question) > settings.max_question_chars:
            raise HTTPException(
                status_code=422,
                detail=f"The question is too long (max {settings.max_question_chars} characters).",
            )
        if (
            body.model
            and body.model != settings.model
            and body.model not in settings.allowed_models
        ):
            raise HTTPException(status_code=400, detail="That model is not available.")
    _limit(services.chat_limiter, session.owner_id, "You are sending requests too quickly.")
    _limit(services.run_ip_limiter, client_ip(request), "Too many runs from this network.")
    try:
        if body.approvals is not None:
            answers = [
                ApprovalAnswer(a.id, a.approved, a.reason, a.edited_query) for a in body.approvals
            ]
            turn = await services.chat.prepare_resume(
                thread_id=body.id, owner_id=session.owner_id, answers=answers
            )
        else:
            turn = await services.chat.prepare(
                thread_id=body.id,
                owner_id=session.owner_id,
                question=question,
                model=body.model,
                approval_mode=body.approval_mode,
                timezone=body.timezone,
            )
    except ThreadNotFound as exc:
        raise HTTPException(status_code=404, detail="Thread not found.") from exc
    except ThreadBusy as exc:
        raise HTTPException(status_code=409, detail="This thread is still answering.") from exc
    except ApprovalPending as exc:
        raise HTTPException(
            status_code=409,
            detail="A query in this conversation is waiting for your approval. Approve or "
            "reject it first.",
        ) from exc
    except ApprovalMismatch as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except BudgetExhausted as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
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
    return _safe_file(path, cache="private, max-age=300")


def _safe_file(path: Path, *, cache: str) -> FileResponse:
    """Serve a generated file so the browser can never run it (no HTML, no sniffing, sandboxed)."""
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if path.suffix.lower() in {".md", ".txt", ".json"}:
        media_type = "text/plain; charset=utf-8"  # never rendered as HTML by the browser
    return FileResponse(
        path,
        media_type=media_type,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Cache-Control": cache,
        },
    )


# --------------------------------------------------------------------------- replays (public)
@router.get("/replays")
async def list_replays(services: ServicesDep) -> dict[str, Any]:
    """Recorded, checked runs anyone can watch without the access code."""
    return {"replays": [r.summary() for r in services.replays.list()]}


@router.get("/replays/{slug}")
async def get_replay(slug: str, services: ServicesDep) -> dict[str, Any]:
    replay = services.replays.get(slug)
    if replay is None:
        raise HTTPException(status_code=404, detail="Recorded run not found.")
    return {**replay.summary(), "runs": replay.runs}


@router.get("/replays/{slug}/files/{name}")
async def get_replay_file(slug: str, name: str, services: ServicesDep) -> FileResponse:
    path = services.replays.file(slug, name)
    if path is None:
        raise HTTPException(status_code=404, detail="Not found.")
    return _safe_file(path, cache="public, max-age=3600")
