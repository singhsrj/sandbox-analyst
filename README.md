# SandboxAnalyst

Ask a business question in plain English; a deep agent plans the work, runs **read-only SQL** against Postgres through a hardened tool, analyses the results in an **isolated E2B sandbox**, and returns a report with charts, the SQL used and its assumptions â€” with every step traced and evaluated.

> Status: **M2 â€“ agent core done** (M0 scaffolding, M1 Neon roles + seeded dataset, M2 CLI agent). M3 (streaming API) done. Next: M4 frontend. Results, demo link and architecture diagram will be added as they are measured/built. No numbers in this README are claimed until an eval run produces them.

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

## Ask the agent (CLI)

```bash
uv run python -m app.cli "Why did revenue drop in March 2025, and which regions were affected?"
uv run python -m app.cli --model qwen.qwen3-235b-a22b-2507 "Which category has the highest return rate?"
```

The agent plans, inspects the schema, runs read-only SQL (validated, then executed as `analyst_ro`), analyses the CSV in an isolated E2B sandbox (no internet, no secrets), writes a report with charts, and prints model, tokens, time and a Langfuse trace link. Files land in `runs/<thread>/` (git-ignored). See [docs/m2-findings.md](docs/m2-findings.md) for what was measured and which failure modes were seen.

## Run the API

```bash
uv run python -m app.serve --port 8000     # on Windows this selects the event loop psycopg needs
```

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /api/health` | none | liveness |
| `GET /api/examples`, `GET /api/schema` | none | example questions, schema browser data |
| `POST /api/session` | access code | returns a short-lived bearer token |
| `POST /api/chat` | bearer | AI SDK UI message stream (SSE) |
| `GET /api/threads`, `GET /api/threads/{id}`, `DELETE ...` | bearer | thread history (replayable) |
| `GET /api/threads/{id}/artifacts/{name}` | bearer | chart / CSV / report download |

Live runs need `DEMO_ACCESS_CODE` and `SESSION_TOKEN_SECRET` in `.env`; without them login is disabled.

`POST /api/chat` also resumes a run paused for human approval: send `approvals: [{id, approved, reason?, edited_query?}]` instead of a new question (see ADR-022). Measure prompt-injection resistance with `uv run python -m evals.injection` (costs tokens).

## Checks

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q
```

## Docs

- [Project brief](docs/brief.md)
- [Architecture decisions](docs/decisions.md)
- [Security: threat model, defences, measured results, known limits](SECURITY.md)
