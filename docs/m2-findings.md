# M2 findings (agent core)

Measured on 2026-11-05 against the seeded Neon dataset. **These are single runs per model, not a
benchmark**: they show what the system does and which failure modes exist. Real comparisons come
from the M6 eval harness (80 questions, repeated runs).

## Question used
"Why did revenue drop in March 2025, and which regions were affected?"
Ground truth (`docs/dataset.md`): March revenue $441,892 vs $506,271 in February; the drop is
caused by an outage in the **South** region, with almost no South orders from **2025-03-03 to
2025-03-29** (South: $154,498 → $26,790).

## Single-run comparison (Bedrock ap-south-1, OpenAI-compatible endpoint)

| Model | Status | Found South | Pinned down the dates | Model calls | Tokens | Time |
|---|---|---|---|---|---|---|
| openai.gpt-oss-120b | ok (1 empty reply, nudged) | yes | no timing given | 16 | 165,523 | 57 s |
| zai.glm-4.7 | ok | yes | vague ("early March", weekly totals) | 16 | 181,362 | 83 s |
| moonshotai.kimi-k2.5 | ok | yes | said "March 1" and "no recovery" (both wrong) | 17 | 187,262 | 78 s |
| mistral.mistral-large-3-675b-instruct | ok | yes | "March 4" start (close), but "remainder of the month" (wrong) | 20 | 263,954 | 100 s |
| qwen.qwen3-235b-a22b-2507 | ok | yes | "consistent throughout March" (wrong) | 24 | 281,023 | 95 s |
| deepseek.v3.2 | budget_exceeded | no answer | n/a | 21 | 304,284 | 144 s |

Cost is **unknown**: no verified Bedrock price for ap-south-1 is configured
(`api/app/agent/model_prices.json` is intentionally empty). Only token budgets are enforced.

Takeaway: every model that finished identified the right region and magnitude; none reliably
found the exact outage window. That is the kind of difference the evals must score.

## Failure modes observed (for the README failure analysis)

1. **Empty final message** (gpt-oss-120b): the model ended a turn with no text and no tool call,
   leaving the user with nothing. Mitigation: the runner nudges up to twice and records
   `empty_reply_nudges`.
2. **Claimed files that were never delivered** (gpt-oss-120b): wrote "chart.png (exported)" without
   calling `export_artifact`. A prompt instruction did not fix it. Mitigation in code: everything
   in `/home/user/outputs/` is delivered automatically, and `unverified_file_claims` records any
   chart/report the answer mentions that does not exist. After the fix: 0 unverified claims in 6 runs.
3. **Shallow "why"**: monthly totals only, no daily drill-down, so cause and timing are missed or
   guessed. Not solved by prompting alone; to be measured in M6.
4. **Unsupported statements**: e.g. "no null or duplicate records were observed" with no query
   checking that. To be measured in M6 (answer-correctness checks).
5. **Token appetite**: 165k-300k tokens per question. Most of it is Deep Agents' long built-in
   prompt and tool list re-sent on every model call (about 8k tokens in per call before any data).
6. **Token budget works**: DeepSeek V3.2 was stopped at 304k > 300k tokens instead of running on.

## Infrastructure bugs found and fixed
- `langchain-e2b 0.0.6` crashes on a failed `edit_file` with deepagents 0.6.x
  (`_map_edit_error` missing). Shim in `app/sandbox/e2b_backend.py`, pinned by a test.
- A CTE named like a system table bypassed the first validator (`WITH pg_shadow AS (SELECT * FROM
  pg_shadow)`). Fixed with PostgreSQL CTE scoping; regression tests added.
- `MAX_AGENT_STEPS` initially mapped to LangGraph's recursion limit, which counts graph
  super-steps (about 3 per model call), so "40" meant about 13 model calls. It now counts model
  calls; LangGraph's limit is only a backstop.
- Langfuse's v1 trace API (`/api/public/traces/{id}`) is removed on **2026-11-16**. The M6 eval
  harness must read traces through `/api/public/v2/observations`.

## Verified facts about the platform
- E2B template `code-interpreter-v1` ships Python 3.13, pandas 2.2.3, matplotlib 3.11.2, numpy,
  scipy. With `allow_internet_access=False`: DNS fails, no pip, and the only environment variables
  are E2B's own (no secrets). A runaway `while True` is killed at the command timeout and the
  sandbox stays usable. Sandbox creation takes about 2 s.
- Bedrock's OpenAI-compatible endpoint in ap-south-1 lists 41 models; tool calling worked on 9 of 10
  candidates in a quick round-trip test (nemotron-super-3-120b timed out).
- A Langfuse trace for a 20-call run contained 118 observations, every generation tagged with the
  exact model id, and token usage that summed exactly to our own run record.
