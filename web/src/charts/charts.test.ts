import { modelSchema, type ModelSummary } from "../data/schema";
import { accuracyDomain } from "../pages/FleetPage";
import { latestTrustworthy } from "../pages/ModelPage";
import { fixture } from "../test/render";
import { MIN_COVERAGE_FOR_MEASURED, toPoints } from "./AccuracyChart";
import { driftScore } from "./DriftSpark";

const model = modelSchema.parse(fixture("models/credit-risk.json"));

describe("toPoints", () => {
  it("only shows measured values once enough labels are in", () => {
    const points = toPoints(model.days, "accuracy");
    points.forEach((p, i) => {
      const day = model.days[i];
      if (!day) throw new Error("index out of range");
      if (day.labelCoverage < MIN_COVERAGE_FOR_MEASURED) expect(p.measured).toBeNull();
      else expect(p.measured).toBe(day.measured?.accuracy ?? null);
    });
    expect(points.at(-1)?.measured).toBeNull(); // today has no labels
  });

  it("switches metric", () => {
    const precision = toPoints(model.days, "precision");
    expect(precision[0]?.value).toBe(model.days[0]?.estimate.precision.value);
  });
});

describe("driftScore", () => {
  it("puts the threshold at 1 for both kinds of statistic", () => {
    expect(driftScore(0.1, 0.1, false)).toBe(1);
    expect(driftScore(0.05, 0.05, true)).toBe(1);
  });
  it("grows with drift: bigger distances, smaller p-values", () => {
    expect(driftScore(0.2, 0.1, false)).toBe(2);
    expect(driftScore(0.025, 0.05, true)).toBe(2);
  });
  it("is capped and survives p = 0", () => {
    expect(driftScore(5, 0.1, false)).toBe(3);
    expect(driftScore(0, 0.05, true)).toBe(3);
  });
});

it("accuracyDomain pads, snaps to 5 points and stays inside [0, 1]", () => {
  const m = (lower: number, upper: number, reference: number) =>
    ({ estimate: { value: (lower + upper) / 2, lower, upper }, referenceAccuracy: reference }) as ModelSummary;
  expect(accuracyDomain([m(0.68, 0.77, 0.73), m(0.77, 0.81, 0.89)])).toEqual([0.65, 0.9]);
  expect(accuracyDomain([m(0.001, 0.02, 0.01), m(0.97, 0.995, 0.99)])).toEqual([0, 1]);
  expect(accuracyDomain([])).toEqual([0.5, 1]);
});

it("latestTrustworthy picks the newest day with half its labels in", () => {
  const day = latestTrustworthy(model.days);
  expect(day?.labelCoverage).toBeGreaterThanOrEqual(0.5);
  const later = model.days.filter((d) => d.date > (day?.date ?? ""));
  expect(later.every((d) => d.labelCoverage < 0.5 || d.measured === null)).toBe(true);
});
