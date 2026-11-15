# evals/

Eval harness (M6): golden dataset (80 questions), scorers, `python -m evals.run`, Langfuse dataset logging, reports.

## Two kinds of check

- **Deterministic** (`scoring.py`, no model): numbers within tolerance, the right item first,
  required words (`must_mention`), and claims the data contradicts (`must_not_say`, regexes
  written per question against the reference data, e.g. q011's "all regions dropped").
- **Narrative judge** (`judge.py`, `--judge`, uses `JUDGE_MODEL`): checks whether the answer's
  *explanation* contradicts the reference SQL's real result. It looks only at meaning
  (directions, rankings and "all X" claims), not exact numbers, because every judge tried flagged
  correct numbers. It is reported in its own column and does not change `passed`.

```bash
uv run python -m evals.run --rescore runs/evals/golden-<stamp>.json --judge   # no agent runs
```
