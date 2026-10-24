import { readFileSync } from "node:fs";
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

/** The latest estimate's range for a model, as the page prints it ("Likely 73.7 to 79.8%"). */
function likelyRange(modelId: string): string {
  const doc = JSON.parse(readFileSync(`public/data/models/${modelId}.json`, "utf8")) as {
    days: { estimate: { accuracy: { lower: number; upper: number } } }[];
  };
  const latest = doc.days.at(-1)?.estimate.accuracy;
  if (!latest) throw new Error(`no days for ${modelId}`);
  return `Likely ${(latest.lower * 100).toFixed(1)} to ${(latest.upper * 100).toFixed(1)}%`;
}

const PAGES = [
  ["overview", "/"],
  ["model", "/models/credit-risk"],
  ["inputs", "/models/fraud-screen/inputs"],
  ["incident (segment)", "/incidents/credit-risk-1"],
  ["incident (broad)", "/incidents/fraud-screen-1"],
  ["incident (relationships)", "/incidents/claims-triage-1"],
  ["incidents", "/incidents"],
] as const;

test.describe("accessibility", () => {
  for (const scheme of ["light", "dark"] as const) {
    for (const [name, path] of PAGES) {
      test(`${name} has no serious violations (${scheme})`, async ({ page }) => {
        await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
        await page.goto(path);
        await expect(page.locator("main h1")).toBeVisible();
        const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
        const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
        expect(serious.map((v) => `${v.id}: ${v.nodes.length} × ${v.help}`)).toEqual([]);
      });
    }
  }
});

test.describe("layout", () => {
  for (const [name, path] of PAGES) {
    test(`${name} never scrolls sideways`, async ({ page }) => {
      await page.goto(path);
      await expect(page.locator("main h1")).toBeVisible();
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(0);
    });
  }
});

test("an engineer follows an alert from the overview to its cause", async ({ page, isMobile }) => {
  await page.goto("/");
  await expect(page.getByText("Three of four models need attention")).toBeVisible();

  if (isMobile) await page.getByRole("button", { name: "Menu" }).click();
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: /credit-risk/ }).click();
  await expect(page.getByRole("heading", { level: 1, name: "credit-risk" })).toBeVisible();
  await expect(page.getByText(likelyRange("credit-risk"), { exact: true })).toBeVisible();

  await page.getByRole("link", { name: "Measured accuracy fell outside the estimate" }).click();
  await expect(page).toHaveURL(/\/incidents\/credit-risk-1$/);
  await expect(page.getByText(/concentrated where division = Khulna/)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Example predictions" })).toBeVisible();
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
  await page.goto("/");
  if (isMobile) await page.getByRole("button", { name: "Menu" }).click();
  await page.getByRole("radio", { name: "Dark" }).check();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test("a missing model explains itself instead of crashing", async ({ page }) => {
  await page.goto("/models/does-not-exist");
  await expect(page.getByRole("heading", { name: "Can't find this model" })).toBeVisible();
  await page.getByRole("link", { name: "Go to overview" }).click();
  await expect(page).toHaveURL(/\/$/);
});

test("an unknown address shows the not-found page", async ({ page }) => {
  await page.goto("/nowhere/at/all");
  await expect(page.getByRole("heading", { name: "This page doesn't exist" })).toBeVisible();
});
