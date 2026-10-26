import {
  activeCount,
  dateRange,
  EMPTY,
  filtersToParams,
  matchesModel,
  parseFilters,
  previousRange,
} from "./filters";

const parse = (query: string) => parseFilters(new URLSearchParams(query));

describe("parseFilters", () => {
  it("defaults to the last 30 days with nothing else set", () => {
    expect(parse("")).toEqual(EMPTY);
  });

  it("reads every slicer", () => {
    expect(parse("period=7&compare=previous&team=Lending,Payments&status=critical&q=fraud")).toEqual({
      ...EMPTY,
      period: 7,
      compare: true,
      teams: ["Lending", "Payments"],
      statuses: ["critical"],
      q: "fraud",
    });
  });

  it("ignores values it doesn't know", () => {
    expect(parse("period=45&status=on-fire,warning&compare=yes")).toEqual({
      ...EMPTY,
      statuses: ["warning"],
    });
  });

  it("accepts a custom range only when both ends are valid dates in order", () => {
    expect(parse("from=2026-10-01&to=2026-10-10")).toMatchObject({ from: "2026-10-01", to: "2026-10-10" });
    expect(parse("from=2026-10-10&to=2026-10-01")).toMatchObject({ from: null, to: null });
    expect(parse("from=2026-10-01")).toMatchObject({ from: null, to: null });
    expect(parse("from=yesterday&to=2026-10-10")).toMatchObject({ from: null, to: null });
  });
});

describe("filtersToParams", () => {
  it("writes only what differs from the defaults and keeps other params", () => {
    const base = new URLSearchParams("tab=inputs&period=7");
    expect(filtersToParams(EMPTY, base).toString()).toBe("tab=inputs");
    expect(filtersToParams({ ...EMPTY, teams: ["Growth"], compare: true }).toString()).toBe(
      "compare=previous&team=Growth",
    );
  });

  it("round-trips", () => {
    const f = parse("period=90&team=Lending&status=warning,critical&q=risk&from=2026-09-01&to=2026-09-30");
    expect(parseFilters(filtersToParams(f))).toEqual(f);
  });
});

describe("date ranges", () => {
  const today = "2026-10-24";

  it("ends today and spans the period", () => {
    expect(dateRange({ ...EMPTY, period: 7 }, today)).toEqual({ from: "2026-10-18", to: today, days: 7 });
  });

  it("prefers a custom range, clipped at today", () => {
    const f = { ...EMPTY, from: "2026-10-20", to: "2026-10-30" };
    expect(dateRange(f, today)).toEqual({ from: "2026-10-20", to: today, days: 5 });
  });

  it("compares with the same number of days just before, across a month end", () => {
    const range = dateRange({ ...EMPTY, period: 30 }, today);
    expect(range.from).toBe("2026-09-25");
    expect(previousRange(range)).toEqual({ from: "2026-08-26", to: "2026-09-24", days: 30 });
  });
});

describe("matchesModel", () => {
  const model = { id: "fraud-screen", name: "fraud-screen", team: "Payments", status: "critical" as const };

  it("passes everything with no filters", () => {
    expect(matchesModel(model, EMPTY)).toBe(true);
  });

  it("applies team, status and a case-insensitive search together", () => {
    expect(matchesModel(model, { ...EMPTY, teams: ["Payments"], statuses: ["critical"], q: "FRAUD" })).toBe(true);
    expect(matchesModel(model, { ...EMPTY, teams: ["Lending"] })).toBe(false);
    expect(matchesModel(model, { ...EMPTY, statuses: ["healthy"] })).toBe(false);
    expect(matchesModel(model, { ...EMPTY, q: "churn" })).toBe(false);
  });
});

it("counts active slicers", () => {
  expect(activeCount(EMPTY)).toBe(0);
  expect(activeCount(parse("period=7&team=A,B&q=x"))).toBe(3);
  expect(activeCount(parse("from=2026-10-01&to=2026-10-05&compare=previous"))).toBe(2);
});

describe("withParams", () => {
  it("sets and removes keys while keeping the rest", async () => {
    const { withParams } = await import("./links");
    expect(withParams("?period=7&tab=inputs", { tab: "segments" })).toBe("?period=7&tab=segments");
    expect(withParams("?period=7&feature=x", { feature: null })).toBe("?period=7");
    expect(withParams("", { tab: null })).toBe("");
  });
});
