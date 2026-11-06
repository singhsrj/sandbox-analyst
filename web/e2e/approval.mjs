// Real-browser test of human approval against the LIVE stack (API + web). Costs model tokens.
// Run: node e2e/approval.mjs   (same env as smoke.mjs)
//
// Strict mode -> the first query pauses -> RELOAD the page (the paused run must come back from the
// database) -> approve every card -> the answer arrives and the trail shows the approved query.
import { mkdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { chromium } from "playwright-core";

const WEB_URL = process.env.WEB_URL ?? "http://localhost:3100";
const SHOTS = path.join(import.meta.dirname, "screenshots");
mkdirSync(SHOTS, { recursive: true });

function accessCode() {
  if (process.env.ACCESS_CODE) return process.env.ACCESS_CODE;
  const env = readFileSync(path.join(import.meta.dirname, "..", "..", ".env"), "utf-8");
  const line = env.split(/\r?\n/).find((l) => l.startsWith("DEMO_ACCESS_CODE="));
  return line.slice("DEMO_ACCESS_CODE=".length).replace(/\s+#.*$/, "").replace(/^["']|["']$/g, "").trim();
}

const QUESTION = "How many orders were cancelled in 2025? Use one SQL query and answer in one sentence.";

const problems = [];
const browser = await chromium.launch({ channel: "chrome", headless: true });
const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
page.on("console", (m) => m.type() === "error" && problems.push(`console: ${m.text().slice(0, 200)}`));
page.on("pageerror", (e) => problems.push(`pageerror: ${String(e).slice(0, 200)}`));
const shot = (name) => page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
const card = () => page.getByRole("region", { name: /approval needed/i }).first();

try {
  await page.goto(WEB_URL);
  await page.getByRole("heading", { name: /ask a question about the shop/i }).waitFor({ timeout: 30_000 });
  await page.getByRole("checkbox", { name: /ask me before every query/i }).check();
  const box = page.getByRole("textbox", { name: /your question/i });
  await box.fill(QUESTION);
  await box.press("Enter");
  const dialog = page.getByRole("dialog", { name: /enter the access code/i });
  await dialog.getByLabel("Access code").fill(accessCode());
  await dialog.getByRole("button", { name: /unlock live questions/i }).click();

  await card().waitFor({ timeout: 240_000 });
  await card().scrollIntoViewIfNeeded();
  await shot("a1-approval-card");
  if (!(await page.getByRole("textbox", { name: /your question/i }).isDisabled()))
    problems.push("composer is not locked while a query waits for approval");

  // the paused run must survive a reload (stored run + Postgres checkpoint)
  await page.reload();
  await card().waitFor({ timeout: 30_000 });
  await shot("a2-card-after-reload");

  let approvals = 0;
  while (approvals < 6) {
    const answered = await Promise.race([
      card().waitFor({ timeout: 240_000 }).then(() => "card"),
      page.getByTestId("answer").waitFor({ timeout: 240_000 }).then(() => "answer"),
    ]);
    if (answered === "answer" && !(await card().isVisible().catch(() => false))) break;
    await card().getByRole("button", { name: /^run query$/i }).click();
    approvals += 1;
    await page.waitForTimeout(1_500);
  }
  await page.getByTestId("answer").waitFor({ timeout: 240_000 });
  // wait for the resumed stream to finish (the composer is usable again)
  await page.getByRole("textbox", { name: /your question/i }).and(page.locator(":enabled")).waitFor({ timeout: 120_000 });
  await page.waitForFunction(() => !document.querySelector('[aria-label="Stop"]'), null, { timeout: 120_000 }).catch(() => {});
  await page.waitForTimeout(1_500);
  await shot("a3-answer-after-approval");
  if (await page.getByText(/paused: a query above is waiting/i).count())
    problems.push("the 'paused' note is still shown after the run finished");
  const queries = await page.getByTestId("artifact-panel").innerText().catch(() => "");
  if (/Queries\s*0\b/.test(queries)) problems.push("run details still show the paused run (0 queries)");
  const approvedNotes = await page.getByText(/you approved this query/i).count();
  if (approvedNotes < 1) problems.push("no step shows that the query was approved");
  console.log(`approved ${approvals} card(s); ${approvedNotes} approved step(s) shown`);
  console.log(`answer: ${(await page.getByTestId("answer").innerText()).slice(0, 300)}`);
} catch (error) {
  await shot("a-failure").catch(() => {});
  problems.push(`FAILED: ${String(error).slice(0, 400)}`);
} finally {
  await browser.close();
}

console.log(problems.length ? `PROBLEMS:\n- ${problems.join("\n- ")}` : "OK: approval flow works in a real browser");
process.exit(problems.some((p) => p.startsWith("FAILED")) ? 1 : 0);
