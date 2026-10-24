// Capture every page at desktop and phone widths, light and dark, for visual review.
// Usage: CHROMIUM_PATH=/path/to/chromium node scripts/screenshots.mjs [outDir] [baseUrl]
import { mkdir } from "node:fs/promises";
import { chromium } from "@playwright/test";

const outDir = process.argv[2] ?? "screenshots";
const base = process.argv[3] ?? "http://localhost:4173";
const pages = [
  ["overview", "/"],
  ["model-credit", "/models/credit-risk"],
  ["model-fraud", "/models/fraud-screen"],
  ["inputs-claims", "/models/claims-triage/inputs"],
  ["incident-credit", "/incidents/credit-risk-1"],
  ["incident-fraud", "/incidents/fraud-screen-1"],
  ["incident-claims", "/incidents/claims-triage-1"],
  ["incidents", "/incidents"],
  ["missing-model", "/models/does-not-exist"],
];
const views = [
  ["desktop", { width: 1360, height: 900 }],
  ["phone", { width: 390, height: 844 }],
];

const executablePath = process.env.CHROMIUM_PATH;
const browser = await chromium.launch({
  ...(executablePath ? { executablePath } : {}),
  args: ["--no-sandbox", "--disable-gpu"],
});
await mkdir(outDir, { recursive: true });

for (const scheme of ["light", "dark"]) {
  for (const [view, viewport] of views) {
    const context = await browser.newContext({ viewport, colorScheme: scheme, reducedMotion: "reduce" });
    const page = await context.newPage();
    for (const [name, path] of pages) {
      if (scheme === "dark" && !["overview", "model-credit", "incident-credit"].includes(name)) continue;
      await page.goto(base + path, { waitUntil: "networkidle" });
      await page.waitForTimeout(200);
      await page.screenshot({ path: `${outDir}/${name}-${view}-${scheme}.png`, fullPage: true });
    }
    await context.close();
  }
}
await browser.close();
console.log(`saved to ${outDir}`);
