"""Shared service container and request dependencies."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request

from app.auth import AuthError, ClerkVerifier, Session
from app.config import Settings
from app.db.app_store import AppStore, UserInfo
from app.ratelimit import RateLimiter
from app.replays import ReplayStore
from app.sandbox.manager import SandboxManager
from app.service.chat import ChatService


@dataclass
class Services:
    settings: Settings
    store: AppStore
    sandboxes: SandboxManager
    chat: ChatService
    verifier: ClerkVerifier | None = None  # None = sign-in is not configured
    login_limiter: RateLimiter = field(default_factory=lambda: RateLimiter(5))  # code, per min
    chat_limiter: RateLimiter = field(default_factory=lambda: RateLimiter(10))  # per user, min
    run_ip_limiter: RateLimiter = field(default_factory=lambda: RateLimiter(20, 3600))  # per IP, h
    suggestion_limiter: RateLimiter = field(default_factory=lambda: RateLimiter(5, 3600))  # per IP
    replays: ReplayStore = field(default_factory=lambda: ReplayStore(Path("/nonexistent")))
    users: UserCache = field(default_factory=lambda: UserCache())


class UserCache:
    """Clerk id -> our user, for a minute, so a request does not always cost a database write.
    The access-code grant drops the user's entry, so a granted user never waits for expiry."""

    TTL_SECONDS = 60.0

    def __init__(self) -> None:
        self._entries: dict[str, tuple[float, UserInfo]] = {}

    def get(self, provider_sub: str) -> UserInfo | None:
        entry = self._entries.get(provider_sub)
        if entry is None or entry[0] < time.monotonic():
            return None
        return entry[1]

    def put(self, provider_sub: str, user: UserInfo) -> None:
        if len(self._entries) > 10_000:  # bounded: drop everything rather than grow forever
            self._entries.clear()
        self._entries[provider_sub] = (time.monotonic() + self.TTL_SECONDS, user)

    def forget_owner(self, user_id: str) -> None:
        for sub in [s for s, (_, user) in self._entries.items() if user.user_id == user_id]:
            del self._entries[sub]


def get_services(request: Request) -> Services:
    services: Services | None = getattr(request.app.state, "services", None)
    if services is None:
        raise HTTPException(status_code=503, detail="The service is starting up.")
    return services


ServicesDep = Annotated[Services, Depends(get_services)]


PROVIDER = "clerk"


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"})


async def current_session(
    services: ServicesDep, authorization: Annotated[str | None, Header()] = None
) -> Session:
    """Require `Authorization: Bearer <Clerk session token>` and map it to our user."""
    if services.verifier is None:
        raise HTTPException(status_code=503, detail="Sign-in is not enabled on this server.")
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _unauthorized("Sign in to continue.")
    try:
        identity = await services.verifier.verify(token.strip())
    except AuthError as exc:
        raise _unauthorized("Your sign-in has expired. Sign in again.") from exc
    user = services.users.get(identity.provider_sub)
    if user is None:
        user = await services.store.user_for(PROVIDER, identity.provider_sub)
        services.users.put(identity.provider_sub, user)
    return Session(
        owner_id=user.user_id, expires_at=identity.expires_at, live_access=user.live_access
    )


SessionDep = Annotated[Session, Depends(current_session)]


def live_session(session: SessionDep) -> Session:
    """Signed in AND has entered the access code (live runs cost model tokens)."""
    if not session.live_access:
        raise HTTPException(status_code=403, detail="Enter the access code to run live questions.")
    return session


LiveSessionDep = Annotated[Session, Depends(live_session)]


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"
