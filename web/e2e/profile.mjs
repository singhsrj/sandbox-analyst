// Real-browser check of the data profile panel: public, no model, no sign-in.
//   node e2e/mock-api.mjs 8010   and   NEXT_PUBLIC_API_BASE_URL=http://localhost:8010 npx next dev -p 3100
//   node e2e/profile.mjs          (WEB_URL defaults to http://localhost:3100)
// Checks: opens beside the chat, every section renders, dividers drag, light and dark themes,
// phone width opens it full screen with no horizontal scroll, the cross closes it.
import { mkdirSync } from "node:fs";
import path from "node:path";
import { chromium } from "playwright-core";

const WEB_URL = process.env.WEB_URL ?? "http://localhost:3100";
const SHOTS = path.join(import.meta.dirname, "screenshots");
mkdirSync(SHOTS, { recursive: true });

const problems = [];
const browser = await chromium.launch({ channel: "chrome", headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await context.newPage();
page.on("console", (m) => m.type() === "error" && problems.push(`console: ${m.text().slice(0, 200)}`));
page.on("pageerror", (e) => problems.push(`pageerror: ${String(e).slice(0, 200)}`));
page.on("response", (r) => r.status() >= 400 && problems.push(`http ${r.status()}: ${r.url().slice(0, 120)}`));
const shot = (name) => page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
const overflow = () => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);

try {
  await page.goto(`${WEB_URL}/app`);
  await page.getByRole("heading", { name: /ask a question about the shop/i }).waitFor({ timeout: 60_000 });
  await page.getByRole("button", { name: /data profile/i }).click();
  const panel = page.getByRole("region", { name: /data profile/i });
  await panel.getByText(/written by/i).waitFor({ timeout: 15_000 });
  for (const name of [/entity relationship diagram/i]) await panel.getByRole("img", { name }).waitFor();
  for (const name of [/columns of order_items/i, /outliers per numeric column/i])
    await panel.getByRole("table", { name }).waitFor();
  await shot("p01-profile-light");

  // the chat is still there and usable
  await page.getByRole("textbox", { name: /your question/i }).fill("Which category returns most?");

  // drag the divider between the profile and the chat 200px to the right
  const handles = page.locator('[data-slot="resizable-handle"]');
  if ((await handles.count()) !== 2) problems.push(`expected 2 dividers, found ${await handles.count()}`);
  const before = (await panel.boundingBox()).width;
  const box = await handles.nth(1).boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + 300);
  await page.mouse.down();
  await page.mouse.move(box.x + 200, box.y + 300, { steps: 8 });
  await page.mouse.up();
  const after = (await panel.boundingBox()).width;
  if (after - before < 150) problems.push(`dragging the divider did not widen the panel (${before} -> ${after})`);

  // table details and the rest of the sections, scrolled into view
  await panel.getByRole("button", { name: "orders", exact: true }).click();
  await panel.getByRole("table", { name: /columns of orders/i }).waitFor();
  await panel.getByRole("button", { name: "Distributions" }).click();
  await page.waitForTimeout(800);
  await shot("p02-distributions-light");
  await panel.getByRole("button", { name: "Correlations" }).click();
  await page.waitForTimeout(800);
  await shot("p03-correlations-light");

  // dark theme
  await page.evaluate(() => document.documentElement.classList.add("dark"));
  await panel.getByRole("button", { name: "Summary" }).click();
  await page.waitForTimeout(800);
  await shot("p04-profile-dark");
  await panel.getByRole("button", { name: "ER diagram" }).click();
  await page.waitForTimeout(800);
  await shot("p05-er-dark");
  await page.evaluate(() => document.documentElement.classList.remove("dark"));

  // widths are remembered after a reload
  await page.reload();
  await page.getByRole("button", { name: /data profile/i }).click();
  await panel.getByText(/written by/i).waitFor({ timeout: 15_000 });
  const reloaded = (await panel.boundingBox()).width;
  if (Math.abs(reloaded - after) > 8) problems.push(`panel width not remembered (${after} -> ${reloaded})`);

  await panel.getByRole("button", { name: /close data profile/i }).click();
  if (await panel.count()) problems.push("the cross did not close the panel");

  // phone: full screen, no horizontal scroll, cross closes it
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(400);
  await page.getByRole("button", { name: /open menu/i }).click();
  await page.getByRole("button", { name: /data profile/i }).click();
  await panel.getByText(/written by/i).waitFor({ timeout: 15_000 });
  await shot("p06-mobile");
  const o = await overflow();
  if (o > 1) problems.push(`phone layout overflows by ${o}px`);
  await panel.getByRole("button", { name: /close data profile/i }).click();
  await page.getByRole("heading", { name: /ask a question about the shop/i }).waitFor();
} catch (error) {
  await shot("pz-failure").catch(() => {});
  problems.push(`FAILED: ${String(error).slice(0, 400)}`);
} finally {
  await browser.close();
}

console.log(problems.length ? `PROBLEMS:\n- ${problems.join("\n- ")}` : "OK: data profile works in a real browser");
process.exit(problems.length ? 1 : 0);
