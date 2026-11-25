"""A user's own Postgres database as a data source.

We do not control this role, so the guarantee the sample data gets from `analyst_ro` (ADR-009)
has to be re-established here, in layers:

  1. the host passed the SSRF guard (app/security/net_guard.py) and we connect to the address it
     checked (`hostaddr`), with TLS required (`verify-full` against public CAs by default)
  2. `inspect()` REFUSES a role that could write: superuser, CREATEROLE, membership in
     pg_write_all_data / pg_write_server_files / pg_read_server_files / pg_execute_server_program,
     any INSERT/UPDATE/DELETE/TRUNCATE on a table of the schema, or CREATE on the schema -
     directly or through any role it is a member of (membership counts even without INHERIT,
     because a member can SET ROLE). It runs when a connection is saved, refreshed, and at the
     start of every chat turn, so a role that gains a privilege later stops working
  3. every query runs in a READ ONLY transaction with SET LOCAL timeouts (execute_readonly)
  4. the validator only allows the tables in the saved catalog snapshot, and never foreign tables
     (which could reach yet another server)

Names and comments from the user's catalog are untrusted text: they are length-capped here, and
the tools label everything from the database as data, not instructions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

import certifi
import psycopg

from app.config import Settings
from app.datasources.base import Catalog, Column, SourceUnavailable, Table
from app.db.analyst import QueryResult, execute_readonly
from app.security.sql_validator import ValidatedQuery, ValidationScope

TlsMode = Literal["verify-full", "require"]

CONNECT_TIMEOUT_SECONDS = 10
INSPECT_TIMEOUT = "10s"
MAX_TABLES = 300
MAX_TEXT_CHARS = 300  # table/column comments from the user's database
# Names the validator and tools can handle without quoting. Others are listed as skipped.
SIMPLE_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

WRITE_ROLES = (
    "pg_write_all_data",
    "pg_write_server_files",
    "pg_read_server_files",
    "pg_execute_server_program",
)
_KINDS = {"r": "table", "p": "partitioned table", "v": "view", "m": "materialized view"}


@dataclass(frozen=True)
class PostgresTarget:
    host: str  # as the user typed it: used for TLS certificate verification
    port: int
    database: str
    username: str
    password: str = field(repr=False)
    schema: str = "public"
    tls_mode: TlsMode = "verify-full"


@dataclass(frozen=True)
class Check:
    id: str
    ok: bool
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "ok": self.ok, "detail": self.detail}


@dataclass(frozen=True)
class Inspection:
    server_version: str
    checks: tuple[Check, ...]
    catalog: Catalog | None = None

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)


class ConnectFailed(RuntimeError):
    """Could not open a connection. `kind` is a stable code; the message is safe for the owner."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


def _classify(exc: psycopg.Error) -> ConnectFailed:
    text = str(exc).lower()
    if "password authentication failed" in text or "no password supplied" in text:
        return ConnectFailed("auth", "The user name or password was not accepted.")
    if "does not exist" in text and "database" in text:
        return ConnectFailed("database", "That database does not exist on the server.")
    if "certificate" in text or "ssl" in text or "tls" in text:
        return ConnectFailed(
            "tls",
            "The secure (TLS) connection failed. The server must support TLS; with 'verify-full' "
            "its certificate must be issued for this host name by a public certificate authority "
            "(or choose 'require').",
        )
    if "timeout" in text or "timed out" in text:
        return ConnectFailed(
            "timeout",
            "The server did not answer in time. Is it reachable from the internet, and is our "
            "address on its allowlist?",
        )
    if "refused" in text:
        return ConnectFailed("refused", "The server refused the connection on that port.")
    return ConnectFailed("unreachable", "Could not connect to the database.")


async def connect(target: PostgresTarget, address: str) -> psycopg.AsyncConnection[Any]:
    """Open a connection to the CHECKED address (see net_guard.resolve_public)."""
    kwargs: dict[str, Any] = {
        "host": target.host,
        "hostaddr": address,
        "port": target.port,
        "dbname": target.database,
        "user": target.username,
        "password": target.password,
        "sslmode": target.tls_mode,
        "connect_timeout": CONNECT_TIMEOUT_SECONDS,
        "application_name": "sandbox-analyst",
        "autocommit": False,
        "prepare_threshold": None,  # works behind PgBouncer in transaction mode
    }
    if target.tls_mode == "verify-full":
        # Mozilla's CA bundle (certifi), not sslrootcert=system: the OpenSSL inside psycopg's
        # wheels has no system store on Windows (found live); a file behaves the same everywhere.
        kwargs["sslrootcert"] = certifi.where()
    try:
        return await psycopg.AsyncConnection.connect(**kwargs)
    except psycopg.Error as exc:
        raise _classify(exc) from None  # the driver's text names hosts and addresses: drop it


def _clip(text: str | None) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= MAX_TEXT_CHARS else text[: MAX_TEXT_CHARS - 1] + "…"


async def _rows(conn: Any, query: str, params: Any = ()) -> list[Any]:
    cur = await conn.execute(query, params)
    return list(await cur.fetchall())


async def inspect(
    conn: psycopg.AsyncConnection[Any], schema: str, *, with_catalog: bool = True
) -> Inspection:
    """Check that the role is read-only, and (optionally) load the schema's catalog."""
    try:
        await conn.execute("SET TRANSACTION READ ONLY")
        await conn.execute(f"SET LOCAL statement_timeout = '{INSPECT_TIMEOUT}'")
        return await _inspect(conn, schema, with_catalog)
    finally:
        await conn.rollback()


async def _inspect(conn: Any, schema: str, with_catalog: bool) -> Inspection:
    checks: list[Check] = [
        Check(
            "tls",
            bool(conn.pgconn.ssl_in_use),
            "The connection is encrypted with TLS."
            if conn.pgconn.ssl_in_use
            else "The connection is not encrypted.",
        )
    ]
    ((version, is_super, can_create_roles, schema_oid),) = await _rows(
        conn,
        "SELECT current_setting('server_version'), r.rolsuper, r.rolcreaterole, "
        "(SELECT oid FROM pg_namespace WHERE nspname = %s) "
        "FROM pg_roles r WHERE r.rolname = current_user",
        (schema,),
    )
    checks.append(
        Check(
            "not_superuser",
            not is_super,
            "The user is a superuser: it can change anything. Use a read-only user."
            if is_super
            else "The user is not a superuser.",
        )
    )
    checks.append(
        Check(
            "no_create_role",
            not can_create_roles,
            "The user can create roles (CREATEROLE), so it could grant itself write access."
            if can_create_roles
            else "The user cannot create roles.",
        )
    )
    write_roles = [
        r[0]
        for r in await _rows(
            conn,
            "SELECT r.rolname FROM pg_roles r WHERE r.rolname = ANY(%s) "
            "AND pg_has_role(current_user, r.oid, 'MEMBER') ORDER BY 1",
            (list(WRITE_ROLES),),
        )
    ]
    checks.append(
        Check(
            "no_write_roles",
            not write_roles,
            f"The user is a member of {', '.join(write_roles)}, which can write data or files."
            if write_roles
            else "The user is not in any built-in role that can write.",
        )
    )
    if schema_oid is None:
        checks.append(Check("schema", False, f"There is no schema named '{schema}'."))
        return Inspection(str(version), tuple(checks))

    # Privileges of the user AND of every role it is a member of (a member can SET ROLE).
    member_of = "SELECT r.oid FROM pg_roles r WHERE pg_has_role(current_user, r.oid, 'MEMBER')"
    ((usage, can_create),) = await _rows(
        conn,
        f"SELECT has_schema_privilege(%s::oid, 'USAGE'), EXISTS ({member_of} "
        "AND has_schema_privilege(r.oid, %s::oid, 'CREATE'))",
        (schema_oid, schema_oid),
    )
    checks.append(
        Check(
            "schema",
            bool(usage),
            f"The user can use the schema '{schema}'."
            if usage
            else f"The user has no USAGE privilege on the schema '{schema}'.",
        )
    )
    checks.append(
        Check(
            "no_schema_create",
            not can_create,
            f"The user can create objects in '{schema}' (CREATE privilege). Revoke it, e.g. "
            f"REVOKE CREATE ON SCHEMA {quote_ident(schema)} FROM PUBLIC."
            if can_create
            else f"The user cannot create objects in '{schema}'.",
        )
    )
    writable = [
        r[0]
        for r in await _rows(
            conn,
            "SELECT c.relname FROM pg_class c WHERE c.relnamespace = %s::oid "  # noqa: S608 - constants only
            "AND c.relkind IN ('r', 'p', 'v', 'm', 'f') "
            f"AND EXISTS ({member_of} AND has_table_privilege(r.oid, c.oid, "
            "'INSERT, UPDATE, DELETE, TRUNCATE')) ORDER BY 1 LIMIT 6",
            (schema_oid,),
        )
    ]
    shown = ", ".join(writable[:5]) + (" and more" if len(writable) > 5 else "")
    checks.append(
        Check(
            "no_table_writes",
            not writable,
            f"The user can change data in {shown}. Use a user that only has SELECT."
            if writable
            else "The user cannot insert, update, delete or truncate any table in the schema.",
        )
    )
    catalog = await load_catalog(conn, schema, schema_oid) if with_catalog else None
    if catalog is not None:
        checks.append(
            Check(
                "readable_tables",
                bool(catalog.tables),
                f"The user can read {len(catalog.tables)} table(s) in '{schema}'."
                if catalog.tables
                else f"The user cannot read any table in '{schema}' (GRANT SELECT is missing).",
            )
        )
    return Inspection(str(version), tuple(checks), catalog)


async def load_catalog(conn: Any, schema: str, schema_oid: int) -> Catalog:
    tables = await _rows(
        conn,
        "SELECT c.oid, c.relname, c.relkind, "
        "CASE WHEN c.relkind = 'p' THEN (SELECT coalesce(sum(GREATEST(ch.reltuples, 0)), 0) "
        "  FROM pg_inherits i JOIN pg_class ch ON ch.oid = i.inhrelid WHERE i.inhparent = c.oid) "
        "WHEN c.relkind = 'v' THEN -1 ELSE GREATEST(c.reltuples, 0) END::bigint, "
        "obj_description(c.oid, 'pg_class') "
        "FROM pg_class c WHERE c.relnamespace = %s::oid AND c.relkind IN ('r', 'p', 'v', 'm') "
        "AND NOT c.relispartition AND has_table_privilege(c.oid, 'SELECT') ORDER BY c.relname",
        (schema_oid,),
    )
    kept: list[tuple[int, str, str, int, str | None]] = []
    skipped: list[str] = []
    for oid, name, kind, rows, desc in tables:
        if SIMPLE_NAME.match(name) and len(kept) < MAX_TABLES:
            kept.append((oid, name, kind, int(rows), desc))
        else:
            skipped.append(_clip(name))
    oids = [k[0] for k in kept]
    columns = await _rows(
        conn,
        "SELECT a.attrelid, a.attname, format_type(a.atttypid, a.atttypmod), NOT a.attnotnull, "
        "col_description(a.attrelid, a.attnum) FROM pg_attribute a "
        "WHERE a.attrelid = ANY(%s) AND a.attnum > 0 AND NOT a.attisdropped "
        "AND has_column_privilege(a.attrelid, a.attnum, 'SELECT') ORDER BY a.attrelid, a.attnum",
        (oids,),
    )
    keys = await _rows(
        conn,
        "SELECT k.conrelid, pg_get_constraintdef(k.oid) FROM pg_constraint k "
        "WHERE k.conrelid = ANY(%s) AND k.contype IN ('p', 'f') "
        "ORDER BY k.conrelid, k.contype DESC, k.oid",
        (oids,),
    )
    cols_by: dict[int, list[Column]] = {}
    for rel, name, type_, nullable, note in columns:
        cols_by.setdefault(rel, []).append(Column(_clip(name), type_, bool(nullable), _clip(note)))
    keys_by: dict[int, list[str]] = {}
    for rel, definition in keys:
        keys_by.setdefault(rel, []).append(_clip(definition))
    return Catalog(
        schema=schema,
        skipped=tuple(skipped),
        tables=tuple(
            Table(
                name=name,
                approx_rows=rows,
                description=_clip(desc),
                columns=tuple(cols_by.get(oid, [])),
                keys=tuple(keys_by.get(oid, [])),
                kind=_KINDS.get(kind, "table"),
            )
            for oid, name, kind, rows, desc in kept
        ),
    )


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def read_only_role_script(database: str, schema: str) -> str:
    """SQL the owner can run (as an admin) to create a user this app accepts."""
    db, sch = quote_ident(database), quote_ident(schema)
    return (
        "-- Run as an admin of your database, then connect with this user.\n"
        "CREATE ROLE sandbox_analyst_reader LOGIN PASSWORD 'choose-a-long-password';\n"
        f"GRANT CONNECT ON DATABASE {db} TO sandbox_analyst_reader;\n"
        f"GRANT USAGE ON SCHEMA {sch} TO sandbox_analyst_reader;\n"
        f"GRANT SELECT ON ALL TABLES IN SCHEMA {sch} TO sandbox_analyst_reader;\n"
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {sch} GRANT SELECT ON TABLES "
        "TO sandbox_analyst_reader;\n"
        "ALTER ROLE sandbox_analyst_reader SET default_transaction_read_only = on;\n"
    )


class PostgresSource:
    """Queries go to the user's database; the catalog is the snapshot saved with the connection
    (so the allowlist is fixed for a run and known without a round trip)."""

    engine_name = "Postgres"
    description = "the user's own data"

    def __init__(
        self,
        *,
        target: PostgresTarget,
        address: str,
        catalog: Catalog,
        settings: Settings,
        notes: str = "",
    ) -> None:
        self._target = target
        self._address = address
        self._catalog = catalog
        self._settings = settings
        self.notes = notes
        self.scope = ValidationScope(
            schema=target.schema, tables=frozenset(t.name for t in catalog.tables)
        )
        # Unknown sizes (views) count as large: a raw read of one deserves a look.
        self.large_tables = frozenset(
            t.name
            for t in catalog.tables
            if t.approx_rows < 0 or t.approx_rows > settings.sql_max_rows
        )

    async def catalog(self) -> Catalog:
        return self._catalog

    async def run_readonly(self, query: ValidatedQuery) -> QueryResult:
        try:
            conn = await connect(self._target, self._address)
        except ConnectFailed as exc:
            raise SourceUnavailable(f"The database could not be reached: {exc}") from None
        async with conn:
            return await execute_readonly(
                conn,
                query,
                cap=self._settings.sql_max_rows,
                timeout_ms=self._settings.sql_statement_timeout_ms,
                schema=self._target.schema,
            )
