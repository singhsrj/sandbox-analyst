# Frontend guide: theme and implementation rules

Every change to `web/` follows this file, so new screens look and behave like the existing ones.
It describes what the app already does; when the code and this file disagree, fix one of them in
the same change.

Before writing Next.js code, read the relevant guide in `node_modules/next/dist/docs/`: this is
Next.js 16, and its APIs differ from older versions (see `AGENTS.md`).

---

## 1. Stack and where code goes

| Layer | Use | Not |
|---|---|---|
| Framework | Next.js 16 App Router, React 19, TypeScript (strict) | Pages router |
| Styling | Tailwind v4 utilities + the tokens in `src/app/globals.css` | CSS modules, styled-components, inline `style` for colours |
| Primitives | shadcn/ui (`radix-nova` style, Radix) in `src/components/ui/` | Other component libraries |
| Chat/stream UI | AI Elements in `src/components/ai-elements/`, AI SDK (`ai`, `@ai-sdk/react`) | Hand-rolled stream parsing |
| Markdown | `streamdown` (no raw HTML) | `dangerouslySetInnerHTML` |
| Icons | `lucide-react`, named `XxxIcon` imports | Other icon sets, emoji as icons |
| Class merging | `cn()` from `@/lib/utils` | String concatenation for conditional classes |

| Path | What belongs there |
|---|---|
| `src/components/app/` | Our components. One component (plus small private helpers) per file, kebab-case file names, PascalCase exports |
| `src/components/ui/`, `src/components/ai-elements/` | Vendored registry copies. Not linted. Add with the shadcn CLI; change only when a real need cannot be met by props or `className` |
| `src/lib/` | Framework-free logic: API client, auth, parsing, formatting. Unit-tested |
| `src/hooks/` | React hooks (`use-xxx.ts`) |
| `src/test-utils/` | Test helpers (`fake-api.ts`) |

Imports use the `@/` alias, never long relative paths across folders.

---

## 2. The look: "evidence ledger"

The UI is a ledger an analyst marks up: quiet paper and ink, thin rules, and **one** accent used like
a highlighter. Most of the screen is greyscale; colour means something.

- **Paper / Sheet / Ink** carry the UI: page background, cards, text.
- **Marker** (yellow `#f2cc0c`) is the only accent. Use it for: the active step, selection, the
  brand mark, a key figure. Never as text colour on a light background (use `text-marker-ink`),
  never as a large fill, never for decoration.
- **Rules, not shadows.** Separate things with `border` / `divide-y`. Shadows only on things that
  float above the page (dialogs, the mobile drawer, menus).
- **Small, square-ish corners.** `--radius` is `0.25rem`; cards and inputs use `rounded-sm`.
- **Dense, calm, readable.** Body text is `text-sm`, secondary text `text-xs text-muted-foreground`.
- **Figures line up.** Tabular numerals are on globally (`font-feature-settings: "tnum"`); keep
  numbers in plain text so they stay aligned.

---

## 3. Colour tokens

All colours come from CSS variables in `src/app/globals.css`, defined for light (`:root`) and dark
(`.dark`), and exposed to Tailwind in `@theme inline`. **Components never contain hex values or
Tailwind palette colours** (`bg-yellow-400`, `text-gray-500`, `bg-white`, `text-black`). Two
deliberate exceptions: the `bg-black/40` backdrop of the mobile drawer, and `bg-white` behind chart
images (`artifact-panel.tsx`), because sandbox charts are drawn for a white page and can have a
transparent background that would be unreadable on the dark theme.

| Purpose | Tailwind class | Notes |
|---|---|---|
| Page background / text | `bg-background` / `text-foreground` | Paper / Ink |
| Raised surface (card, panel) | `bg-card` + `border` | Sheet |
| Quiet fill (hover, tags, code) | `bg-muted`, `hover:bg-muted/60` | |
| Secondary text | `text-muted-foreground` | Graphite |
| Lines | `border`, `border-b`, `divide-y` | `--border` is set as the default border colour |
| Primary action | `Button` default variant | Ink fill, paper text |
| Accent | `bg-marker`, `text-marker-ink`, class `marked` | Sparingly (see section 2) |
| Error | `text-destructive`, `Button variant="destructive"` | |
| Success | `text-ok` | |
| Sidebar | `bg-sidebar`, `text-sidebar-foreground`, `bg-sidebar-accent` | |
| Charts | `--chart-1` … `--chart-5` | Greyscale ramp, `chart-5` is the marker for the highlighted series |
| Focus ring | automatic (`:focus-visible` uses `--ring`) | Don't remove outlines |

**Adding a token:** add the raw value to both `:root` and `.dark`, map it in `@theme inline`
(`--color-name: var(--name);`), check contrast in both themes (text ≥ 4.5:1, UI lines and icons
≥ 3:1), then use the Tailwind class. Prefer an existing token first.

---

## 4. Typography

- **Fonts:** Geist (`font-sans`, default) and Geist Mono (`font-mono`), loaded with `next/font` in
  `layout.tsx`. No other fonts.
- **Mono** is for SQL, code, file names, IDs and numbers shown as data.

| Use | Classes |
|---|---|
| Page title (empty state only, one per screen) | `text-3xl font-semibold tracking-tight text-balance max-w-[22ch]` |
| Lead paragraph | `leading-7 text-muted-foreground max-w-[58ch]` |
| Section / panel heading | `text-sm font-semibold` (`h2`) or `text-sm font-medium` (`h3`) |
| Body | `text-sm` (example-question list uses `text-[15px] leading-6`) |
| Secondary / meta | `text-xs text-muted-foreground` |
| Brand mark | `marked font-semibold tracking-tight` |
| Code | `font-mono text-xs leading-5` |

Headings inside the model's answer get one fixed scale from the `.answer` rules in `globals.css`,
whatever level the model used. Wrap rendered answers in `.answer`; don't restyle them per component.

Keep line length readable: prose `max-w-[58ch]`, the conversation column `max-w-[46rem]`.

---

## 5. Layout and spacing

- **App shell:** `flex h-dvh w-full overflow-hidden`; sidebar `w-72 shrink-0 border-r` from `md:`
  up; below `md` the sidebar is a drawer (`fixed inset-0 z-40`, `role="dialog" aria-modal="true"`,
  panel `w-[85%] max-w-xs shadow-lg`, backdrop button that closes it).
- **Content column:** `mx-auto w-full max-w-[46rem] px-5`, vertical rhythm `py-8 md:py-12`.
- **Spacing:** Tailwind's scale, mostly `gap-1.5 … gap-4`, `p-3` inside cards, `px-4 py-2` for list
  rows. Prefer `grid gap-*` / `flex gap-*` over margins between siblings.
- **Scroll areas:** a flex child that scrolls needs `min-h-0` (and `min-w-0` for horizontal
  content), otherwise it pushes the page.
- **Mobile is required, not optional:** works at 360px wide, no horizontal page scroll (the e2e smoke
  test checks this), long SQL wraps (`wrap-code`), images fit their panel, tap targets ≥ 24px.

---

## 6. Signature patterns (reuse, don't reinvent)

| Pattern | How | Where |
|---|---|---|
| Highlighted text | `className="marked"` (highlighter behind the lower half) | Brand, "Recorded run", key figures |
| Evidence trail | `<ol className="trail">` with `<li className="relative">` + `<span className="trail-node" data-state=… aria-hidden="true" />` | `assistant-turn.tsx`, `tool-steps.tsx` |
| Trail states | `running` (marker, pulses), `done` (ink), `error` (destructive), `waiting` (marker ring, no pulse: paused for a human), `denied` (dashed, hollow) | Always pair with a `sr-only` label ("In progress: ", "Done: " …) |
| Answer typography | wrapper `className="answer"` | Rendered model output |
| Wrapping code | `className="wrap-code"` | SQL / shell blocks |
| Bordered list | `divide-y border-y`, rows `px-1 py-3 hover:bg-muted/60` | Example questions |
| Card needing attention | `grid gap-3 rounded-sm border border-foreground/40 bg-card p-3` | `approval-card.tsx` |
| Tabs | `role="tablist"`, buttons `-mb-px border-b-2 py-2 text-sm`, active `border-foreground font-medium`, inactive `border-transparent text-muted-foreground hover:text-foreground` | `sidebar.tsx` |
| Row actions | `group relative` row; action `opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 focus-visible:opacity-100` | Thread delete button |

New visual states go into `globals.css` as `data-state` variants of an existing class, not as one-off
utility soup in a component.

---

## 7. Components and buttons

- Use `@/components/ui/*` first: `Button`, `Dialog`, `Input`, `Textarea`, `Select`, `Tooltip`,
  `DropdownMenu`, `Badge`, `Card`, `Collapsible`, `ScrollArea`, `Separator`, `Spinner`.
- Need another primitive? `npx shadcn@latest add <name>` (it reads `components.json`), then prune
  what is unused.
- **Button variants:** `default` = the one primary action in a view; `outline` = secondary actions
  ("New question"); `ghost` = toolbar and icon buttons; `destructive` = delete/reject; `link` = inline.
- **Button sizes:** `default` (h-8), `sm`, `xs`, `lg`; icon-only buttons use `icon`, `icon-sm`
  (toolbars) or `icon-xs` (inside rows), and **always** have an `aria-label`.
- Icons inside buttons get `aria-hidden="true"` when there is visible text.
- Dialogs always have `DialogTitle` and `DialogDescription` (use `className="sr-only"` if they
  shouldn't be visible).

---

## 8. Dark mode

- The theme is the `dark` class on `<html>`, set before first paint by the inline script in
  `layout.tsx` (stored in `localStorage.theme`, falling back to the system setting). `ThemeToggle`
  switches it.
- Because every colour is a token, components need no `dark:` variants. Use `dark:` only when a
  token cannot express the difference (vendored components do this).
- **Check every change in both themes** before calling it done.

---

## 9. Component code conventions

- `"use client"` at the top of interactive components (most of `components/app/`).
- Props: a named `interface XxxProps` (or an inline type for 1–3 props), documented with `/** */`
  when the meaning is not obvious. Callbacks are named `onXxx`.
- State: `useState` / `useCallback` / context. No global state library. Derive values instead of
  storing them.
- Browser APIs (`localStorage`, `sessionStorage`, `history`) are wrapped in `try/catch`: the app
  must still work in private mode or with storage blocked.
- **Data:** all HTTP goes through `src/lib/api.ts` (`request()`), which adds the bearer token, maps
  401 to `AuthRequiredError` and turns failures into readable `ApiError` messages. Components catch
  `AuthRequiredError` and call `signOut()` / ask to sign in again; never `fetch` the API directly
  from a component (except the chat transport, which receives `fetchImpl`).
- New API calls get types in `src/lib/types.ts`.
- **States every view handles:** loading (`role="status"`, `text-sm text-muted-foreground`,
  "Loading…"), empty (one helpful sentence that says what to do next), error (`role="alert"`,
  `text-sm text-destructive`, a message the user can act on).

### Copy

Plain, short sentences that say what happens and why. Examples from the app: "Live questions run real
queries and cost money, so they need a code." · "Delete this conversation and its files? This cannot
be undone." Use sentence case for buttons and headings, an ellipsis character (`…`) for progress
("Checking…"), and no exclamation marks or jargon.

---

## 10. Accessibility checklist

- Real elements: `button` for actions, `a` for navigation, lists for lists, one `h1` per screen.
- Every input has a `<label htmlFor>` (use `useId()` for ids); errors use `aria-invalid` and
  `aria-describedby`.
- Icon-only controls have an `aria-label`; decorative icons and trail nodes are `aria-hidden`.
- Status that changes (running, waiting, failed) is announced with text (`sr-only` or `role="status"`).
- Keyboard: everything reachable and visible on focus (row actions appear on `focus-within`).
- Motion: animations respect `prefers-reduced-motion` (see the `node-pulse` rule).
- Contrast: tokens are checked; don't put marker yellow behind small light text or as text on paper.

---

## 11. Security rules (from `README.md`, non-negotiable)

- No `dangerouslySetInnerHTML` (the theme script in `layout.tsx` is the only exception).
- Model output renders through `streamdown` without raw HTML; no math/mermaid plugins.
- Sandbox output goes in a plain `<pre>` with ANSI codes stripped.
- Artifacts are fetched with the bearer token and shown from blob URLs (revoke them when done).
- Only `NEXT_PUBLIC_*` values reach the browser; no secrets in `web/`.
- New dependencies: check what they do with untrusted input before adding them.

---

## 12. Tests and checks

- **Component tests** (Vitest + Testing Library) live in `__tests__/` next to the code. Render the
  real component with `createFakeApi()` from `@/test-utils/fake-api`, drive it with `userEvent`, and
  query by role and label (`getByRole("button", { name: /…/i })`, `getByLabelText`). Use
  `data-testid` only where no accessible query exists.
- **Logic** in `src/lib/` gets plain unit tests (`src/lib/__tests__/`).
- **Protocol:** `contract.test.ts` checks the backend's stream chunks; keep it passing.
- **Real browser:** `node e2e/smoke.mjs` (against `e2e/mock-api.mjs` without a model) for layout,
  console errors and phone-width overflow.

Done means all of these pass:

```bash
npm run lint && npm run typecheck && npm test && npm run build
```

---

## 13. Before you finish a frontend change

- [ ] Only tokens and existing patterns used; no hex or palette colours in components
- [ ] Looks right in light **and** dark
- [ ] Works at phone width with no horizontal scroll
- [ ] Loading, empty and error states handled with the right roles
- [ ] Keyboard and screen-reader basics from section 10
- [ ] Security rules from section 11
- [ ] Tests added or updated; the check command passes
- [ ] This file updated if you added a token, a pattern or a convention
