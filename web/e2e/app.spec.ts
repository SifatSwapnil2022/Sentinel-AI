import { readFileSync } from "node:fs";
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

/** The latest estimate's range for a model, as the page prints it ("Likely 73.7 to 79.8%"). */
function likelyRange(modelId: string): string {
  const doc = JSON.parse(readFileSync(`public/data/models/${modelId}.json`, "utf8")) as {
    days: { estimate: { accuracy: { lower: number; upper: number } } }[];
  };
  const latest = doc.days.at(-1)?.estimate.accuracy;
  if (!latest) throw new Error(`no days for ${modelId}`);
  return `Likely ${(latest.lower * 100).toFixed(1)} to ${(latest.upper * 100).toFixed(1)}%`;
}

/** A dashboard tile by its title (wide tables inside share the name, so match the section). */
const tile = (page: Page, name: string) => page.locator("section").filter({ has: page.getByRole("heading", { name, exact: true }) });

const PAGES = [
  ["landing", "/"],
  ["overview", "/overview"],
  ["overview compared", "/overview?compare=previous&period=7"],
  ["models", "/models"],
  ["model", "/models/credit-risk"],
  ["inputs", "/models/fraud-screen?tab=inputs"],
  ["segments", "/models/credit-risk?tab=segments"],
  ["traffic", "/models/fraud-screen?tab=traffic&compare=previous"],
  ["model incidents", "/models/policy-lapse?tab=incidents"],
  ["incident (segment)", "/incidents/credit-risk-1"],
  ["incident (broad)", "/incidents/fraud-screen-1"],
  ["incident (relationships)", "/incidents/claims-triage-1"],
  ["incident (missing values)", "/incidents/upsell-propensity-1"],
  ["incident (resolved)", "/incidents/policy-lapse-1"],
  ["incidents", "/incidents?state=all&period=90"],
  ["explore", "/explore?measure=predictions&by=team&view=bar"],
  ["reports", "/reports"],
] as const;

test.describe("accessibility", () => {
  for (const scheme of ["light", "dark"] as const) {
    for (const [name, path] of PAGES) {
      test(`${name} has no serious violations (${scheme})`, async ({ page }) => {
        await page.addInitScript((t) => localStorage.setItem("sentinel.theme", t), scheme);
        await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
        await page.goto(path);
        await expect(page.locator("main h1")).toBeVisible();
        const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
        const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
        expect(serious.map((v) => `${v.id}: ${v.nodes.length} × ${v.help} (${v.nodes[0]?.target.join(" ")})`)).toEqual([]);
      });
    }
  }
});

test.describe("layout", () => {
  for (const [name, path] of PAGES) {
    test(`${name} never scrolls sideways`, async ({ page }) => {
      await page.goto(path);
      await expect(page.locator("main h1")).toBeVisible();
      await page.waitForTimeout(200);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(0);
    });
  }
});

test("a visitor goes from the landing page to an incident's cause", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/labels arrive late/);
  await page.getByRole("link", { name: "Open the live dashboard" }).click();
  await expect(page).toHaveURL(/\/overview$/);
  await expect(page.getByText(/models need attention/)).toBeVisible();

  await tile(page, "Models").getByRole("link", { name: "credit-risk", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "credit-risk" })).toBeVisible();
  await expect(page.getByText(likelyRange("credit-risk"), { exact: true })).toBeVisible();

  await page.getByRole("link", { name: "Measured accuracy fell outside the estimate" }).click();
  await expect(page).toHaveURL(/\/incidents\/credit-risk-1$/);
  await expect(page.getByText(/concentrated where division = Khulna/)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Example predictions" })).toBeVisible();
});

test("slicers live in the address and follow the visitor between pages", async ({ page, isMobile }) => {
  await page.goto("/overview");
  if (isMobile) await page.getByRole("button", { name: /^Filters/ }).click();
  await page.getByRole("region", { name: "Filters" }).getByRole("button", { name: "7 days", exact: true }).click();
  await expect(page).toHaveURL(/period=7/);
  if (isMobile) await page.getByRole("button", { name: "Menu" }).click();
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Explore" }).click();
  await expect(page).toHaveURL(/\/explore\?period=7/);
  await page.reload();
  await expect(tile(page, "Estimated accuracy by model")).toContainText(/Oct 18 to Oct 24/);
});

test("dragging across the accuracy chart zooms to those dates", async ({ page, isMobile }) => {
  test.skip(isMobile, "dragging is a pointer interaction");
  await page.goto("/models/fraud-screen");
  const frame = page.getByRole("group", { name: /Accuracy over 30 days/ });
  const box = await frame.boundingBox();
  if (!box) throw new Error("chart not rendered");
  await page.mouse.move(box.x + box.width * 0.4, box.y + 120);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.8, box.y + 120, { steps: 6 });
  await page.mouse.up();
  await expect(page).toHaveURL(/from=2026-10-\d\d&to=2026-10-\d\d/);
  const days = await page.getByRole("group", { name: /Accuracy over \d+ days/ }).getAttribute("aria-labelledby");
  expect(days).toBeTruthy();
  await expect(page.getByRole("group", { name: /Accuracy over 30 days/ })).toHaveCount(0);
});

test("a tile downloads its data as CSV", async ({ page }) => {
  await page.goto("/overview");
  const download = page.waitForEvent("download");
  await tile(page, "Models").getByRole("button", { name: "CSV" }).click();
  const file = await download;
  expect(file.suggestedFilename()).toMatch(/^sentinel_models_.*\.csv$/);
  const text = readFileSync(await file.path(), "utf8");
  expect(text.split("\n")[0]).toMatch(/^model,team,/);
  expect(text).toContain("credit-risk");
});

test("the reports page serves the star schema", async ({ page, request }) => {
  await page.goto("/reports");
  const href = await tile(page, "Tables").getByRole("link", { name: "CSV" }).first().getAttribute("href");
  if (!href) throw new Error("no CSV link");
  const csv = await (await request.get(href)).text();
  expect(csv.split("\n")[0]).toBe(
    "model_id,model_name,team,version,description,label_delay_days,reference_rows,reference_accuracy,reference_precision,reference_recall,reference_f1,status,open_incidents",
  );
  for (const file of ["reports/sentinel-powerbi.zip", "reports/sentinel.twbx"]) {
    expect((await request.get(`/${file}`)).status(), file).toBe(200);
  }
});

test("the accuracy chart can be read with the keyboard", async ({ page }) => {
  await page.goto("/models/credit-risk");
  const chart = page.getByRole("group", { name: /Accuracy over 30 days/ });
  await chart.focus();
  await page.keyboard.press("End");
  await expect(page.getByRole("status").filter({ hasText: "Oct 24" })).toBeVisible();
  await page.keyboard.press("ArrowLeft");
  await expect(page.getByRole("status").filter({ hasText: "Oct 23" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("status").filter({ hasText: "Oct 23" })).toHaveCount(0);
});

test("hovering the chart shows that day's values", async ({ page, isMobile }) => {
  test.skip(isMobile, "hover is a pointer interaction");
  await page.goto("/models/fraud-screen");
  const frame = page.getByRole("group", { name: /Accuracy over 30 days/ });
  const box = await frame.boundingBox();
  if (!box) throw new Error("chart not rendered");
  await page.mouse.move(box.x + box.width - 30, box.y + 120);
  const readout = page.getByRole("status").filter({ hasText: "Estimated accuracy" });
  await expect(readout).toContainText("Oct 24");
  await expect(readout).toContainText("Not enough labels");
});

test("the theme choice survives a reload", async ({ page, isMobile }) => {
  await page.goto("/overview");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  if (isMobile) await page.getByRole("button", { name: "Menu" }).click();
  await page.getByRole("combobox", { name: "Colour theme" }).selectOption("light");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
});

test("a missing model explains itself instead of crashing", async ({ page }) => {
  await page.goto("/models/does-not-exist");
  await expect(page.getByRole("heading", { name: "Can't find this model" })).toBeVisible();
  await page.getByRole("link", { name: "Go to overview" }).click();
  await expect(page).toHaveURL(/\/overview$/);
});

test("an unknown address shows the not-found page", async ({ page }) => {
  await page.goto("/nowhere/at/all");
  await expect(page.getByRole("heading", { name: "This page doesn't exist" })).toBeVisible();
});

test("the landing page's examples lead to the cases they describe", async ({ page }) => {
  const fleet = JSON.parse(readFileSync("public/data/fleet.json", "utf8")) as {
    models: { id: string; measured: { value: number } }[];
  };
  const fraud = fleet.models.find((m) => m.id === "fraud-screen");
  if (!fraud) throw new Error("demo has no fraud-screen");

  await page.goto("/");
  const readings = page.getByRole("figure", { name: /a fraud model in the demo/ });
  await expect(readings).toContainText("Labels say");
  await expect(readings).toContainText(`${(fraud.measured.value * 100).toFixed(1)}%`);

  const approach = page.locator("#approach");
  await approach.getByRole("link", { name: "See the incident" }).first().click();
  await expect(page).toHaveURL(/\/incidents\/credit-risk-1$/);
  await expect(page.getByText(/concentrated where division = Khulna/)).toBeVisible();
});

test("section links scroll to their sections", async ({ page, isMobile }) => {
  test.skip(isMobile, "section links are hidden on phones");
  await page.goto("/");
  await page.getByRole("navigation", { name: "Sections" }).getByRole("link", { name: "Testing" }).click();
  await expect(page).toHaveURL(/#evidence$/);
  await expect(page.getByRole("heading", { name: "How it's tested" })).toBeInViewport();
});
