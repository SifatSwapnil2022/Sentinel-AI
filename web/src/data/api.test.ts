import { dataSource } from "./api";

describe("dataSource", () => {
  it("reads the bundled demo JSON by default", () => {
    for (const api of [undefined, ""]) {
      const s = dataSource(api, "/sentinel/");
      expect(s.live).toBe(false);
      expect(s.fleet).toBe("/sentinel/data/fleet.json");
      expect(s.model("credit-risk")).toBe("/sentinel/data/models/credit-risk.json");
      expect(s.incident("credit-risk-1")).toBe("/sentinel/data/alerts/credit-risk-1.json");
      expect(s.daily).toBe("/sentinel/data/fleet-daily.json");
      expect(s.export("dim_model")).toBe("/sentinel/data/bi/dim_model.csv");
    }
  });

  it("reads a live API when one is configured", () => {
    const s = dataSource("https://sentinel.example.com/", "/");
    expect(s.live).toBe(true);
    expect(s.fleet).toBe("https://sentinel.example.com/v1/fleet");
    expect(s.model("credit-risk")).toBe("https://sentinel.example.com/v1/models/credit-risk");
    expect(s.incident("credit-risk-1")).toBe("https://sentinel.example.com/v1/incidents/credit-risk-1");
    expect(s.daily).toBe("https://sentinel.example.com/v1/fleet/daily");
    expect(s.export("dim_model")).toBe("https://sentinel.example.com/v1/export/dim_model.csv");
  });

  it("supports the same origin and escapes ids", () => {
    const s = dataSource("/", "/");
    expect(s.fleet).toBe("/v1/fleet");
    expect(s.model("a/b")).toBe("/v1/models/a%2Fb");
  });
});
