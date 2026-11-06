# web/

Next.js 16 (App Router) + TypeScript + Tailwind v4 + shadcn/ui (Radix) + AI Elements, talking to the
FastAPI backend over the AI SDK UI message stream.

```bash
cp .env.example .env.local        # NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
npm install
npm run dev                       # http://localhost:3000
```

Checks: `npm run lint && npm run typecheck && npm test && npm run build`

## Layout

| Path | What |
|---|---|
| `src/components/app/` | Our UI: workspace, chat session, evidence trail (`assistant-turn`, `tool-steps`), files panel, sidebar, access dialog |
| `src/components/ai-elements/`, `src/components/ui/` | Vendored AI Elements / shadcn components, pruned to what is used and excluded from lint |
| `src/lib/` | API client, auth, stream replay, tool-output parsers (all unit-tested) |
| `test-fixtures/chunks.json` | Chunks produced by the backend adapter from a real recorded run; regenerate with `uv run python scripts/dump_chunks.py` (CI fails if it drifts) |
| `e2e/` | Real-browser smoke test and a mock API (see below) |

## Contract test

`src/lib/__tests__/contract.test.ts` validates every chunk the Python backend emits against the real
`ai` package's own `uiMessageChunkSchema`, then replays them through `readUIMessageStream`. A change
on either side of the protocol fails here instead of in a user's browser.

## Real-browser smoke test (not part of CI)

Drives Chrome with `playwright-core` (no browser download) and writes screenshots to
`e2e/screenshots/` (git-ignored). It also asserts there are no console errors, no cropped file
previews and no horizontal overflow on a phone-sized screen.

```bash
# Live stack: API on :8010 with CORS_ALLOW_ORIGINS=http://localhost:3100, web on :3100
WEB_URL=http://localhost:3100 node e2e/smoke.mjs

# Without a model: serve a recorded real run (access code: demo)
node e2e/mock-api.mjs 8010 &
ACCESS_CODE=demo node e2e/smoke.mjs
```

## Security notes

- Only `NEXT_PUBLIC_*` values reach the browser; there are no secrets in the frontend.
- The access token lives in `sessionStorage` (per tab); the browser id in `localStorage`.
- Model output is rendered through the markdown renderer without raw HTML. The math and mermaid
  plugins are not installed (mermaid would render arbitrary model-written diagrams).
- Sandbox output is shown in a plain `<pre>` with ANSI codes stripped. The ANSI-rendering
  component was removed because its dependency has a quadratic-time regex (DoS on untrusted input).
- Artifacts are fetched with the bearer token and shown from blob URLs.
