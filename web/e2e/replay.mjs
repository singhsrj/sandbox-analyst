// Real-browser check of replay mode (no access code, no model tokens).
// Run with the API and web app running: node e2e/replay.mjs
import { mkdirSync } from "node:fs";
import path from "node:path";
import { chromium } from "playwright-core";

const WEB_URL = process.env.WEB_URL ?? "http://localhost:3100";
const SHOTS = path.join(import.meta.dirname, "screenshots");
mkdirSync(SHOTS, { recursive: true });

const problems = [];
const browser = await chromium.launch({ channel: "chrome", headless: true });
const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
page.on("console", (m) => m.type() === "error" && problems.push(`console: ${m.text().slice(0, 200)}`));
page.on("pageerror", (e) => problems.push(`pageerror: ${String(e).slice(0, 200)}`));
const shot = (name) => page.screenshot({ path: path.join(SHOTS, `${name}.png`) });

try {
  await page.goto(WEB_URL);
  const list = page.getByRole("list", { name: /recorded runs/i });
  await list.waitFor({ timeout: 30_000 });
  await page.getByRole("heading", { name: /watch a recorded run/i }).scrollIntoViewIfNeeded();
  await shot("r1-start-page");

  await list.getByRole("button").first().click();
  await page.getByTestId("replay-banner").waitFor();
  await page.getByTestId("answer").waitFor();
  await page.getByTestId("file-card").first().waitFor({ timeout: 30_000 });
  await page.waitForTimeout(1_500);
  await shot("r2-replay-open");
  if (await page.getByLabel("Your question").count()) problems.push("a composer is shown in a recorded run");
  const broken = await page.evaluate(() =>
    [...document.querySelectorAll('[data-testid="file-card"] img')].filter((i) => !i.complete || i.naturalWidth === 0).length,
  );
  if (broken) problems.push(`${broken} chart(s) in the recorded run did not load`);

  // a shared link opens the same recorded run directly
  const url = page.url();
  await page.goto(url);
  await page.getByTestId("replay-banner").waitFor({ timeout: 30_000 });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(600);
  await shot("r3-replay-mobile");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  if (overflow > 1) problems.push(`mobile layout overflows by ${overflow}px`);

  await page.getByRole("button", { name: /ask your own question/i }).click();
  await page.getByLabel("Your question").waitFor();
} catch (error) {
  await shot("r-failure").catch(() => {});
  problems.push(`FAILED: ${String(error).slice(0, 400)}`);
} finally {
  await browser.close();
}
console.log(problems.length ? `PROBLEMS:\n- ${problems.join("\n- ")}` : "OK: replay mode works in a real browser");
process.exit(problems.some((p) => p.startsWith("FAILED")) ? 1 : 0);
