"""FastAPI entrypoint. Run locally with: uv run uvicorn app.main:app --reload --app-dir api"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app import __version__
from app.api.deps import Services
from app.api.routes import router
from app.config import Settings, get_settings
from app.db.app_store import AppStore, make_pool
from app.observability import init_langfuse
from app.ratelimit import RateLimiter
from app.sandbox.manager import SandboxManager
from app.service.chat import ChatService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def open_services(settings: Settings) -> AsyncIterator[Services]:
    """Open DB pool + checkpointer + sandbox manager; close and clean up everything on exit."""
    langfuse = init_langfuse(settings)
    pool = make_pool(settings)
    await pool.open(wait=True, timeout=30)
    try:
        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup()
        sandboxes = SandboxManager(settings)
        sandboxes.start_reaper()
        services = Services(
            settings=settings,
            store=AppStore(pool),
            sandboxes=sandboxes,
            chat=ChatService(settings, AppStore(pool), sandboxes, checkpointer),
            login_limiter=RateLimiter(settings.login_attempts_per_minute),
            chat_limiter=RateLimiter(settings.rate_limit_per_minute),
            run_ip_limiter=RateLimiter(settings.runs_per_ip_per_hour, 3600),
            session_ip_limiter=RateLimiter(settings.sessions_per_ip_per_hour, 3600),
        )
        try:
            yield services
        finally:
            await sandboxes.close_all()  # never leave a sandbox running
            if langfuse is not None:
                langfuse.flush()
    finally:
        await pool.close()


def create_app(services_override: Services | None = None) -> FastAPI:
    """Build the app. Tests pass `services_override`; production opens real services at startup."""
    settings = services_override.settings if services_override else get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if services_override is not None:
            app.state.services = services_override
            yield
            return
        async with open_services(settings) as services:
            app.state.services = services
            logger.info("services ready")
            yield

    app = FastAPI(title="SandboxAnalyst API", version=__version__, lifespan=lifespan)

    # Auth is a bearer token in the Authorization header (no cross-site cookies), so credentials
    # mode is not needed. See docs/decisions.md ADR-006.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.include_router(router)
    return app


app = create_app()
