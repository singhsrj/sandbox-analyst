<div align="center">

# SandboxAnalyst

**Ask your data a question in plain English. Get back a report you can check.**

An AI data analyst that writes read-only SQL, runs its Python in an isolated sandbox,<br>
and shows the query, code and assumptions behind every number.

[**Live demo**](https://sandbox-analyst.vercel.app) · [How it works](#how-it-works) · [Security](SECURITY.md) · [Design decisions](docs/decisions.md)

</div>

---

## Why SandboxAnalyst?

Text-to-SQL chatbots are easy to build and hard to trust. They **make up numbers**, they can **drop tables or leak credentials**, they **hide their working**, and **nobody measures them**. SandboxAnalyst is built around fixing those four problems.

- **You can check every answer.** The report includes the exact SQL, the Python, the charts and the stated assumptions. Every step streams live while it runs.
- **The database is safe.** SQL goes through two independent defences: an AST validator (one `SELECT`, allowlisted tables) and a Postgres role that can only read. Either one alone is enough to stop a write.
- **Model-written code is treated as hostile.** It runs in a throwaway E2B VM with no network access and no secrets. Only the query result is sent into the sandbox, never the database credentials.
- **Risky queries wait for a human.** Large or unfiltered queries pause so a person can approve, edit or reject them. The pause survives a page reload and a server restart.
- **Quality is measured.** A golden question set with answers defined by reference SQL, a deterministic scorer, and a prompt-injection eval, all in [`evals/`](evals/).

## Try it

**[sandbox-analyst.vercel.app](https://sandbox-analyst.vercel.app)**: recorded, fact-checked runs are open to everyone. Asking your own questions needs an access code.

Example questions it is built for:

> *Why did revenue drop in March 2025, and which regions were affected?*<br>
> *Which category has the highest return rate?*<br>
> *What are customers saying in their reviews?*

The data is a synthetic e-commerce warehouse (~207k rows) with [planted insights](docs/dataset.md), so the correct answers are known.

## How it works

```
Browser ──▶ Next.js on Vercel ──SSE──▶ FastAPI on EC2 (behind Caddy)
                                         │
                                         ├─ Deep Agent (LangGraph) ──▶ gpt-oss-120b on Amazon Bedrock
                                         ├─ run_sql ─▶ validator ─▶ Neon Postgres (read-only role)
                                         ├─ Python, charts ─────────▶ E2B sandbox VM (no network, no secrets)
                                         └─ traces ─────────────────▶ Langfuse
```

1. **Plan:** the agent writes a visible to-do list.
2. **Explore:** it reads the schema.
3. **Query:** `run_sql` validates the query, runs it as `analyst_ro`, writes the result as a CSV into the sandbox, and gives the model only a summary.
4. **Analyse:** pandas and matplotlib run in the sandbox.
5. **Report:** you get findings, charts, the SQL and the assumptions, plus CSV, PNG and Markdown downloads.

## Measured, not claimed

| | Result |
|---|---|
| Golden eval, batch 1 | 17 / 20 correct (the full 80-question run is still pending) |
| Time per question | 26–105 s |
| Tokens per question | ~49k–222k |
| Prompt injection | Measured on a small set of runs; see [SECURITY.md](SECURITY.md) |

Every number here comes from a real run. The known limits, including one confidently wrong answer, are listed in [SECURITY.md](SECURITY.md#what-is-not-protected-known-limits).

## Run it locally

Requires [uv](https://docs.astral.sh/uv/) and Node 20+, plus accounts for Neon, E2B, Langfuse and a model endpoint (see `.env.example`).

```bash
cp .env.example .env              # fill in values
uv sync
uv run python -m db.provision     # creates the read-only and app roles
uv run python -m db.migrate && uv run python -m db.seed

uv run python -m app.cli "Why did revenue drop in March 2025?"   # ask from the terminal
```

<details>
<summary>API server, web app and checks</summary>

```bash
# API (on Windows, this picks the event loop that psycopg needs)
uv run python -m app.serve --port 8000          # http://localhost:8000/api/health

# Web
cd web && npm install && npm run dev

# Checks
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q
```

To log in to live runs, set `DEMO_ACCESS_CODE` and `SESSION_TOKEN_SECRET`. The full endpoint list is in [`api/app/api/routes.py`](api/app/api/routes.py). Deployment is covered in [docs/deploy.md](docs/deploy.md) and [infra/](infra/README.md).

</details>

## Stack

**Agent:** LangChain Deep Agents on LangGraph · **API:** FastAPI (SSE) · **Web:** Next.js, Vercel AI SDK, AI Elements · **Data:** Neon Postgres · **Sandbox:** E2B · **SQL safety:** sqlglot · **Observability:** Langfuse · **Infra:** Docker, Caddy, Terraform, AWS EC2 and Bedrock

## Learn more

- [Security](SECURITY.md): threat model, defences, measured results and known limits
- [Architecture decisions](docs/decisions.md): 27 short ADRs
- [Dataset](docs/dataset.md): schema and planted insights
- [Deployment](docs/deploy.md)
