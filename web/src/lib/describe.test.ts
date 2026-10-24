import { incidentSchema } from "../data/schema";
import { fixture } from "../test/render";
import { conditionText, fleetSentence, summarize } from "./describe";
import { percent, shortDate } from "./format";

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
    const credit = incident("credit-risk-1");
    const text = summarize(credit);
    expect(text).toMatch(
      new RegExp(`^Measured accuracy on labelled predictions since ${shortDate(credit.window.from)} `),
    );
    expect(text).toContain("concentrated where division = Khulna");
  });

  it("says a broad drop is broad and names the biggest traffic shift", () => {
    const fraud = incident("fraud-screen-1");
    const text = summarize(fraud);
    expect(text).toContain("No single segment explains it");
    const [shift] = fraud.mixShifts;
    if (!shift) throw new Error("fixture has no mix shifts");
    expect(shift.feature).toBe("amount_bdt");
    expect(text).toContain(
      `${conditionText(shift.feature, shift.value)} went from ${percent(shift.reference, 0)} to ${percent(shift.current, 0)}`,
    );
  });

  it("describes changed relationships for multivariate incidents", () => {
    const claims = incident("claims-triage-1");
    const text = summarize(claims);
    expect(text).toMatch(/link between policy_value_bdt and claim_amount_bdt changed/);
    const [pair] = claims.correlationChanges;
    if (!pair) throw new Error("fixture has no correlation changes");
    expect(pair.reference - pair.current).toBeGreaterThan(0.3); // the scenario breaks the link
    expect(text).toContain(`${pair.reference.toFixed(2)} to ${pair.current.toFixed(2)}`);
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
