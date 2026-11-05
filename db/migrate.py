"""Apply SQL migrations from db/migrations/ using the admin connection.

Usage: uv run python -m db.migrate
Applied versions are recorded in public.schema_migrations; re-running is a no-op.
"""

from __future__ import annotations

from pathlib import Path

import psycopg

from app.config import get_settings

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def migrate(conn: psycopg.Connection) -> list[str]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS public.schema_migrations ("
        "version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
    )
    conn.commit()
    applied = {row[0] for row in conn.execute("SELECT version FROM public.schema_migrations")}
    newly_applied: list[str] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.stem in applied:
            continue
        with conn.transaction():
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO public.schema_migrations (version) VALUES (%s)", (path.stem,))
        newly_applied.append(path.stem)
    return newly_applied


def main() -> None:
    settings = get_settings()
    with psycopg.connect(settings.secret("admin_database_url")) as conn:
        done = migrate(conn)
    print("applied:", ", ".join(done) if done else "nothing (up to date)")


if __name__ == "__main__":
    main()
