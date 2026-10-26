import { fleetSchema, incidentSchema } from "../data/schema";
import { fixture } from "../test/render";
import { brokenLink, hiddenSegment, labelGap, quietModels } from "./story";

const fleet = fleetSchema.parse(fixture("fleet.json"));
const incident = (id: string) => incidentSchema.parse(fixture(`alerts/${id}.json`));

describe("labelGap", () => {
  it("pairs the last trustworthy measurement with today's estimate", () => {
    const gap = labelGap(fleet, 45, "fraud-screen");
    const summary = fleet.models.find((m) => m.id === "fraud-screen");
    expect(gap).not.toBeNull();
    expect(gap?.measured).toBe(summary?.measured.value);
    expect(gap?.estimate).toBe(summary?.estimate.value);
    expect(gap?.flaggedOn).toBe("2026-10-13");
    expect(gap?.labelsCompleteOn).toBe("2026-11-27"); // 45 days later
    expect(gap && gap.measured - gap.estimate).toBeGreaterThan(0.05);
  });

  it("is absent for a model without an estimate-drop alert or a measurement", () => {
    expect(labelGap(fleet, 30, "churn-predictor")).toBeNull();
    expect(labelGap(fleet, 30, "nope")).toBeNull();
    const unmeasured = {
      ...fleet,
      models: fleet.models.map((m) => ({ ...m, measured: { ...m.measured, value: null } })),
    };
    expect(labelGap(unmeasured, 45, "fraud-screen")).toBeNull();
  });

  it("counts days across month ends in UTC", () => {
    const late = {
      ...fleet,
      alerts: fleet.alerts.map((a) => (a.modelId === "fraud-screen" ? { ...a, openedOn: "2026-12-20" } : a)),
    };
    expect(labelGap(late, 45, "fraud-screen")?.labelsCompleteOn).toBe("2027-02-03");
  });
});

describe("hiddenSegment", () => {
  it("contrasts the overall drop with the worst segment's", () => {
    const s = hiddenSegment(incident("credit-risk-1"));
    expect(s?.conditions).toEqual([{ feature: "division", value: "Khulna" }]);
    expect(s && s.segmentDrop).toBeGreaterThan(3 * (s?.overallDrop ?? 1));
  });

  it("is absent when no segment stands out", () => {
    expect(hiddenSegment(incident("fraud-screen-1"))).toBeNull();
  });
});

describe("brokenLink", () => {
  it("reports the largest correlation change", () => {
    const l = brokenLink(incident("claims-triage-1"));
    expect(l?.a).toBe("policy_value_bdt");
    expect(l && l.before - l.after).toBeGreaterThan(0.5);
    expect(brokenLink(incident("credit-risk-1"))).toBeNull();
  });
});

it("quietModels lists healthy models", () => {
  expect(quietModels(fleet)).toEqual(["churn-predictor"]);
});
