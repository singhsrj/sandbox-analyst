"""Users' own databases: test, save, check, open for a run, recycle bin and purge.

Every path that touches a user's database goes: SSRF guard (resolve + pin the address) ->
connect with TLS -> read-only privilege inspection. A connection is only saved, and only used for
a run, when every check passes; the check is repeated at the start of each chat turn.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from app.config import Settings
from app.datasources.base import Catalog
from app.datasources.postgres import (
    ConnectFailed,
    Inspection,
    PostgresSource,
    PostgresTarget,
    connect,
    inspect,
    read_only_role_script,
)
from app.db.connection_store import ConnectionNotFound, ConnectionRecord, ConnectionStore
from app.security.net_guard import HostNotAllowed, Resolver, resolve_public, system_resolver
from app.security.secret_box import SecretBox, SecretBoxError, connection_context

logger = logging.getLogger(__name__)

__all__ = [
    "ConnectionInput",
    "ConnectionLimit",
    "ConnectionNotFound",
    "ConnectionRejected",
    "ConnectionService",
    "ConnectionUnusable",
    "ConnectionsDisabled",
    "TestReport",
]


class ConnectionsDisabled(RuntimeError):
    """CONNECTION_ENCRYPTION_KEY is not configured."""


class ConnectionLimit(RuntimeError):
    """The owner already has the maximum number of connections."""


class ConnectionUnusable(RuntimeError):
    """The connection exists but cannot be used right now. The message is safe for the owner."""


@dataclass(frozen=True)
class ConnectionInput:
    name: str
    host: str
    port: int
    database: str
    username: str
    password: str = field(repr=False)
    schema_name: str = "public"
    tls_mode: Literal["verify-full", "require"] = "verify-full"
    notes: str = ""
    engine: Literal["postgres"] = "postgres"

    def target(self) -> PostgresTarget:
        return PostgresTarget(
            host=self.host.strip(),
            port=self.port,
            database=self.database,
            username=self.username,
            password=self.password,
            schema=self.schema_name,
            tls_mode=self.tls_mode,
        )


@dataclass(frozen=True)
class TestReport:
    ok: bool
    stage: str  # "host" | "connect" | "checks"
    message: str
    checks: list[dict[str, Any]] = field(default_factory=list)
    server_version: str | None = None
    table_count: int = 0
    skipped_tables: list[str] = field(default_factory=list)
    fix_script: str | None = None  # SQL to create an acceptable read-only user
    catalog: Catalog | None = field(default=None, repr=False)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "stage": self.stage,
            "message": self.message,
            "checks": self.checks,
            "server_version": self.server_version,
            "table_count": self.table_count,
            "skipped_tables": self.skipped_tables,
            "fix_script": self.fix_script,
        }


class ConnectionRejected(RuntimeError):
    """The connection failed its test; `report` says why."""

    def __init__(self, report: TestReport) -> None:
        super().__init__(report.message)
        self.report = report


def _report(target: PostgresTarget, inspection: Inspection) -> TestReport:
    catalog = inspection.catalog
    ok = inspection.ok
    failed = [c for c in inspection.checks if not c.ok]
    return TestReport(
        ok=ok,
        stage="checks",
        message="Connected. The user is read-only."
        if ok
        else "Connected, but this user cannot be used: " + failed[0].detail,
        checks=[c.as_dict() for c in inspection.checks],
        server_version=inspection.server_version,
        table_count=len(catalog.tables) if catalog else 0,
        skipped_tables=list(catalog.skipped) if catalog else [],
        fix_script=None if ok else read_only_role_script(target.database, target.schema),
        catalog=catalog,
    )


class ConnectionService:
    def __init__(
        self,
        settings: Settings,
        store: ConnectionStore,
        box: SecretBox | None,
        *,
        resolver: Resolver = system_resolver,
    ) -> None:
        self._settings = settings
        self._store = store
        self._box = box
        self._resolver = resolver

    @property
    def enabled(self) -> bool:
        return self._box is not None

    @property
    def store(self) -> ConnectionStore:
        return self._store

    def _require_box(self) -> SecretBox:
        if self._box is None:
            raise ConnectionsDisabled()
        return self._box

    async def _address(self, target: PostgresTarget) -> str:
        return await resolve_public(
            target.host,
            target.port,
            resolver=self._resolver,
            allow_private=self._settings.allow_private_connection_hosts,
        )

    # ------------------------------------------------------------------ test / create / refresh
    async def test(self, target: PostgresTarget) -> TestReport:
        """Resolve, connect and inspect. Never raises for a bad target: the report says why."""
        self._require_box()
        try:
            address = await self._address(target)
        except HostNotAllowed as exc:
            return TestReport(ok=False, stage="host", message=str(exc))
        try:
            conn = await connect(target, address)
        except ConnectFailed as exc:
            return TestReport(ok=False, stage="connect", message=str(exc))
        try:
            async with conn:
                inspection = await inspect(conn, target.schema)
        except Exception:
            logger.exception("inspecting a connection failed")
            return TestReport(
                ok=False, stage="checks", message="Connected, but the checks could not be run."
            )
        return _report(target, inspection)

    async def create(self, owner_id: str, data: ConnectionInput) -> ConnectionRecord:
        box = self._require_box()
        if await self._store.count_active(owner_id) >= self._settings.max_connections_per_owner:
            raise ConnectionLimit()
        target = data.target()
        report = await self.test(target)
        if not report.ok or report.catalog is None:
            raise ConnectionRejected(report)
        connection_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        record = ConnectionRecord(
            connection_id=connection_id,
            owner_id=owner_id,
            engine=data.engine,
            name=data.name.strip(),
            host=target.host,
            port=target.port,
            database=target.database,
            username=target.username,
            schema_name=target.schema,
            tls_mode=target.tls_mode,
            secret_ciphertext=box.seal(data.password, connection_context(connection_id, owner_id)),
            key_id=box.key_id,
            notes=data.notes.strip(),
            catalog=report.catalog.to_dict(),
            checks=report.checks,
            checked_at=now,
            consented_at=now,
            created_at=now,
            updated_at=now,
        )
        await self._store.insert(record)
        return record

    async def refresh(
        self, owner_id: str, connection_id: str, *, password: str | None = None
    ) -> TestReport:
        """Re-check privileges and reload the table list; optionally replace the password.
        A failing result is saved too: the connection then stays unusable until it passes."""
        box = self._require_box()
        record = await self._store.get(connection_id, owner_id)
        context = connection_context(connection_id, owner_id)
        target = self._target(record, password if password is not None else self._open(record))
        report = await self.test(target)
        if report.stage != "checks":
            return report  # could not even connect: keep the last known check result
        secret = (box.seal(password, context), box.key_id) if password is not None else None
        await self._store.update_inspection(
            connection_id,
            owner_id,
            checks=report.checks,
            catalog=report.catalog.to_dict() if report.ok and report.catalog else None,
            secret=secret if report.ok else None,
        )
        return report

    async def update_details(
        self, owner_id: str, connection_id: str, *, name: str | None, notes: str | None
    ) -> ConnectionRecord:
        await self._store.update_details(
            connection_id,
            owner_id,
            name=name.strip() if name is not None else None,
            notes=notes.strip() if notes is not None else None,
        )
        return await self._store.get(connection_id, owner_id)

    # ------------------------------------------------------------------ use in a run
    async def open_source(self, owner_id: str, connection_id: str) -> PostgresSource:
        """A data source for a chat turn, after re-checking that the user is still read-only.

        Raises ConnectionNotFound (missing, someone else's, or in the recycle bin) or
        ConnectionUnusable (with a message for the owner).
        """
        self._require_box()
        record = await self._store.get(connection_id, owner_id)
        if not record.usable:
            raise ConnectionUnusable(
                f"The connection '{record.name}' failed its last check. Open it under Data "
                "sources and run the check again."
            )
        target = self._target(record, self._open(record))
        try:
            address = await self._address(target)
            conn = await connect(target, address)
        except (HostNotAllowed, ConnectFailed) as exc:
            raise ConnectionUnusable(f"'{record.name}': {exc}") from None
        async with conn:
            inspection = await inspect(conn, target.schema, with_catalog=False)
        if not inspection.ok:
            checks = [c.as_dict() for c in inspection.checks]
            await self._store.update_inspection(
                connection_id, owner_id, checks=checks, catalog=None
            )
            failed = next(c for c in inspection.checks if not c.ok)
            raise ConnectionUnusable(f"'{record.name}' is no longer read-only: {failed.detail}")
        return PostgresSource(
            target=target,
            address=address,
            catalog=Catalog.from_dict(record.catalog),
            settings=self._settings,
            notes=record.notes,
        )

    def _open(self, record: ConnectionRecord) -> str:
        box = self._require_box()
        try:
            return box.open(
                record.secret_ciphertext,
                connection_context(record.connection_id, record.owner_id),
                record.key_id,
            )
        except SecretBoxError as exc:
            raise ConnectionUnusable(
                f"The saved password for '{record.name}' can no longer be read. Enter it again."
            ) from exc

    @staticmethod
    def _target(record: ConnectionRecord, password: str) -> PostgresTarget:
        return PostgresTarget(
            host=record.host,
            port=record.port,
            database=record.database,
            username=record.username,
            password=password,
            schema=record.schema_name,
            tls_mode="require" if record.tls_mode == "require" else "verify-full",
        )

    # ------------------------------------------------------------------ recycle bin
    async def trash(self, owner_id: str, connection_id: str) -> list[str]:
        return await self._store.trash(connection_id, owner_id)

    async def restore(self, owner_id: str, connection_id: str) -> None:
        await self._store.restore(connection_id, owner_id, self._settings.connection_trash_days)

    async def purge_expired(self, cleanup_thread: Callable[[str], Awaitable[None]]) -> int:
        """Delete connections that have been in the recycle bin too long, with everything that
        holds their data: sandboxes, checkpoints, delivered files, threads and runs."""
        purged = 0
        for connection_id, thread_ids in await self._store.expired(
            self._settings.connection_trash_days
        ):
            try:
                for thread_id in thread_ids:
                    await cleanup_thread(thread_id)
                await self._store.purge(connection_id)
                purged += 1
            except Exception:
                logger.exception("purging connection %s failed; retrying later", connection_id)
        return purged
