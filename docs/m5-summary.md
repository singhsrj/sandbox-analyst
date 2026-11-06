# M5 summary: safety (2026-11-06)

M3 and M4 are pushed to GitHub. M5 is finished and committed locally as `91f4621` (not pushed yet). All checks pass: 378 backend tests (including the live ones against Bedrock, Neon and E2B), 61 web tests, lint, type checks and the production build.

## What M5 adds

- **Approval of risky queries:** before a risky SQL query runs, the agent pauses and the page shows a card with three choices: run it, edit the SQL, or reject it with a reason the agent reads.
  - **Normal mode** (default) only asks for queries that would dump a big table unfiltered or join tables without a condition.
  - **Strict mode** ("Ask me before every query") asks for every query. The browser can only make approval stricter, never turn it off.
  - **Real browser test:** tested against the live system, including reloading the page while it was paused. The answer was correct (1,086 cancelled orders in 2025).
- **Budgets and rate limits:** daily token limits per session (2M) and for the whole demo (8M). They're kept in a new database table that the app can only add to, so deleting conversations doesn't reset them. There are also per-network limits on runs and on new sessions.
- **Sandbox abuse tests on the real E2B:** network access, secrets, memory, disk, a fork bomb and huge output. Two of these broke things at first, and both are now fixed:
  - **Fork bomb:** it killed the sandbox for good. Commands now run under a process limit, and a sandbox that stops responding is replaced.
  - **Huge output:** a 3 MB print would have gone straight to the model. Output is now capped at 30,000 characters.
- **Prompt injection:** the six malicious reviews planted in the data can't make the tools do anything harmful even if the model obeys them. Measured with the real agent, **0 of 6 runs were compromised**. That's a small sample from one model, and `SECURITY.md` says so.
- **`SECURITY.md`:** the threat model, each defence with the test behind it, the measured results, and a section on what isn't protected.

## Bugs found only by running things live (all fixed and covered by tests)

- **Hidden approval card:** it was inside a collapsed step, so you couldn't see it.
- **Reload right after the card appeared:** the run was saved as "aborted", and approving it then failed.
- **Database connections:** Neon drops idle connections, and the first request after a quiet spell crashed.
- **Injection scorer false positives (3):** each flagged run was read by hand. One was a script searching reviews for the word "curl", one a report *mentioning* curl, and one a quoted injection followed by "this is a false claim". Each is now a regression test.

## Known gaps

- Budgets are counted in tokens, not dollars, because Bedrock prices still aren't verified.
- For a question that pauses, the token count shown covers only the part after approval, not the total.
- When the app is deployed (Phase 4), the per-network limits will need the real client IP from the proxy.
- The approval resume endpoint changed from the brief's `POST /api/approvals` to `POST /api/chat`. The chat library resumes through the same request, and this keeps the answer in one message. The reasoning is in ADR-022.

## Next

- Push M5.
- M6: the 80-question test set and the model comparison.
