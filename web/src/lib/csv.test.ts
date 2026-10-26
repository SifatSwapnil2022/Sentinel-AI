import { csvName, toCsv } from "./csv";

describe("toCsv", () => {
  it("writes a header and one line per row", () => {
    expect(toCsv([{ model: "credit-risk", accuracy: 0.7637, open: true }])).toBe(
      "model,accuracy,open\ncredit-risk,0.7637,true\n",
    );
  });

  it("quotes commas, quotes and line breaks", () => {
    expect(toCsv([{ segment: 'division = "Khulna", income < 40k', note: "a\nb" }])).toBe(
      'segment,note\n"division = ""Khulna"", income < 40k","a\nb"\n',
    );
  });

  it("leaves nulls empty and follows the given column order", () => {
    expect(toCsv([{ a: 1, b: null }], ["b", "a"])).toBe("b,a\n,1\n");
  });

  it("is empty without rows or columns", () => {
    expect(toCsv([])).toBe("");
  });
});

it("csvName makes a safe file name", () => {
  expect(csvName("fraud screen", "2026-09-25", "2026-10-24")).toBe(
    "sentinel_fraud-screen_2026-09-25_2026-10-24.csv",
  );
});
