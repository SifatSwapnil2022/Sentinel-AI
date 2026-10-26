import { describe, expect, it } from "vitest";
import type { DailyRow } from "../data/schema";
import { combine, MEASURES, pivot } from "./explore";

function row(patch: Partial<DailyRow>): DailyRow {
  return {
    modelId: "a",
    team: "T",
    date: "2026-10-01",
    rows: 100,
    estimate: 0.8,
    lower: 0.78,
    upper: 0.82,
    reference: 0.85,
    measured: null,
    labelCoverage: 0.2,
    p95LatencyMs: 50,
    driftedFeatures: 0,
    totalFeatures: 4,
    multivariateDrifted: false,
    conceptFlag: null,
    missingJump: 0,
    ...patch,
  };
}

const measure = (id: string) => {
  const m = MEASURES.find((x) => x.id === id);
  if (!m) throw new Error(id);
  return m;
};

describe("combine", () => {
  it("weights rates by prediction volume", () => {
    const rows = [row({ estimate: 0.9, rows: 300 }), row({ estimate: 0.5, rows: 100 })];
    expect(combine(rows, measure("estimate"))).toBeCloseTo(0.8);
  });

  it("sums counts and takes the worst for missing values", () => {
    const rows = [row({ rows: 10, missingJump: 0.02 }), row({ rows: 5, missingJump: 0.3 })];
    expect(combine(rows, measure("predictions"))).toBe(15);
    expect(combine(rows, measure("missing"))).toBe(0.3);
  });

  it("returns null when nothing qualifies", () => {
    expect(combine([row({ labelCoverage: 0.1, measured: 0.7 })], measure("measured"))).toBeNull();
    expect(combine([], measure("predictions"))).toBeNull();
  });
});

describe("pivot", () => {
  const dates = ["2026-10-01", "2026-10-02"];
  const rows = [
    row({ modelId: "b", team: "T", date: "2026-10-01", rows: 10 }),
    row({ modelId: "a", team: "T", date: "2026-10-01", rows: 20 }),
    row({ modelId: "a", team: "U", date: "2026-10-02", rows: 30 }),
  ];

  it("makes one aligned series per group, sorted by id", () => {
    const groups = pivot(rows, measure("predictions"), "model", dates);
    expect(groups.map((g) => g.id)).toEqual(["a", "b"]);
    expect(groups[0]?.values).toEqual([20, 30]);
    expect(groups[1]?.values).toEqual([10, null]);
    expect(groups[0]?.total).toBe(50);
  });

  it("rolls everything into one series for the fleet", () => {
    const [fleet] = pivot(rows, measure("predictions"), "fleet", dates);
    expect(fleet?.values).toEqual([30, 30]);
  });
});
