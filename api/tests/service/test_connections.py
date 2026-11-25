"""Users' own databases: the connection service, its routes, and how chat binds a thread to one.

The database side (connect + privilege inspection) is faked here; the real thing is exercised in
tests/datasources/test_postgres_live.py against Neon and a local Postgres.
"""

from __future__ import annotations

import base64
import secrets
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.deps import Services
from app.auth import ClerkVerifier
from app.datasources.base import Catalog, Column, Table
from app.datasources.postgres import Check, ConnectFailed, Inspection, PostgresSource
from app.db.connection_store import ConnectionNotFound
from app.main import create_app
from app.ratelimit import RateLimiter
from app.security.secret_box import SecretBox
from app.service import chat as chat_module
from app.service import connections as conn_module
from app.service.chat import ChatService, DataSourceMismatch
from app.service.connections import (
    ConnectionInput,
    ConnectionLimit,
    ConnectionRejected,
    ConnectionsDisabled,
    ConnectionService,
    ConnectionUnusable,
)
from tests.fakes import (
    FakeAgent,
    FakeConnectionStore,
    FakeSandboxes,
    FakeStore,
    recorded_events,
)
from tests.helpers import ISSUER, clerk_keys, clerk_token, make_settings

PUBLIC_IP = "52.66.10.20"
OWNER = "owner-aaaaaaaa"
OTHER = "owner-bbbbbbbb"

CATALOG = Catalog(
    schema="shop",
    tables=(
        Table("clients", 120, "", (Column("client_id", "integer", False),)),
        Table("invoices", 50_000, "", (Column("amount", "numeric", True),)),
        Table("monthly", -1, "", (Column("total", "numeric", True),), kind="view"),
    ),
)
GOOD = Inspection(
    "16.4",
    (Check("tls", True, "TLS"), Check("no_table_writes", True, "read-only")),
    CATALOG,
)
WRITABLE = Inspection(
    "16.4",
    (
        Check("tls", True, "TLS"),
        Check("no_table_writes", False, "The user can change data in invoices."),
    ),
    CATALOG,
)


def key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


def data(**overrides: Any) -> ConnectionInput:
    values: dict[str, Any] = {
        "name": "Shop prod",
        "host": "db.example.com",
        "port": 5432,
        "database": "shop",
        "username": "reader",
        "password": "s3cret-password",
        "schema_name": "shop",
    }
    values.update(overrides)
    return ConnectionInput(**values)


class FakeDb:
    """Stands in for connect() + inspect(); records what was contacted."""

    def __init__(self) -> None:
        self.inspection = GOOD
        self.connected: list[tuple[str, str, str]] = []  # (host, address, password)
        self.fail_connect: Exception | None = None

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        db = self

        class Conn:
            async def __aenter__(self) -> Conn:
                return self

            async def __aexit__(self, *exc: object) -> None:
                return None

        async def connect(target: Any, address: str) -> Conn:
            if db.fail_connect is not None:
                raise db.fail_connect
            db.connected.append((target.host, address, target.password))
            return Conn()

        async def inspect(conn: Any, schema: str, *, with_catalog: bool = True) -> Inspection:
            return db.inspection if with_catalog else replace(db.inspection, catalog=None)

        monkeypatch.setattr(conn_module, "connect", connect)
        monkeypatch.setattr(conn_module, "inspect", inspect)


async def public_resolver(host: str, port: int) -> list[str]:
    return ["10.0.0.5"] if host.startswith("internal") else [PUBLIC_IP]


@pytest.fixture
def db(monkeypatch: pytest.MonkeyPatch) -> FakeDb:
    fake = FakeDb()
    fake.install(monkeypatch)
    return fake


@pytest.fixture
def app_store() -> FakeStore:
    return FakeStore()


@pytest.fixture
def conn_store(app_store: FakeStore) -> FakeConnectionStore:
    return FakeConnectionStore(app_store)


def make_service(conn_store: FakeConnectionStore, **settings: Any) -> ConnectionService:
    s = make_settings(CONNECTION_ENCRYPTION_KEY=key(), **settings)
    return ConnectionService(
        s,
        conn_store,  # type: ignore[arg-type]
        SecretBox.from_settings(s),
        resolver=public_resolver,
    )


# --------------------------------------------------------------------------- create / test
async def test_a_read_only_connection_is_saved_with_the_password_encrypted(
    db: FakeDb, conn_store: FakeConnectionStore
) -> None:
    service = make_service(conn_store)
    record = await service.create(OWNER, data())
    assert db.connected == [("db.example.com", PUBLIC_IP, "s3cret-password")]
    assert b"s3cret" not in record.secret_ciphertext
    assert record.usable and record.catalog["schema"] == "shop"
    public = record.public(7)
    assert "s3cret" not in repr(public) and "secret_ciphertext" not in public
    assert public["table_count"] == 3 and public["purge_at"] is None


async def test_a_role_that_can_write_is_refused_and_nothing_is_saved(
    db: FakeDb, conn_store: FakeConnectionStore
) -> None:
    db.inspection = WRITABLE
    with pytest.raises(ConnectionRejected) as caught:
        await make_service(conn_store).create(OWNER, data())
    report = caught.value.report
    assert not report.ok and "change data in invoices" in report.message
    assert report.fix_script and 'GRANT SELECT ON ALL TABLES IN SCHEMA "shop"' in report.fix_script
    assert conn_store.records == {}


async def test_a_private_host_is_refused_before_any_connection(
    db: FakeDb, conn_store: FakeConnectionStore
) -> None:
    report = await make_service(conn_store).test(data(host="internal.corp").target())
    assert report.stage == "host" and "private or reserved" in report.message
    assert db.connected == []


async def test_connect_failures_come_back_as_a_report(
    db: FakeDb, conn_store: FakeConnectionStore
) -> None:
    db.fail_connect = ConnectFailed("auth", "The user name or password was not accepted.")
    report = await make_service(conn_store).test(data().target())
    assert report.stage == "connect" and not report.ok and "not accepted" in report.message


async def test_the_number_of_connections_per_owner_is_capped(
    db: FakeDb, conn_store: FakeConnectionStore
) -> None:
    service = make_service(conn_store, MAX_CONNECTIONS_PER_OWNER="2")
    await service.create(OWNER, data())
    await service.create(OWNER, data())
    with pytest.raises(ConnectionLimit):
        await service.create(OWNER, data())
    await service.create(OTHER, data())  # per owner


async def test_without_a_key_the_feature_is_off(conn_store: FakeConnectionStore) -> None:
    service = ConnectionService(make_settings(), conn_store, None)  # type: ignore[arg-type]
    assert not service.enabled
    with pytest.raises(ConnectionsDisabled):
        await service.test(data().target())


# --------------------------------------------------------------------------- use in a run
async def test_a_run_gets_a_source_pinned_to_the_checked_address(
    db: FakeDb, conn_store: FakeConnectionStore
) -> None:
    service = make_service(conn_store)
    record = await service.create(OWNER, data())
    db.connected.clear()
    source = await service.open_source(OWNER, record.connection_id)
    assert isinstance(source, PostgresSource)
    assert db.connected == [("db.example.com", PUBLIC_IP, "s3cret-password")]  # re-checked
    assert source.scope.schema == "shop"
    assert source.scope.tables == {"clients", "invoices", "monthly"}
    assert source.large_tables == {"invoices", "monthly"}  # > row cap, and a view (unknown)


async def test_a_role_that_gained_write_access_stops_working(
    db: FakeDb, conn_store: FakeConnectionStore
) -> None:
    service = make_service(conn_store)
    record = await service.create(OWNER, data())
    db.inspection = WRITABLE
    with pytest.raises(ConnectionUnusable, match="no longer read-only"):
        await service.open_source(OWNER, record.connection_id)
    assert not conn_store.records[record.connection_id].usable  # saved: stays blocked
    db.inspection = GOOD
    with pytest.raises(ConnectionUnusable, match="failed its last check"):
        await service.open_source(OWNER, record.connection_id)
    report = await service.refresh(OWNER, record.connection_id)
    assert report.ok and conn_store.records[record.connection_id].usable


async def test_someone_elses_connection_does_not_exist(
    db: FakeDb, conn_store: FakeConnectionStore
) -> None:
    service = make_service(conn_store)
    record = await service.create(OWNER, data())
    with pytest.raises(ConnectionNotFound):
        await service.open_source(OTHER, record.connection_id)


async def test_a_ciphertext_moved_to_another_row_cannot_be_opened(
    db: FakeDb, conn_store: FakeConnectionStore
) -> None:
    service = make_service(conn_store)
    a = await service.create(OWNER, data(password="password-a"))
    b = await service.create(OWNER, data(password="password-b"))
    conn_store.records[b.connection_id] = replace(b, secret_ciphertext=a.secret_ciphertext)
    with pytest.raises(ConnectionUnusable, match="can no longer be read"):
        await service.open_source(OWNER, b.connection_id)


async def test_refresh_with_a_new_password_keeps_it_only_when_the_check_passes(
    db: FakeDb, conn_store: FakeConnectionStore
) -> None:
    service = make_service(conn_store)
    record = await service.create(OWNER, data())
    db.inspection = WRITABLE
    await service.refresh(OWNER, record.connection_id, password="new-but-writable")
    assert conn_store.records[record.connection_id].secret_ciphertext == record.secret_ciphertext
    db.inspection = GOOD
    await service.refresh(OWNER, record.connection_id, password="new-password")
    db.connected.clear()
    await service.open_source(OWNER, record.connection_id)
    assert db.connected[0][2] == "new-password"


# --------------------------------------------------------------------------- recycle bin
async def test_the_recycle_bin_hides_restores_and_finally_purges(
    db: FakeDb, conn_store: FakeConnectionStore, app_store: FakeStore
) -> None:
    service = make_service(conn_store)
    record = await service.create(OWNER, data())
    cid = record.connection_id
    await app_store.ensure_thread("thread-on-shop", OWNER, "q?", cid)
    await app_store.ensure_thread("thread-sample", OWNER, "q?")

    assert await service.trash(OWNER, cid) == ["thread-on-shop"]
    assert [t.thread_id for t in await app_store.list_threads(OWNER)] == ["thread-sample"]
    with pytest.raises(ConnectionNotFound):
        await service.open_source(OWNER, cid)
    with pytest.raises(ConnectionNotFound):
        await service.restore(OTHER, cid)

    await service.restore(OWNER, cid)
    assert {t.thread_id for t in await app_store.list_threads(OWNER)} == {
        "thread-on-shop",
        "thread-sample",
    }

    await service.trash(OWNER, cid)
    cleaned: list[str] = []

    async def cleanup(thread_id: str) -> None:
        cleaned.append(thread_id)

    assert await service.purge_expired(cleanup) == 0  # not old enough yet
    eight_days_ago = datetime.now(UTC) - timedelta(days=8)
    conn_store.records[cid] = replace(conn_store.records[cid], deleted_at=eight_days_ago)
    with pytest.raises(ConnectionNotFound):
        await service.restore(OWNER, cid)  # past the window
    assert await service.purge_expired(cleanup) == 1
    assert cleaned == ["thread-on-shop"] and conn_store.purged == [cid]
    assert set(app_store.threads) == {"thread-sample"}


# --------------------------------------------------------------------------- chat binding
@pytest.fixture
def patched_chat(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"build_kwargs": None, "handlers": 0}

    async def fake_build_agent(*args: Any, **kwargs: Any) -> Any:
        state["build_kwargs"] = kwargs
        return FakeAgent(recorded_events(), "Done.")

    async def fake_collect(*args: Any, **kwargs: Any) -> list[str]:
        return []

    def fake_handler(settings: Any) -> None:
        state["handlers"] += 1

    monkeypatch.setattr(chat_module, "build_agent", fake_build_agent)
    monkeypatch.setattr(chat_module, "get_model", lambda *a, **k: object())
    monkeypatch.setattr(chat_module, "collect_outputs", fake_collect)
    monkeypatch.setattr(chat_module, "make_handler", fake_handler)
    return state


async def test_a_thread_is_bound_to_its_connection_for_life(
    db: FakeDb,
    conn_store: FakeConnectionStore,
    app_store: FakeStore,
    patched_chat: dict[str, Any],
    tmp_path: Path,
) -> None:
    connections = make_service(conn_store)
    record = await connections.create(OWNER, data())
    chat = ChatService(
        make_settings(ARTIFACTS_DIR=str(tmp_path)),
        app_store,  # type: ignore[arg-type]
        FakeSandboxes(),  # type: ignore[arg-type]
        None,
        connections,
    )
    turn = await chat.prepare(
        thread_id="thread-12345", owner_id=OWNER, question="q?", connection_id=record.connection_id
    )
    chunks = [c async for c in chat.stream(turn)]
    assert isinstance(patched_chat["build_kwargs"]["source"], PostgresSource)
    assert patched_chat["handlers"] == 0  # the user's data is not sent to Langfuse
    run = next(c for c in chunks if c["type"] == "data-run")["data"]
    assert run["data_source"] == record.connection_id

    # A follow-up without connection_id keeps the thread's source...
    turn = await chat.prepare(thread_id="thread-12345", owner_id=OWNER, question="more?")
    assert isinstance(turn.source, PostgresSource)
    # ...and naming another one is refused.
    other = await connections.create(OWNER, data(name="Other"))
    with pytest.raises(DataSourceMismatch):
        await chat.prepare(
            thread_id="thread-12345",
            owner_id=OWNER,
            question="q?",
            connection_id=other.connection_id,
        )
    # Sample threads still trace and get no source.
    turn = await chat.prepare(thread_id="thread-sample1", owner_id=OWNER, question="q?")
    assert turn.source is None
    [c async for c in chat.stream(turn)]
    assert patched_chat["handlers"] == 1


async def test_someone_elses_connection_never_gets_a_thread(
    db: FakeDb,
    conn_store: FakeConnectionStore,
    app_store: FakeStore,
    patched_chat: dict[str, Any],
) -> None:
    connections = make_service(conn_store)
    record = await connections.create(OWNER, data())
    chat = ChatService(
        make_settings(),
        app_store,  # type: ignore[arg-type]
        FakeSandboxes(),  # type: ignore[arg-type]
        None,
        connections,
    )
    with pytest.raises(ConnectionNotFound):
        await chat.prepare(
            thread_id="thread-stolen",
            owner_id=OTHER,
            question="q?",
            connection_id=record.connection_id,
        )
    assert "thread-stolen" not in app_store.threads


# --------------------------------------------------------------------------- routes
@pytest.fixture
def api(
    tmp_path: Path,
    db: FakeDb,
    conn_store: FakeConnectionStore,
    app_store: FakeStore,
    patched_chat: dict[str, Any],
) -> Iterator[tuple[TestClient, Services]]:
    settings = make_settings(
        DEMO_ACCESS_CODE="code",
        CLERK_ISSUER=ISSUER,
        ARTIFACTS_DIR=str(tmp_path),
        CORS_ALLOW_ORIGINS="http://localhost:3000",
        CONNECTION_ENCRYPTION_KEY=key(),
    )
    connections = ConnectionService(
        settings,
        conn_store,  # type: ignore[arg-type]
        SecretBox.from_settings(settings),
        resolver=public_resolver,
    )
    sandboxes = FakeSandboxes()
    services = Services(
        settings=settings,
        store=app_store,  # type: ignore[arg-type]
        sandboxes=sandboxes,  # type: ignore[arg-type]
        chat=ChatService(settings, app_store, sandboxes, None, connections),  # type: ignore[arg-type]
        verifier=ClerkVerifier(settings, keys=clerk_keys()),
        connections=connections,
        connection_test_limiter=RateLimiter(3, 3600),
    )
    with TestClient(create_app(services)) as client:
        yield client, services


def headers(services: Services, owner: str = OWNER, *, live: bool = True) -> dict[str, str]:
    store: FakeStore = services.store  # type: ignore[assignment]
    store.users.setdefault(owner, [owner, live])[1] = live
    return {"Authorization": f"Bearer {clerk_token(owner)}"}


BODY = {
    "name": "Shop prod",
    "host": "db.example.com",
    "database": "shop",
    "username": "reader",
    "password": "s3cret-password",
    "schema": "shop",
}


def test_saving_needs_live_access_and_explicit_consent(api: tuple[TestClient, Services]) -> None:
    client, services = api
    assert (
        client.post(
            "/api/connections",
            json={**BODY, "consent": True},
            headers=headers(services, "owner-nolive01", live=False),
        ).status_code
        == 403
    )
    assert client.post("/api/connections", json=BODY, headers=headers(services)).status_code == 422
    assert (
        client.post(
            "/api/connections", json={**BODY, "consent": False}, headers=headers(services)
        ).status_code
        == 422
    )


def test_create_list_and_read_never_return_the_password(api: tuple[TestClient, Services]) -> None:
    client, services = api
    created = client.post(
        "/api/connections", json={**BODY, "consent": True}, headers=headers(services)
    )
    assert created.status_code == 201
    cid = created.json()["connection"]["connection_id"]
    listed = client.get("/api/connections", headers=headers(services)).json()
    assert listed["enabled"] is True and listed["trash_days"] == 7
    one = client.get(f"/api/connections/{cid}", headers=headers(services))
    for response in (created, one):
        assert "s3cret" not in response.text and "ciphertext" not in response.text
    assert [t["name"] for t in one.json()["catalog"]["tables"]] == [
        "clients",
        "invoices",
        "monthly",
    ]
    assert (
        client.get(f"/api/connections/{cid}", headers=headers(services, OTHER)).status_code == 404
    )


def test_a_writable_role_gets_a_422_with_the_report(
    api: tuple[TestClient, Services], db: FakeDb
) -> None:
    client, services = api
    db.inspection = WRITABLE
    response = client.post(
        "/api/connections", json={**BODY, "consent": True}, headers=headers(services)
    )
    assert response.status_code == 422
    assert response.json()["report"]["fix_script"].startswith("-- Run as an admin")


def test_testing_connections_is_rate_limited(api: tuple[TestClient, Services]) -> None:
    client, services = api
    codes = [
        client.post("/api/connections/test", json=BODY, headers=headers(services)).status_code
        for _ in range(4)
    ]
    assert codes == [200, 200, 200, 429]


def test_input_with_control_characters_or_unknown_fields_is_refused(
    api: tuple[TestClient, Services],
) -> None:
    client, services = api
    for bad in (
        {**BODY, "host": "db.example.com\n"},
        {**BODY, "sslmode": "disable"},
        {**BODY, "tls_mode": "disable"},
        {**BODY, "port": 22},
    ):
        r = client.post("/api/connections/test", json=bad, headers=headers(services))
        assert r.status_code == 422, bad


def test_chat_on_a_connection_and_the_recycle_bin_over_http(
    api: tuple[TestClient, Services],
) -> None:
    client, services = api
    h = headers(services)
    cid = client.post("/api/connections", json={**BODY, "consent": True}, headers=h).json()[
        "connection"
    ]["connection_id"]
    body = {
        "id": "thread-on-shop",
        "connection_id": cid,
        "messages": [{"role": "user", "parts": [{"type": "text", "text": "Total sales?"}]}],
    }
    with client.stream("POST", "/api/chat", json=body, headers=h) as response:
        assert response.status_code == 200
        list(response.iter_lines())
    threads = client.get("/api/threads", headers=h).json()["threads"]
    assert threads[0]["connection_id"] == cid

    # Someone else naming this connection: not found, and no thread is created for them.
    other = {**body, "id": "thread-other1"}
    assert client.post("/api/chat", json=other, headers=headers(services, OTHER)).status_code == 404

    trashed = client.delete(f"/api/connections/{cid}", headers=h).json()["connection"]
    assert trashed["purge_at"] is not None
    assert services.sandboxes.closed == ["thread-on-shop"]  # type: ignore[attr-defined]
    assert client.get("/api/threads", headers=h).json()["threads"] == []
    assert client.get("/api/threads/thread-on-shop", headers=h).status_code == 404
    listed = client.get("/api/connections", headers=h).json()["connections"]
    assert listed[0]["deleted_at"] is not None  # still visible in the bin

    assert client.post(f"/api/connections/{cid}/restore", headers=h).status_code == 204
    assert len(client.get("/api/threads", headers=h).json()["threads"]) == 1


def test_routes_say_when_the_feature_is_off(tmp_path: Path) -> None:
    settings = make_settings(CLERK_ISSUER=ISSUER, ARTIFACTS_DIR=str(tmp_path))
    store = FakeStore()
    services = Services(
        settings=settings,
        store=store,  # type: ignore[arg-type]
        sandboxes=FakeSandboxes(),  # type: ignore[arg-type]
        chat=ChatService(settings, store, FakeSandboxes(), None),  # type: ignore[arg-type]
        verifier=ClerkVerifier(settings, keys=clerk_keys()),
    )
    with TestClient(create_app(services)) as client:
        h = headers(services)
        assert client.get("/api/connections", headers=h).json()["enabled"] is False
        r = client.post("/api/connections/test", json=BODY, headers=h)
        assert r.status_code == 503
