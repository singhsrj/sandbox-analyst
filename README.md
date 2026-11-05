# SandboxAnalyst

Ask a business question in plain English; a deep agent plans the work, runs **read-only SQL** against Postgres through a hardened tool, analyses the results in an **isolated E2B sandbox**, and returns a report with charts, the SQL used and its assumptions — with every step traced and evaluated.

> Status: **M1 – database done** (M0 scaffolding, M1 Neon roles + seeded dataset). Results, demo link and architecture diagram will be added as they are measured/built. No numbers in this README are claimed until an eval run produces them.

## Quick start (backend)

Requires [uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env          # fill in values
uv sync                       # installs the locked environment (Python 3.12)
uv run uvicorn app.main:app --reload --app-dir api
# -> http://localhost:8000/api/health
```

## Database (Neon)

```bash
uv run python -m db.provision   # creates analyst_ro / app_rw, writes their URLs into .env
uv run python -m db.migrate      # analytics schema
uv run python -m db.seed         # deterministic synthetic data (~207k rows)
```

See [docs/dataset.md](docs/dataset.md) for the planted insights. Integration tests in `api/tests/db/` try to write as `analyst_ro` and must fail; they are skipped when database credentials are absent.

## Checks

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q
```

## Docs

- [Project brief](docs/brief.md)
- [Architecture decisions](docs/decisions.md)
