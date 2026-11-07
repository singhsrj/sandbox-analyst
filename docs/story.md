# SandboxAnalyst: the whole story

*Written 2026-11-07. Numbers come from measured runs in this repo; see `docs/decisions.md`, `SECURITY.md` and `evals/`.*

## 1. The situation and the problem it solves

**Where it starts.** In most companies the people with business questions ("why did revenue drop in March?", "which customers churn?") aren't the people who can answer them. They file a request and wait for an analyst, who writes SQL, pulls the data into a notebook, makes a chart and writes up the result. Analysts become a queue, and small questions wait days.

**Why "just use an LLM" isn't the answer.** Text-to-SQL chatbots exist, but they fail in ways that matter:
1. **They make up numbers.** A fluent answer with a wrong figure is worse than no answer, because nobody can tell it's wrong.
2. **They're unsafe.** A model that writes SQL or runs code can drop tables, read other schemas, leak credentials, or be hijacked by text hidden in the data.
3. **They're opaque.** You get a conclusion, not the queries and steps behind it, so you can't check it.
4. **Nobody measures them.** "It seems to work" is the usual quality bar.

**What SandboxAnalyst does about it.** You ask a business question in plain English. An AI agent plans the work, runs read-only SQL against the warehouse, analyses the results with Python in an isolated sandbox, and returns a report with charts, the exact SQL used and its stated assumptions. Every step is shown live, so you can check the numbers yourself. Risky queries can wait for human approval, and accuracy is measured against a test set with known answers.

**What it is, honestly.** A portfolio-grade, production-shaped system on a synthetic e-commerce dataset (about 207,000 rows, with planted insights so correctness can be tested). It's built to show how to make an LLM agent *safe, inspectable and measurable*, not to replace an analytics team.

---

## 2. The idea and the architecture

**The idea in one line:** give the model the analyst's tools, but each tool comes with guardrails, and the answer comes with its own evidence.

```
 Browser ──HTTPS──▶ Vercel (Next.js web app)
    │
    └──HTTPS (live stream of events)──▶ EC2 t4g.small, ap-south-1
                              │
                    Caddy (HTTPS, the only way in)
                              │  private Docker network
                    FastAPI app (Docker)
                      ├─ Deep Agent (LangGraph) ──▶ Amazon Bedrock (gpt-oss-120b)
                      ├─ run_sql ──validator──▶ Neon Postgres  [analytics, read-only role]
                      ├─ Python/charts ─────▶ E2B sandbox VM   [no network, no secrets]
                      ├─ threads, runs, checkpoints, usage ──▶ Neon [app schema, app role]
                      └─ traces ────────────▶ Langfuse
```

**The roles:**
- **Web:** chat, an "evidence trail" of every step, the files panel, approval cards, replay mode.
- **API:** login, streaming, run lifecycle, budgets, approvals.
- **Agent:** plans, picks tools, writes the report.
- **Database:** the data being analysed, plus the app's own state.
- **Sandbox:** where model-written code runs.
- **Langfuse:** a trace of every model and tool call.

---

## 3. Lower-level architecture

**Backend (`api/app`)**

| Module | What it does |
|---|---|
| `api/routes.py` | REST and SSE (server-sent events) endpoints: session, chat (a new question, or approval answers that resume a paused run), threads, artifacts, schema, examples, replays, health |
| `auth.py` | Access code → a short-lived bearer token signed with HMAC; each token carries an owner id, and every thread belongs to one owner |
| `service/chat.py` | `ChatService`: checks before a run starts (locks, concurrency, daily budgets, pending approvals), runs the agent, always finishes (collects files, closes the trace, saves the run, records usage), even if the browser disconnects |
| `agent/factory.py` | Builds the Deep Agent: model, our four tools, the sandbox as its file and execute backend, the Postgres checkpointer, the approval middleware, and a helper sub-agent with no database tools |
| `agent/loop.py` | `AgentDriver`: streams events, detects a pause for approval, nudges empty replies |
| `agent/approvals.py` + `security/sql_risk.py` | Human-in-the-loop: per-call interrupts, a deterministic "is this query risky?" check, and mapping approve/edit/reject to resume values |
| `tools/analyst_tools.py` | `list_tables`, `describe_table`, `run_sql` (validate → run as the read-only role → write a CSV into the sandbox → return only a summary), `export_artifact` |
| `security/sql_validator.py` | AST-level SQL validation with sqlglot: one SELECT, an allowlist of tables, no catalogs or unknown functions, PostgreSQL-correct CTE scoping |
| `sandbox/` | One E2B VM per thread: lazy creation, reconnect after restart, idle reaper; a process limit, output cap and health-based replacement |
| `streaming/adapter.py` | A pure translator from LangGraph events to the Vercel AI SDK's UI message stream (text, tool steps, todos, files, run stats, approval chunks) |
| `db/app_store.py` | Threads, runs (the stored stream chunks, so a run can be replayed exactly) and an append-only usage ledger |
| `replays.py` | Read-only public recorded runs |

**Frontend (`web/`):** Next.js 16 and React 19 with `useChat` and a custom transport. It sends only the newest message, because history lives on the server. Its parts:
- **Evidence trail:** one row per step: plan, schema lookups, queries, code.
- **Approval card:** approve, edit the SQL, or reject with a reason.
- **Files panel:** charts, CSVs and the report.
- **Replay mode.**

The token is kept per tab in `sessionStorage`.

**Evals (`evals/`):**
- **Golden questions:** a YAML file, each answer defined by reference SQL that runs as the read-only role.
- **Scorer:** deterministic: numbers within tolerance, ranking order, required mentions, refusals, no write attempts.
- **Runner:** stores raw records so scoring can be rerun for free.
- **Injection eval.**

**Infrastructure:**
- **Container:** a Dockerfile (locked dependencies, non-root user, no secrets in the image).
- **Compose:** Caddy plus the API on a private network.
- **Terraform:** a least-privilege deployer IAM user, then the server (IMDSv2, encrypted disk, SSH from one IP only).

---

## 4. Key system design decisions (and why)

| Decision | Why |
|---|---|
| **Two independent SQL defences:** an AST validator and a read-only database role | Either one alone can fail. A validator bypass was actually found (a CTE that shadows `pg_shadow`), and the role still held |
| **Database credentials never enter the sandbox:** only the result CSV goes in | Model-written code can't read what isn't there |
| **Tools return summaries, not data** (row count, column types, a 5-row preview) | Keeps tokens bounded, makes the model analyse with code, and limits how much untrusted text reaches the prompt |
| **The file list is collected by code, not taken from the model** | The model claimed charts it never saved; now claims that don't match real files are flagged |
| **The model goes through Bedrock's OpenAI-compatible endpoint** | Paid from AWS credits; one client library; no OpenRouter available to us |
| **Our own human-approval middleware (per call)** instead of Deep Agents' `interrupt_on` | The built-in version pauses in batches and doesn't say which tool call it's about, so the card can't attach to the right step |
| **The helper sub-agent gets no database tools** | Our middleware doesn't reach sub-agents, so otherwise they'd be a way around approval |
| **Resuming goes through the same `/api/chat` call** | The chat library continues the same assistant message, and history replays as one turn |
| **The server, not the browser, decides what a resume means** | Model, approval mode and question come from the paused run; the browser can't swap them |
| **An append-only usage ledger** separate from runs | Runs are deleted with their thread, and deleting a conversation mustn't reset a budget |
| **Budgets in tokens, not dollars** | Bedrock prices aren't verified, and we never make up a number |
| **The stream format is checked against the installed `ai` package** | The docs didn't settle several chunk types, so CI fails if they drift instead of the browser breaking |
| **Replay mode is curated and fact-checked** | The demo works without a code or once the budget is spent, and only runs whose numbers were checked get published |
| **A single EC2 server with Caddy**, not App Runner or ECS | Cheapest and simplest for one container; free t4g.small until the end of 2026 |
| **Trust forwarded IPs only from the Docker network's range, never `*`** | With `*`, uvicorn takes the leftmost forwarded address, which the client controls |
| **DuckDNS, not sslip.io** | sslip.io shares one Let's Encrypt limit across all its users; DuckDNS is on the Public Suffix List, so each name has its own |
| **Terraform in two stages** with a narrow deployer user | No admin keys on the laptop; the deployer can only launch t4g.small in one region |
| **One model for evals; a deterministic scorer** | Credit budget; scores are auditable and can be rerun from stored records |

---

## 5. The hardest parts

1. **Trustworthy answers, not just working code.** The agent ran without errors but still got things wrong. In eval q011 it said "all regions dropped, North the most", when North actually *grew* and South fell 83%. It also skipped categories (q009) and silently changed definitions (q007). None of these crash anything, so tests can't catch them; only a golden set with known answers can. Building that scorer was hard in its own right: across two features I found and fixed 5 false positives (curly apostrophes, narrow spaces as thousands separators, quoted injections, keyword filters mistaken for exfiltration code).

2. **Human approval across HTTP requests.** A pause has to survive the request ending, a page reload and a server restart, then resume exactly. That meant LangGraph interrupts, a Postgres checkpointer, matching interrupt ids to the chat library's approval ids, edit support the library doesn't have, and replaying two runs as one message. A live browser test found two bugs unit tests missed: the card hidden in a collapsed step, and a reload during the save turning the run into "aborted", which made the card impossible to answer.

3. **Security edges you only find by trying.**
   - **The CTE shadowing bypass** in the SQL validator.
   - **A wildcard ARN in my own IAM policy** that silently defeated the instance-type rule.
   - **uvicorn's trust of the leftmost forwarded address**, which the client controls.
   - **Fork bombs and output floods** that killed the sandbox in a live probe.
   - **An apparent network escape** (raw TCP connected) that turned out to be E2B's local proxy accepting the connection and passing nothing.

   Each was caught by probing rather than assuming.

4. **Platform friction:**
   - Windows event-loop incompatibility with async psycopg.
   - The Neon pooler leaking session state.
   - Neon dropping idle connections in production.
   - An expired 12-hour Bedrock key hidden by a duplicate `.env` line.
   - CloudShell blocked during AWS account verification.
   - GitHub Actions locked by a billing issue.

---

## 6. The real tradeoffs

| We chose | We gave up |
|---|---|
| An open-weight model (gpt-oss-120b) on credits | Accuracy and reliability of a frontier model; 17 of 20 on batch 1 |
| An isolated VM sandbox per conversation | Latency (sandbox start-up) and extra moving parts |
| Summaries instead of raw results | Sometimes the model needs more of the data and has to go another round |
| A deterministic, regex-based scorer | Judging narrative quality; it can still produce false positives and needs human audits |
| A heuristic for "risky" queries in normal mode | An expensive but unflagged query runs without asking |
| One server, in-memory rate limits | No high availability; limits reset on restart; no horizontal scaling |
| One shared access code | Real identity; anyone with the code gets a fresh session budget, bounded only by per-IP and global limits |
| Token budgets | True cost control in dollars |
| Storing full stream chunks per run | Exact replay, at the cost of storage growth |
| Evaluating one model | Knowing which model is best for this job |
| A public API (required for a browser app) | Exposure to scanners and probing; mitigated, not eliminated |

---

## 7. If we built it again

1. **Evals first.** I'd build the golden set and scorer in week one, not milestone 6. The hallucinated narrative in q011 should have shaped the design, not been found at the end.
2. **Structured answers with citations.** The agent would return its numbers as structured data, each linked to the query result it came from. Then every claimed number can be checked automatically against the data, instead of regex on prose.
3. **A semantic layer.** Definitions like "revenue = delivered orders" would live in versioned metric definitions, not only in prompt text.
4. **Design pause and resume from day one,** not retrofit them into an existing streaming pipeline.
5. **Managed, CI-driven deployment** (Fargate or Cloud Run, or at least a GitHub Actions deploy), shared rate limits in Postgres or Redis, and real login (magic link or OAuth).
6. **Fewer tokens per question.** About 89,000 tokens average and 222,000 at most is costly. Better schema summaries, fewer tool rounds and prompt caching would help.
7. **Check accounts and platforms early:** GitHub billing, AWS verification, and a Linux dev box to avoid Windows-only problems.

---

## 8. Important limitations right now

- **Accuracy:** 17 of 20 on the first batch, including one confidently wrong explanation. Only 40 of the planned 80 questions are approved so far, and the full run is still pending.
- **Speed and cost:** 26–105 seconds and about 49,000–222,000 tokens per question (batch 1). Dollar cost is reported as unknown.
- **One model, one dataset, one hard-coded table allowlist.** You can't plug in your own database yet.
- **No forecasting.** Questions about the future are declined ("next version").
- **Operations:**
  - One server, no failover.
  - Deploys are a manual SSH command.
  - Rate limits are in memory.
  - SSH is pinned to one home IP.
  - CI is currently blocked by GitHub billing.
- **Security:** injection resistance is measured on only 6 runs. The sandbox guards aren't a hard boundary (the sandbox user has sudo inside its own VM). There's one shared access code.
- **Smaller gaps:**
  - When a question pauses for approval, the token count shown covers only the resumed part.
  - The public health endpoint says more than it needs to, and public endpoints have no rate limit.
  - There are only 2 replays.

---

## 9. Sequence diagram (one question, with approval)

```mermaid
sequenceDiagram
    actor U as User
    participant W as Web app (Vercel)
    participant A as API (FastAPI)
    participant G as Deep Agent (LangGraph)
    participant L as Bedrock (gpt-oss-120b)
    participant D as Neon (analyst_ro)
    participant S as E2B sandbox
    participant P as Neon (app: runs, checkpoints, ledger)

    U->>W: Enter access code
    W->>A: POST /api/session
    A-->>W: signed token
    U->>W: "Why did revenue drop in March 2025?"
    W->>A: POST /api/chat (newest message only)
    A->>P: checks: thread lock, budgets, nothing pending
    A-->>W: SSE stream opens
    A->>G: run (thread checkpoint)
    loop plan → explore → query → analyse
        G->>L: next step?
        L-->>G: tool call
        alt run_sql
            G->>G: validate SQL; risky? (normal mode)
            opt needs approval
                G-->>A: interrupt (pause, checkpointed)
                A-->>W: tool-approval-request
                A->>P: save run "awaiting_approval"
                U->>W: Approve / Edit / Reject
                W->>A: POST /api/chat {approvals}
                A->>G: resume(decision)
            end
            G->>D: read-only SELECT
            D-->>G: rows
            G->>S: write CSV into sandbox
        else execute / write_file
            G->>S: run Python (charts, numbers)
            S-->>G: capped output
        end
        A-->>W: step events (live evidence trail)
    end
    G-->>A: final report
    A->>S: collect files from outputs/
    A->>P: save run (chunks), record token usage
    A-->>W: answer, files, run stats, finish
    W-->>U: report + SQL + charts + every step
```

---

## 10. Future features

**Product:**
- Forecasting (promised as "next version").
- Answers with numeric citations and automatic claim checking.
- Connect your own read-only Postgres.
- A semantic layer for metric definitions.
- Shareable conversations.
- Scheduled reports.
- Follow-up suggestions.
- More replays.

**Quality:**
- Finish the 80-question set and the full run.
- An LLM grader for narrative quality alongside the deterministic scorer.
- Larger injection tests.
- Optional multi-model comparison when credits allow.

**Platform:**
- CI/CD deploys.
- Shared rate limits.
- Real accounts.
- Cost in dollars once prices are verified.
- Prompt caching.
- A managed container service.
- A trimmed public health endpoint.
- Rate limits on public endpoints.

---

## 11. Requirements

**Technical: functional**
1. Accept a business question in natural language, plus follow-ups in the same conversation.
2. Plan the work and show the plan.
3. Run SQL only as a single read-only SELECT on the allowed tables, with a row cap and a timeout.
4. Analyse data and make charts in an isolated sandbox.
5. Return a report with summary, findings, charts, the SQL used, and assumptions and caveats.
6. Stream every step live.
7. Keep conversation history per visitor, and replay it exactly.
8. Pause risky queries for approve, edit or reject.
9. Decline unanswerable or prediction questions honestly.
10. Refuse any write or modification.
11. Offer recorded runs without an access code.

**Technical: non-functional**
- **Security:**
  - Two layers of SQL defence.
  - No secrets in the sandbox, browser or image.
  - Least-privilege database and IAM roles.
  - HTTPS only.
  - Spoof-proof client IPs.
  - Tested resistance to injection and sandbox abuse.
- **Cost:**
  - Per-question token and step limits.
  - Daily per-session and global budgets.
  - Rate limits.
  - A cloud budget alarm.
- **Reliability:**
  - A run is always saved, even on disconnect or error.
  - Approvals survive a reload or restart.
  - Database connections are health-checked.
- **Observability:** a Langfuse trace for every run, and stored run records.
- **Quality:**
  - Strict typing and linting.
  - About 413 backend tests (366 unit, 47 live integration) and 67 web tests.
  - A stream contract test.
  - Real-browser end-to-end checks.
  - A golden eval set.
- **Usability:**
  - Works on phones.
  - Light and dark themes.
  - Accessible labels.
  - Clear errors.

**Non-technical**
- **Honesty:**
  - Never invent numbers, costs or results.
  - Every published claim is backed by a test or a measurement.
  - Limitations are stated.
- **Budget:** about $190 in AWS credits. Free tiers wherever possible (Neon, E2B, Langfuse, Vercel, DuckDNS, the t4g.small trial), and no paid domain.
- **People and time:** no deadline, quality first. A human reviews the eval questions, about 30 minutes a day.
- **Data and privacy:** synthetic data only. Reports use aggregates, not individual customers.
- **Audience:** a portfolio project, so the reasoning (decision records, `SECURITY.md`, the deploy guide) is part of the deliverable.
- **Process:** phased milestones, each one demonstrable, tested and committed before the next.
