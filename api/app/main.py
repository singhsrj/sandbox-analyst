"""FastAPI entrypoint. Run locally with: uv run uvicorn app.main:app --reload --app-dir api"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="SandboxAnalyst API", version=__version__)

    # Auth uses a bearer token in the Authorization header (no cross-site cookies),
    # so credentials mode is not needed. See docs/decisions.md ADR-006.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__, "env": settings.app_env}

    return app


app = create_app()
