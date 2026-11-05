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
