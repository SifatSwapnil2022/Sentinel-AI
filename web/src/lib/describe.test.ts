import { incidentSchema } from "../data/schema";
import { fixture } from "../test/render";
import { conditionText, fleetSentence, summarize } from "./describe";

const incident = (id: string) => incidentSchema.parse(fixture(`alerts/${id}.json`));

describe("conditionText", () => {
  it.each([
    ["division", "Khulna", "division = Khulna"],
    ["amount_bdt", "≥ 3.44k", "amount_bdt ≥ 3.44k"],
    ["amount_bdt", "< 982", "amount_bdt < 982"],
    ["monthly_income", "28.7k – 41.9k", "monthly_income 28.7k – 41.9k"],
    ["is_international", "False", "is_international = False"],
  ])("%s %s", (feature, value, expected) => {
    expect(conditionText(feature, value)).toBe(expected);
  });
});

describe("summarize", () => {
  it("names the segment for a concentrated drop", () => {
    const text = summarize(incident("credit-risk-1"));
    expect(text).toMatch(/^Measured accuracy on labelled predictions since Oct 18/);
    expect(text).toContain("concentrated where division = Khulna");
  });

  it("says a broad drop is broad and names the biggest traffic shift", () => {
    const text = summarize(incident("fraud-screen-1"));
    expect(text).toContain("No single segment explains it");
    expect(text).toContain("amount_bdt ≥ 3.44k went from 25% to 52%");
  });

  it("describes changed relationships for multivariate incidents", () => {
    const text = summarize(incident("claims-triage-1"));
    expect(text).toMatch(/link between policy_value_bdt and claim_amount_bdt changed/);
    expect(text).toContain("0.86 to 0.64");
  });

  it("falls back cleanly when there is nothing else to say", () => {
    const bare = { ...incident("fraud-screen-1"), mixShifts: [], findings: [] };
    expect(summarize(bare)).toMatch(/spread across the traffic\.$/);
    const noPair = { ...incident("claims-triage-1"), correlationChanges: [] };
    expect(summarize(noPair)).toMatch(/^The way features move together changed\./);
  });
});

describe("fleetSentence", () => {
  it.each([
    [[], "No models are being monitored yet."],
    [["healthy", "healthy"], "All two models are healthy."],
    [["critical", "healthy"], "One of two models needs attention: one critical."],
    [
      ["critical", "critical", "warning", "healthy"],
      "Three of four models need attention: two critical and one with a warning.",
    ],
  ] as const)("%j", (statuses, expected) => {
    expect(fleetSentence([...statuses])).toBe(expected);
  });
});
