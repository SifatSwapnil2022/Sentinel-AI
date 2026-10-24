import {
  ago,
  compact,
  count,
  daysBetween,
  decimal,
  longDate,
  percent,
  percentRange,
  points,
  pValue,
  shortDate,
} from "./format";

describe("percent", () => {
  it.each([
    [0.7673, "76.7%"],
    [1, "100.0%"],
    [0, "0.0%"],
    [-0.024, "−2.4%"],
  ])("%s -> %s", (value, expected) => {
    expect(percent(value)).toBe(expected);
  });

  it("shows a dash for missing or invalid values", () => {
    expect(percent(null)).toBe("—");
    expect(percent(undefined)).toBe("—");
    expect(percent(Number.NaN)).toBe("—");
  });

  it("respects digits", () => {
    expect(percent(0.2503, 0)).toBe("25%");
  });
});

describe("points", () => {
  it("signs changes with a true minus", () => {
    expect(points(-0.0242)).toBe("−2.4 points");
    expect(points(0.008)).toBe("+0.8 points");
  });
  it("does not print a signed zero", () => {
    expect(points(-0.0001)).toBe("0 points");
  });
  it("handles missing", () => {
    expect(points(null)).toBe("—");
  });
});

it("percentRange", () => {
  expect(percentRange(0.7531, 0.7821)).toBe("75.3 to 78.2%");
  expect(percentRange(null, 0.5)).toBe("—");
});

it("count and compact", () => {
  expect(count(1600)).toBe("1,600");
  expect(compact(2400)).toBe("2.4K");
});

it("decimal and pValue", () => {
  expect(decimal(-0.1234)).toBe("−0.12");
  expect(decimal(Number.NaN)).toBe("—");
  expect(pValue(0.00001)).toBe("p < 0.0001");
  expect(pValue(0.0042)).toBe("p = 0.0042");
  expect(pValue(0.31)).toBe("p = 0.310");
  expect(pValue(Number.NaN)).toBe("—");
});

describe("dates are read as calendar days, not shifted by time zone", () => {
  it("formats", () => {
    expect(shortDate("2026-10-16")).toBe("Oct 16");
    expect(longDate("2026-10-24")).toBe("October 24, 2026");
  });
  it("counts days", () => {
    expect(daysBetween("2026-10-16", "2026-10-24")).toBe(8);
    expect(ago("2026-10-24", "2026-10-24")).toBe("today");
    expect(ago("2026-10-23", "2026-10-24")).toBe("yesterday");
    expect(ago("2026-10-16", "2026-10-24")).toBe("8 days ago");
  });
});
