"""Shared service container and request dependencies."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request

from app.auth import AuthError, Session, verify_token
from app.config import Settings
from app.db.app_store import AppStore
from app.ratelimit import RateLimiter
from app.sandbox.manager import SandboxManager
from app.service.chat import ChatService


@dataclass
class Services:
    settings: Settings
    store: AppStore
    sandboxes: SandboxManager
    chat: ChatService
    login_limiter: RateLimiter = field(default_factory=lambda: RateLimiter(5))
    chat_limiter: RateLimiter = field(default_factory=lambda: RateLimiter(10))


def get_services(request: Request) -> Services:
    services: Services | None = getattr(request.app.state, "services", None)
    if services is None:
        raise HTTPException(status_code=503, detail="The service is starting up.")
    return services


ServicesDep = Annotated[Services, Depends(get_services)]


def current_session(
    services: ServicesDep, authorization: Annotated[str | None, Header()] = None
) -> Session:
    """Require `Authorization: Bearer <token>` from POST /api/session."""
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=401,
            detail="Missing access token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return verify_token(services.settings, token.strip())
    except AuthError as exc:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired access token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


SessionDep = Annotated[Session, Depends(current_session)]


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"
