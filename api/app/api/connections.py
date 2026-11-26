"""Routes for users' own databases.

GET    /api/connections                       mine, incl. the recycle bin        [auth]
POST   /api/connections/test                  test without saving -> report      [live]
POST   /api/connections                       test + save (needs consent)        [live]
GET    /api/connections/{id}                  details + table list               [auth]
PATCH  /api/connections/{id}                  name, notes                        [auth]
POST   /api/connections/{id}/refresh          re-check, reload tables, new pwd   [live]
DELETE /api/connections/{id}                  to the recycle bin                 [auth]
POST   /api/connections/{id}/restore          out of the recycle bin             [auth]

Anything that contacts the user's database needs live access (like a chat run) and is rate
limited per account and per IP, so the API cannot be used to probe hosts. The password is
accepted, encrypted and never returned.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Path, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.deps import LiveSessionDep, Services, ServicesDep, SessionDep, client_ip
from app.db.connection_store import ConnectionNotFound
from app.service.connections import (
    ConnectionInput,
    ConnectionLimit,
    ConnectionRejected,
    ConnectionService,
    ConnectionUnusable,
)

router = APIRouter(prefix="/api/connections")

ConnectionId = Annotated[
    str, Path(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
]


def _no_control_chars(value: str) -> str:
    if any(ord(ch) < 32 for ch in value):
        raise ValueError("must not contain control characters")
    return value


class ConnectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    engine: Literal["postgres"] = "postgres"
    name: str = Field(min_length=1, max_length=60)
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=5432, ge=1024, le=65535)
    database: str = Field(min_length=1, max_length=63)
    username: str = Field(min_length=1, max_length=63)
    password: str = Field(min_length=1, max_length=1000)
    schema_name: str = Field(default="public", alias="schema", min_length=1, max_length=63)
    tls_mode: Literal["verify-full", "require"] = "verify-full"
    notes: str = Field(default="", max_length=2000)

    _check = field_validator("name", "host", "database", "username", "password", "schema_name")(
        _no_control_chars
    )

    @field_validator("notes")
    @classmethod
    def _notes(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("must not contain NUL characters")
        return value

    def to_input(self) -> ConnectionInput:
        return ConnectionInput(
            engine=self.engine,
            name=self.name,
            host=self.host,
            port=self.port,
            database=self.database,
            username=self.username,
            password=self.password,
            schema_name=self.schema_name,
            tls_mode=self.tls_mode,
            notes=self.notes,
        )


class CreateConnectionIn(ConnectionIn):
    # The owner agreed that query previews go to the AI model and results are processed in an
    # isolated sandbox, and that files are kept until they delete the conversation.
    consent: Literal[True]


class ConnectionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=60)
    notes: str | None = Field(default=None, max_length=2000)


class RefreshIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str | None = Field(default=None, min_length=1, max_length=1000)


def _service(services: Services) -> ConnectionService:
    if services.connections is None or not services.connections.enabled:
        raise HTTPException(
            status_code=503, detail="Connecting your own database is not enabled on this server."
        )
    return services.connections


def _limit_probe(services: Services, owner_id: str, request: Request) -> None:
    for limiter, key in (
        (services.connection_test_limiter, owner_id),
        (services.connection_ip_limiter, client_ip(request)),
    ):
        if not limiter.allow(key):
            raise HTTPException(
                status_code=429,
                detail="Too many connection attempts. Try again later.",
                headers={"Retry-After": str(limiter.retry_after(key))},
            )


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Data source not found.")


@router.get("")
async def list_connections(session: SessionDep, services: ServicesDep) -> dict[str, Any]:
    days = services.settings.connection_trash_days
    service = services.connections
    if service is None or not service.enabled:
        return {"enabled": False, "trash_days": days, "connections": []}
    records = await service.store.list_for(session.owner_id)
    return {
        "enabled": True,
        "trash_days": days,
        "max_connections": services.settings.max_connections_per_owner,
        "connections": [r.public(days) for r in records],
    }


@router.post("/test")
async def test_connection(
    body: ConnectionIn, request: Request, session: LiveSessionDep, services: ServicesDep
) -> dict[str, Any]:
    service = _service(services)
    _limit_probe(services, session.owner_id, request)
    report = await service.test(body.to_input().target())
    return report.as_dict()


@router.post("", status_code=201, response_model=None)
async def create_connection(
    body: CreateConnectionIn, request: Request, session: LiveSessionDep, services: ServicesDep
) -> dict[str, Any] | JSONResponse:
    service = _service(services)
    _limit_probe(services, session.owner_id, request)
    try:
        record = await service.create(session.owner_id, body.to_input())
    except ConnectionLimit as exc:
        raise HTTPException(
            status_code=409,
            detail=f"You can save up to {services.settings.max_connections_per_owner} "
            "databases. Delete one first.",
        ) from exc
    except ConnectionRejected as exc:
        return JSONResponse(
            status_code=422, content={"detail": exc.report.message, "report": exc.report.as_dict()}
        )
    return {"connection": record.public(services.settings.connection_trash_days)}


@router.get("/{connection_id}")
async def get_connection(
    connection_id: ConnectionId, session: SessionDep, services: ServicesDep
) -> dict[str, Any]:
    service = _service(services)
    try:
        record = await service.store.get(connection_id, session.owner_id)
    except ConnectionNotFound as exc:
        raise _not_found() from exc
    return {
        "connection": record.public(services.settings.connection_trash_days),
        "catalog": record.catalog,
    }


@router.patch("/{connection_id}")
async def update_connection(
    connection_id: ConnectionId, body: ConnectionPatch, session: SessionDep, services: ServicesDep
) -> dict[str, Any]:
    service = _service(services)
    try:
        record = await service.update_details(
            session.owner_id, connection_id, name=body.name, notes=body.notes
        )
    except ConnectionNotFound as exc:
        raise _not_found() from exc
    return {"connection": record.public(services.settings.connection_trash_days)}


@router.post("/{connection_id}/refresh")
async def refresh_connection(
    connection_id: ConnectionId,
    body: RefreshIn,
    request: Request,
    session: LiveSessionDep,
    services: ServicesDep,
) -> dict[str, Any]:
    service = _service(services)
    _limit_probe(services, session.owner_id, request)
    try:
        report = await service.refresh(session.owner_id, connection_id, password=body.password)
    except ConnectionNotFound as exc:
        raise _not_found() from exc
    except ConnectionUnusable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return report.as_dict()


@router.delete("/{connection_id}")
async def trash_connection(
    connection_id: ConnectionId, session: SessionDep, services: ServicesDep
) -> dict[str, Any]:
    """To the recycle bin: hidden with its conversations, restorable for CONNECTION_TRASH_DAYS."""
    service = _service(services)
    try:
        thread_ids = await service.trash(session.owner_id, connection_id)
    except ConnectionNotFound as exc:
        raise _not_found() from exc
    for thread_id in thread_ids:  # sandboxes hold copies of query results: stop them now
        await services.sandboxes.close(thread_id)
    record = await service.store.get(connection_id, session.owner_id, include_trashed=True)
    return {"connection": record.public(services.settings.connection_trash_days)}


@router.post("/{connection_id}/restore", status_code=204)
async def restore_connection(
    connection_id: ConnectionId, session: SessionDep, services: ServicesDep
) -> None:
    service = _service(services)
    try:
        await service.restore(session.owner_id, connection_id)
    except ConnectionNotFound as exc:
        raise _not_found() from exc
