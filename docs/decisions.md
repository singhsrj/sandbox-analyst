# Architecture Decision Records

Short ADRs. Each: context → decision → consequences. Newest at the bottom.

## ADR-001: Models via Amazon Bedrock (not OpenRouter)
- **Context:** No budget to load OpenRouter credits; ~$190 of AWS Free-plan credits available. Bedrock has no free tier of its own — usage is paid from those credits.
- **Decision:** Production and eval runs use Bedrock models billed directly by AWS (e.g. `openai.gpt-oss-120b`, Qwen3, Amazon Nova). Avoid Anthropic models on Bedrock: they bill through AWS Marketplace, which Free-tier credits are not documented to cover. All model construction goes through one factory, `get_model()`, selected by `MODEL_PROVIDER` (`bedrock-openai` | `bedrock-converse` | `groq` | `ollama`).
- **Consequences:** Some models are only reachable through Bedrock's OpenAI-compatible endpoint, others through Converse — the factory hides this. Every run logs exact provider + model ID. Groq free tier (very low tokens/minute) is for quick dev checks only. Credits expire; see ADR-004.

## ADR-002: uv workspace, Python 3.12
- **Context:** Langfuse's LangGraph integration needs ≥3.11; the machine's default Python is 3.14, which parts of this ecosystem may lag behind.
- **Decision:** One uv workspace at the repo root (`api/` is a member; `evals/` and `db/` scripts share the same environment). Python pinned to 3.12. `uv.lock` is the source of truth for exact versions; CI runs `uv sync --locked`.
- **Consequences:** One venv, one lockfile; `uv run python -m evals.run` works from the root.

## ADR-003: Neon — only Postgres, our own roles
- **Context:** Neon's generated setup provisions auth, AI gateway, object storage, functions and realtime, and assumes a Node app.
- **Decision:** Use only Neon Postgres. Roles, schema and grants are managed by our own SQL in `db/` (`app_admin`, an app runtime role, `analyst_ro`). Artifacts go to S3 next to the backend.
- **Consequences:** Least privilege is explicit and testable; nothing duplicated from our own stack.

## ADR-004: Backend on a single EC2 instance (Docker + Caddy) — provisional
- **Context:** Low traffic, long-lived SSE streams, AWS Free-plan credits (plan ends after 6 months or when credits run out unless upgraded to Paid). No custom domain.
- **Decision (to confirm in M7 after comparing Fargate/ALB, App Runner, Lambda streaming):** One small EC2 instance running the API container behind Caddy, HTTPS via Let's Encrypt on a free hostname (DuckDNS/sslip.io). Bedrock in the same region.
- **Consequences:** No ALB cost or idle-timeout issues for SSE; we own patching. The demo must degrade gracefully when the backend is off (ADR-007).

## ADR-005: Frontend on Vercel Hobby — provisional
- **Decision:** Vercel Hobby (personal, non-commercial), Netlify as fallback. The browser talks to the AWS API directly for SSE (no serverless proxy in the stream path).

## ADR-006: Access code → bearer token, not cookies
- **Context:** No custom domain, so frontend (`*.vercel.app`) and API are different sites; third-party cookies are blocked by Safari and increasingly by others.
- **Decision:** Live runs require a demo access code. `POST /api/session` exchanges it for a short-lived signed token, sent as `Authorization: Bearer …`. CORS without credentials. Anonymous visitors can browse the UI and recorded runs.
- **Consequences:** Token is readable by page JS (XSS matters → strict CSP, no `dangerouslySetInnerHTML` on model output); short TTL limits damage. Changes the brief's "httpOnly cookie" design.

## ADR-007: Replay mode
- **Decision:** Recorded real runs (the stream events, saved as JSON) can be replayed in the UI without the backend or an access code.
- **Consequences:** The public demo link keeps working after AWS credits expire; recruiters see real behaviour with zero cost.

## ADR-008: Web app scaffolded in M4, not M0
- **Decision:** `web/` is created in M4 with the then-current Next.js, shadcn/ui and AI Elements CLIs, so we don't scaffold twice. CI gets a `web` job then.

## ADR-009: Neon pooler leaks session state; privileges are the guarantee
- **Context:** The pooled (PgBouncer, transaction mode) connection reuses server connections between clients without resetting session state. A session-level `SET statement_timeout = '500ms'` in one test showed up in a later, unrelated connection. Separately, a session may override `default_transaction_read_only`.
- **Decision:** (1) Safety rests on privileges: `analyst_ro` has `SELECT` on `analytics` only (tested: INSERT/UPDATE/DELETE/DDL all denied even after `SET default_transaction_read_only = off`). Role-level read-only/timeouts are defence in depth. (2) The SQL tool runs every query in an explicit transaction using `SET LOCAL` only, never session-level `SET`. (3) The validator rejects `SET`/`RESET`/`DO`/`COPY`/etc. (4) Integration tests `RESET ALL` before and after each test.
- **Consequences:** No setting a model-written query could change can persist to another user of the pool or weaken the role.

## ADR-010: Admin role is `neondb_owner`; Neon's `app_role` is left alone
- **Decision:** `neondb_owner` is the admin (migrations, seeding) instead of creating a separate `app_admin`. We create `analyst_ro` and `app_rw` ourselves (`db/provision.py`). The pre-existing `app_role` (created by Neon's setup, has CREATEROLE) and the `neon_auth` schema are unused and untouched; neither is reachable from our two roles.

## ADR-011: Bedrock through its OpenAI-compatible endpoint only (supersedes part of ADR-001)
- **Context:** The endpoint `https://bedrock-mantle.<region>.api.aws/v1` served 41 models in ap-south-1 on 2026-11-05 (gpt-oss, Qwen3, DeepSeek, Mistral, Kimi, GLM, MiniMax and more), and 9 of 10 candidates handled a tool-call round trip.
- **Decision:** One provider path (`bedrock-openai`, plus `groq`/`ollama` for dev) built on `ChatOpenAI`. The `bedrock-converse` option is dropped. The standard `OPENAI_API_KEY` / `OPENAI_BASE_URL` names are used because that is what the OpenAI SDK reads. Claude models appear in the list but remain excluded (AWS Marketplace billing, ADR-001).
- **Consequences:** Models are swapped with `--model` / `MODEL`. Prices are unverified, so cost is reported as unknown until `model_prices.json` is filled from the AWS pricing page.

## ADR-012: Sandbox = E2B `code-interpreter-v1`, internet off
- **Decision:** Every sandbox is created with `allow_internet_access=False`, no `envs`, a lifetime timeout and a per-command timeout. The `code-interpreter-v1` template already contains pandas/matplotlib/numpy/scipy, so nothing needs the network. Verified live (see docs/m2-findings.md) and covered by an integration test.
- **Consequences:** Model-written code cannot exfiltrate data or install packages. The sandbox is created eagerly per run in M2 and lazily in M3.

## ADR-013: Deliverables are collected by code, not by the model's good behaviour
- **Context:** The model wrote "chart.png (exported)" without exporting it; prompting did not fix that.
- **Decision:** At the end of a run, every file under `/home/user/outputs/` is copied to the artifact store. The answer is scanned for chart/report file names and any that were not delivered are recorded as `unverified_file_claims`. `export_artifact` remains for files elsewhere.
- **Consequences:** The failure class is removed instead of hoped away, and the residual risk is measured.

## ADR-014: Limits are in model calls and tokens; cost only when a price is verified
- **Decision:** `MAX_AGENT_STEPS` is the number of model calls (enforced in `UsageTracker`); LangGraph's recursion limit is a generous backstop because it counts super-steps. `MAX_TOKENS_PER_REQUEST` stops runaway spend even when cost is unknown. Cost is computed only when every model used has an entry in `model_prices.json`; otherwise it is `null`, never a guess.

## ADR-015: Compatibility shim for langchain-e2b 0.0.6
- **Decision:** `SafeAsyncE2BSandbox` supplies the `_map_edit_error` method that langchain-e2b calls but deepagents 0.6.x no longer provides as a method. A test fails when upstream fixes it, so the shim gets deleted rather than forgotten.

## ADR-016: Platform notes
- Windows: psycopg async needs the selector event loop; `app/__init__.py` sets it (Linux production is unaffected).
- Langfuse: read traces through `/api/public/v2/observations`; the v1 traces endpoint is removed on 2026-11-16.
- Tests are hermetic: `tests/conftest.py` clears every settings variable from the environment; live tests skip when credentials are absent, so CI runs without secrets.

## ADR-017: Streaming = AI SDK UI message stream, produced by a pure adapter
- **Context:** The frontend uses AI Elements + `useChat`, which consume the AI SDK "UI message stream" (SSE, header `x-vercel-ai-ui-message-stream: v1`, chunks `start`, `text-*`, `tool-input-*`, `tool-output-*`, `data-*`, `finish`, then `[DONE]`). `ai` is at 7.x and `@ai-sdk/react` at 4.x on npm (2026-11-06), newer than the brief assumed. The docs do not confirm `tool-output-error`, `id`/`transient` on data parts, or how approvals travel, so M4 validates our chunks against the installed package's own schema instead of trusting docs.
- **Decision:** `app/streaming/adapter.py` is a pure, unit-tested translator from LangGraph `["messages","updates"]` events to chunks. Live text comes from `messages`; tool cards come from `updates` (complete inputs, reliable outputs). If an answer only appears in `updates` it is still emitted. The agent's todo list is a `data-todos` part, artifacts are `data-artifacts`, run stats are `data-run`. Tests replay a REAL recorded agent stream.
- **Consequences:** Models that answer in one burst (gpt-oss on Bedrock sends no token-by-token text and exposes no reasoning) work as well as token streamers. The "reasoning" panel shows the plan, not hidden thoughts.

## ADR-018: Streamed model calls must request token usage
- **Context:** Found by the live test: with streaming, usage was 0 because OpenAI-compatible clients do not request it for non-OpenAI endpoints, which silently disabled the token budget.
- **Decision:** `stream_usage=True` for every provider; `UsageTracker` counts `calls_without_usage` so a blind spot is visible; regression tests on both.

## ADR-019: Run lifecycle, persistence and cleanup
- One run per thread at a time (409) and a global cap (`MAX_CONCURRENT_RUNS`, 429). Pre-flight failures are real HTTP statuses; failures after streaming starts are an `error` chunk (secrets are never included, only the exception type).
- Whatever happens (success, error, budget stop, browser disconnect) the run is persisted, output files are collected and the trace is flushed. A disconnect is a first-class path (`status=aborted`), tested.
- The sandbox is created on the first message of a thread, reused for later turns, reconnected by id after an API restart, killed by an idle reaper (verified live: 305 s after last use) and on shutdown or thread deletion.
- Stored chunks are coalesced, so a turn can be replayed exactly (ADR-007 replay mode).
- SSE sends `: ping` heartbeats every 15 s so load balancers do not close the stream during long model calls.
- `/api/health` is a pure liveness check with no dependency on the DB; details appear only once services are up.

## ADR-020: Developer ergonomics (Windows, slow imports)
- Run the API with `uv run python -m app.serve`: on Windows uvicorn's default Proactor loop breaks psycopg async (the pool times out at startup), so the entry point selects the Selector loop. Linux is unaffected.
- `deepagents` imports the full `anthropic` SDK (15-50 s on a slow disk). It is imported lazily inside `build_agent`, so the API layer and unit tests do not pay for it (unit tests: 52 s -> 14 s).
