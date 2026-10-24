import { readdirSync } from "node:fs";
import { resolve } from "node:path";
import { fixture } from "../test/render";
import { fleetSchema, incidentSchema, modelSchema } from "./schema";

// Contract test: the Python generator and the dashboard must agree on every field.
const dir = resolve(import.meta.dirname, "../../public/data");
const files = (sub: string): string[] => readdirSync(resolve(dir, sub));

describe("committed demo data matches the schemas", () => {
  it("fleet.json", () => {
    expect(() => fleetSchema.parse(fixture("fleet.json"))).not.toThrow();
  });

  it.each(files("models"))("models/%s", (file) => {
    expect(() => modelSchema.parse(fixture(`models/${file}`))).not.toThrow();
  });

  it.each(files("alerts"))("alerts/%s", (file) => {
    expect(() => incidentSchema.parse(fixture(`alerts/${file}`))).not.toThrow();
  });

  it("every incident in the fleet index has a file, and every model a page", () => {
    const fleet = fleetSchema.parse(fixture("fleet.json"));
    const models = new Set(files("models").map((f) => f.replace(".json", "")));
    const alerts = new Set(files("alerts").map((f) => f.replace(".json", "")));
    for (const m of fleet.models) expect(models).toContain(m.id);
    for (const a of fleet.alerts) expect(alerts).toContain(a.id);
  });
});

describe("schemas reject bad data", () => {
  it("rejects probabilities outside [0, 1]", () => {
    const fleet = fixture("fleet.json") as { models: { estimate: { value: number } }[] };
    const first = fleet.models[0];
    if (!first) throw new Error("fixture has no models");
    first.estimate.value = 1.4;
    expect(fleetSchema.safeParse(fleet).success).toBe(false);
  });

  it("rejects an unknown schema version", () => {
    const fleet = { ...(fixture("fleet.json") as object), schemaVersion: 99 };
    expect(fleetSchema.safeParse(fleet).success).toBe(false);
  });
});
