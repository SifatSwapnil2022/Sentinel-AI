import { dailySchema, fleetSchema } from "../data/schema";
import { dateRange, EMPTY, previousRange } from "../filters/filters";
import { fixture } from "../test/render";
import { change, datesIn, fleetKpis, gapColor, incidentsIn, rowsIn } from "./fleetStats";

const daily = dailySchema.parse(fixture("fleet-daily.json"));
const fleet = fleetSchema.parse(fixture("fleet.json"));
const all = new Set(fleet.models.map((m) => m.id));
const range = dateRange(EMPTY, fleet.today);

describe("fleetKpis", () => {
  const current = rowsIn(daily.rows, all, range);
  const previous = rowsIn(daily.rows, all, previousRange(range));
  const kpis = fleetKpis(current, previous, datesIn(range));

  it("sums predictions over models and days", () => {
    expect(current).toHaveLength(fleet.models.length * 30);
    expect(kpis.predictions.value).toBe(current.reduce((t, r) => t + r.rows, 0));
    expect(kpis.predictions.series).toHaveLength(30);
  });

  it("weights accuracy gaps by traffic", () => {
    const manual =
      current.reduce((t, r) => t + (r.estimate - (r.reference ?? 0)) * r.rows, 0) /
      current.reduce((t, r) => t + r.rows, 0);
    expect(kpis.gap.value).toBeCloseTo(manual, 10);
    // the demo's injected problems pull the fleet below reference this month
    expect(change(kpis.gap)).toBeLessThan(0);
  });

  it("counts drift days, and is empty without rows", () => {
    expect(kpis.driftDays.value).toBeGreaterThan(0);
    const none = fleetKpis([], [], []);
    expect(none.predictions.value).toBeNull();
    expect(change(none.gap)).toBeNull();
  });
});

describe("filters narrow the rows", () => {
  it("keeps only the selected models and dates", () => {
    const one = rowsIn(daily.rows, new Set(["churn-predictor"]), dateRange({ ...EMPTY, period: 7 }, fleet.today));
    expect(one).toHaveLength(7);
    expect(new Set(one.map((r) => r.modelId))).toEqual(new Set(["churn-predictor"]));
  });
});

describe("incidentsIn", () => {
  const history = [...fleet.alerts, ...fleet.resolved];

  it("includes incidents that overlap the range, open or resolved", () => {
    const ninety = dateRange({ ...EMPTY, period: 90 }, fleet.today);
    const ids = incidentsIn(history, all, ninety).map((i) => i.id);
    expect(ids).toContain("policy-lapse-1");
    expect(ids).toContain("credit-risk-1");
  });

  it("leaves out incidents resolved before the range", () => {
    const week = dateRange({ ...EMPTY, period: 7 }, fleet.today);
    expect(incidentsIn(history, all, week).map((i) => i.id)).not.toContain("policy-lapse-1");
  });
});

it("gapColor bins worse in red and better in blue", () => {
  expect(gapColor(-0.08)).toBe("var(--div-neg-3)");
  expect(gapColor(-0.03)).toBe("var(--div-neg-2)");
  expect(gapColor(0)).toBe("var(--div-mid)");
  expect(gapColor(0.01)).toBe("var(--div-pos-1)");
  expect(gapColor(0.2)).toBe("var(--div-pos-2)");
});

it("datesIn lists every day", () => {
  expect(datesIn({ from: "2026-09-29", to: "2026-10-02", days: 4 })).toEqual([
    "2026-09-29",
    "2026-09-30",
    "2026-10-01",
    "2026-10-02",
  ]);
});
