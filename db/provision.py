"""Create the database roles and write their connection strings into .env.

Usage:
    uv run python -m db.provision             # create missing roles, apply db/roles.sql
    uv run python -m db.provision --rotate    # also reset both passwords and rewrite .env

Passwords are generated here, applied with ALTER ROLE and written to the gitignored .env.
They are never printed. The admin URL (neondb_owner, direct connection) is the input.

Resulting URLs:
    ANALYST_DATABASE_URL = analyst_ro @ POOLED host  (agent SQL tool)
    APP_DATABASE_URL     = app_rw     @ DIRECT host  (threads, LangGraph checkpointer)
"""

from __future__ import annotations

import re
import secrets
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import psycopg
from psycopg import sql

from app.config import REPO_ROOT, get_settings

ROLES_SQL = Path(__file__).parent / "roles.sql"
ENV_FILE = REPO_ROOT / ".env"


def _pooled_host(host: str) -> str:
    first, _, rest = host.partition(".")
    return host if first.endswith("-pooler") else f"{first}-pooler.{rest}"


def _direct_host(host: str) -> str:
    return host.replace("-pooler.", ".", 1)


def build_url(admin_url: str, role: str, password: str, *, pooled: bool) -> str:
    parts = urlsplit(admin_url)
    host = parts.hostname or ""
    host = _pooled_host(host) if pooled else _direct_host(host)
    netloc = f"{quote(role)}:{quote(password, safe='')}@{host}"
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def set_env_values(env_path: Path, values: dict[str, str]) -> None:
    """Replace KEY=value lines in-place, keeping any trailing comment; append if missing."""
    text = env_path.read_text(encoding="utf-8")
    for key, value in values.items():
        match = re.search(rf"^{re.escape(key)}=(\S*)", text, re.MULTILINE)
        if match:
            text = text[: match.start(1)] + value + text[match.end(1) :]
        else:
            text = text.rstrip("\n") + f"\n{key}={value}\n"
    env_path.write_text(text, encoding="utf-8")


def _role_exists(conn: psycopg.Connection, role: str) -> bool:
    return conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone() is not None


def _set_password(conn: psycopg.Connection, role: str, password: str, *, create: bool) -> None:
    verb = "CREATE" if create else "ALTER"
    conn.execute(
        sql.SQL("{} ROLE {} LOGIN PASSWORD {}").format(
            sql.SQL(verb), sql.Identifier(role), sql.Literal(password)
        )
    )


def main() -> None:
    rotate = "--rotate" in sys.argv[1:]
    settings = get_settings()
    admin_url = settings.secret("admin_database_url")

    new_values: dict[str, str] = {}
    with psycopg.connect(admin_url, autocommit=True) as conn:
        for role, env_key, pooled in (
            ("analyst_ro", "ANALYST_DATABASE_URL", True),
            ("app_rw", "APP_DATABASE_URL", False),
        ):
            exists = _role_exists(conn, role)
            if exists and not rotate:
                print(f"role {role}: exists (use --rotate to reset its password)")
                continue
            password = secrets.token_urlsafe(32)
            _set_password(conn, role, password, create=not exists)
            new_values[env_key] = build_url(admin_url, role, password, pooled=pooled)
            print(f"role {role}: {'password rotated' if exists else 'created'}")

        conn.execute(ROLES_SQL.read_text(encoding="utf-8"))
        print("applied db/roles.sql")

    if new_values:
        set_env_values(ENV_FILE, new_values)
        print(f"wrote {', '.join(new_values)} to .env")


if __name__ == "__main__":
    main()
