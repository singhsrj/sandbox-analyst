# We need to fix this: the explanation isn't scored

## The problem

The agent always works from real data: it writes SQL, runs it, and gets real results. But the
model then reads those results and writes the explanation itself, and it can misread them.

Example (q011): the query results showed North revenue going **up**, but the model wrote "all
regions dropped, North the most". The data was right and the explanation was wrong.

| Step | Who does it | Can it be wrong? |
|---|---|---|
| Running SQL and fetching the data | Code and the database | No, it's real data |
| Turning that data into a verdict | The model | **Yes, it can misread it** |

Today `evals/scoring.py` checks the numbers (within a tolerance) and the `must_mention` facts, but
says outright: "Narrative quality is NOT judged here." A fluent answer with the right numbers and a
wrong explanation can pass. q011 only failed because it happened not to mention South.

## Options

### 1. Check the claims in code (deterministic)
Add expected facts to each golden question (e.g. `North: up`, `South: down`). The scorer fails
the answer if it contradicts one.
- Pros: cheap, the same result every time, fits the existing scorer.
- Cons: facts are written by hand per question; phrasing is hard to match.

### 2. Use a judge model
A second model gets the answer and the reference SQL's results and is asked: "Does every
claim in this answer match this data?" It returns pass or fail with a reason.
- Pros: catches any kind of wrong claim; no hand-written rules.
- Cons: costs tokens; the judge can be wrong too, so check it by hand on a sample.

### 3. Fix it in the agent itself
Before answering, the agent checks each claim against its own query results and drops or flags
any claim that no result row supports.
- Pros: stops the mistake from reaching users, not just in the eval.
- Cons: slower and more tokens on every question; the model is checking its own work.

## Decision

- **Start with option 2** for the eval. It's the fastest way to measure how often this happens.
  Check the judge's verdicts by hand on a sample before trusting it.
- **Add option 1** for the few questions where the direction of a change is the whole answer
  (e.g. q011).
- **Leave option 3** until we know how common the problem is.

## Next steps

- [x] Add a judge step: `evals/judge.py`, run with `python -m evals.run ... --judge`. Inputs are
      the answer text plus the reference SQL's real result; the verdict, the contradicted claims
      and a reason are stored in the results file and shown in a separate "story" column. It does
      not change `passed` yet.
- [x] Rescore the stored batch-1 records (no new agent runs needed) and compare with today's scores.
- [x] Check the judge's verdicts by hand on a sample of answers (all 5 first-version flags; see below).
- [x] Add direction facts (option 1) to q011: new `must_not_say` field (regexes) in the golden set.
- [ ] Add `must_not_say` to the other questions where direction or ranking is the whole answer.
- [ ] Run the judge on the full 80-question run, hand-check every flag, then decide whether it gates `passed`.
- [ ] Report back to the commenter on how far this got us.

## What we found (2026-11-15, batch-1 run from 2026-11-06, judge `openai.gpt-oss-120b`)

**The judge caught a second q011-style answer that the scorer missed.** q009 said "all categories
have average ratings above 4.0; the lowest is Home & Kitchen at 4.13". Footwear is 3.11, and the
answer quietly left out three categories.

Final result, the same in 3 of 3 runs: 3 answers flagged (q007, q009, q011), all correct on a hand
check, and no false positives.

| q | Claim flagged | Hand check |
|---|---|---|
| q007 | "Everyday Router" is in the top 5 | correct: the 5th is Essential Walking Shoes |
| q009 | "all above 4.0", "lowest is Home & Kitchen" | correct: Footwear is 3.11 |
| q011 | "all regions dropped", "largest drop in North" | correct: North +31%, East and West also rose |

How we got there:
1. **First version (judge checked numbers too): 2 false positives in 5 flags.** q017 ("24 rows
   across 12 emails" is the same thing as 12 extra rows) and q018 ("excluding returned items", a
   definition the answer states). Telling the judge to respect stated definitions did not fix it.
2. **Other judges were worse.** qwen3-235b and mistral-large-3 flagged even plainly consistent
   numbers (q013 "742 churned = 67.5% of 1,100"; q014 "95.47%" against 95.5%).
3. **Fix: the judge only checks meaning.** Only three kinds of claim count: direction (rose/fell),
   ranking (largest, top 5) and sweeping ("all X"). Exact numbers stay with the deterministic
   scorer, which has per-question tolerances. Any other complaint is dropped in code.
4. **Remaining risk:** with an earlier wording, q017 came back once as a false "direction" claim,
   so the judge is not perfectly stable. It also runs on the same model as the agent. Re-check
   by hand on the full run before letting it gate `passed`.

**Side fix found on the way:** `golden_check.run()` used a session `SET statement_timeout`. Through
Neon's pooler this leaked into other connections (ADR-009) and broke
`test_statement_timeout_cancels_and_leaves_no_state_behind` once the judge ran ~150 reference
queries. It now uses `SET LOCAL` in a transaction.
