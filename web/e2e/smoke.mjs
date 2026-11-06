// Real-browser smoke test against the running stack (API + web). Not part of CI: it needs live
// credentials and costs model tokens. Run: node e2e/smoke.mjs  (see web/e2e/README.md)
//
//   WEB_URL   default http://localhost:3100
//   ACCESS_CODE read from ../.env (DEMO_ACCESS_CODE) unless set
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

const QUESTION =
  "Which region had the lowest revenue in March 2025? Save a bar chart of March 2025 revenue by region as regions.png under /home/user/outputs/. Be brief.";

const problems = [];
const browser = await chromium.launch({ channel: "chrome", headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await context.newPage();
page.on("console", (m) => m.type() === "error" && problems.push(`console: ${m.text().slice(0, 200)}`));
page.on("pageerror", (e) => problems.push(`pageerror: ${String(e).slice(0, 200)}`));
page.on("requestfailed", (r) => problems.push(`requestfailed: ${r.url().slice(0, 100)} ${r.failure()?.errorText}`));

const shot = (name) => page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: false });

try {
  await page.goto(WEB_URL);
  await page.getByRole("heading", { name: /ask a question about the shop/i }).waitFor({ timeout: 30_000 });
  await page.getByRole("list", { name: /example questions/i }).getByRole("button").first().waitFor();
  await shot("01-empty-light");

  // schema browser works without signing in
  await page.getByRole("tab", { name: /the data/i }).click();
  await page.getByText("orders", { exact: true }).first().waitFor({ timeout: 15_000 });
  await page.locator("summary", { hasText: "orders" }).first().click();
  await shot("02-schema");
  await page.getByRole("tab", { name: /history/i }).click();

  // ask while signed out -> access dialog
  await page.getByRole("textbox", { name: /your question/i }).fill(QUESTION);
  await page.getByRole("textbox", { name: /your question/i }).press("Enter");
  const dialog = page.getByRole("dialog", { name: /enter the access code/i });
  await dialog.waitFor();
  await shot("03-access-dialog");
  await dialog.getByLabel("Access code").fill(accessCode());
  await dialog.getByRole("button", { name: /unlock live questions/i }).click();

  // the waiting question is sent automatically; watch the trail build
  await page.getByTestId("assistant-turn").waitFor({ timeout: 60_000 });
  await page.waitForTimeout(3_000);
  await shot("04-working");
  await page.getByTestId("answer").waitFor({ timeout: 240_000 });
  await page.getByTestId("artifact-panel").waitFor({ timeout: 30_000 });
  await page.getByTestId("file-card").first().waitFor({ timeout: 30_000 });
  await page.waitForTimeout(1_500);
  await shot("05-answer-light");

  // regression guard: file cards must show their full content, never be cropped by the layout
  const cropped = await page.evaluate(() =>
    [...document.querySelectorAll('[data-testid="file-card"] img')].filter(
      (img) => img.naturalHeight > 0 && Math.abs(img.getBoundingClientRect().height - (img.naturalHeight * img.getBoundingClientRect().width) / img.naturalWidth) > 2 ||
        img.closest('[data-testid="file-card"]').getBoundingClientRect().height < img.getBoundingClientRect().height,
    ).length,
  );
  if (cropped > 0) problems.push(`${cropped} chart preview(s) are cropped by the files panel`);

  // scroll back to the top of the turn: the question and the evidence trail
  await page.getByRole("heading", { level: 2 }).first().scrollIntoViewIfNeeded();
  await page.evaluate(() => document.querySelector('[role="log"]')?.scrollTo({ top: 0 }));
  await page.waitForTimeout(500);
  await shot("05b-trail-top");

  // open the first SQL step to see the query and the result preview
  const sqlStep = page.getByTestId("step-sql").first();
  await sqlStep.getByRole("button").first().click();
  await page.waitForTimeout(800);
  await sqlStep.scrollIntoViewIfNeeded();
  await shot("06-sql-step-open");

  // dark theme
  await page.getByRole("button", { name: /switch to dark theme/i }).first().click();
  await page.waitForTimeout(500);
  await shot("07-answer-dark");

  // history lists this conversation; reloading the URL reopens it
  await page.getByRole("button", { name: /which region had the lowest revenue/i }).first().waitFor({ timeout: 15_000 });
  await page.reload();
  await page.getByRole("heading", { level: 2, name: /which region had the lowest revenue/i }).waitFor({ timeout: 30_000 });
  await page.getByTestId("answer").waitFor();
  await shot("08-reopened-from-history");

  // phone layout
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(600);
  await shot("09-mobile");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  if (overflow > 1) problems.push(`mobile layout overflows the screen by ${overflow}px`);
  await page.getByRole("button", { name: /open menu/i }).click();
  await page.waitForTimeout(400);
  await shot("10-mobile-menu");
} catch (error) {
  await shot("zz-failure").catch(() => {});
  problems.push(`FAILED: ${String(error).slice(0, 400)}`);
} finally {
  await browser.close();
}

console.log(problems.length ? `PROBLEMS:\n- ${problems.join("\n- ")}` : "OK: no console errors or failed requests");
process.exit(problems.some((p) => p.startsWith("FAILED")) ? 1 : 0);
