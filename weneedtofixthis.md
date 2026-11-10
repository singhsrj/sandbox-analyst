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

- [ ] Add a judge step to `evals/scoring.py`: inputs are the answer text plus the reference SQL
      result; output is pass/fail and a reason, stored in the run record.
- [ ] Rescore the stored batch-1 records (no new agent runs needed) and compare with today's scores.
- [ ] Check the judge's verdicts by hand on a sample of answers.
- [ ] Add direction facts (option 1) to q011 and similar questions.
- [ ] Report back to the commenter on how far this got us.
