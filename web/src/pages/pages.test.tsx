import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { fleetSchema, incidentSchema, modelSchema } from "../data/schema";
import { fleetSentence } from "../lib/describe";
import { percent, percentRange } from "../lib/format";
import { fixture, mockData, renderRoute } from "../test/render";

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const fleet = fleetSchema.parse(fixture("fleet.json"));

afterEach(() => {
  vi.restoreAllMocks();
});

/** A tile, found by its title. Wide tables inside are regions with the same name, so skip those. */
async function region(name: string | RegExp) {
  const all = await screen.findAllByRole("region", { name });
  const tile = all.find((e) => e.tagName === "SECTION");
  if (!tile) throw new Error(`no tile named ${String(name)}`);
  return tile;
}

describe("overview", () => {
  it("leads with a sentence and lists models worst first", async () => {
    mockData();
    renderRoute("/overview");
    const sentence = fleetSentence(fleet.models.map((m) => m.status));
    expect(await screen.findByText((text) => text.startsWith(sentence))).toBeInTheDocument();
    const table = within(await region("Models")).getByRole("table");
    const statuses = within(table)
      .getAllByRole("row")
      .slice(1)
      .map((row) => fleet.models.find((m) => row.textContent.startsWith(m.name))?.status);
    const rank = { critical: 0, warning: 1, healthy: 2 } as const;
    const ranks = statuses.map((s) => (s ? rank[s] : 9));
    expect(ranks).toEqual([...ranks].sort());
    expect(ranks).toHaveLength(fleet.models.length);
  });

  it("describes every forest-plot glyph for screen readers", async () => {
    mockData();
    renderRoute("/overview");
    const fraud = fleet.models.find((m) => m.id === "fraud-screen");
    if (!fraud) throw new Error("fixture has no fraud-screen");
    const glyph = await screen.findByRole("img", {
      name: new RegExp(`^fraud-screen: estimated ${escape(percent(fraud.estimate.value))}`),
    });
    expect(glyph).toHaveAccessibleName(new RegExp(`reference ${escape(percent(fraud.referenceAccuracy))}`));
  });

  it("applies the team slicer from the address", async () => {
    mockData();
    renderRoute("/overview?team=Lending");
    const table = within(await region("Models")).getByRole("table");
    const names = within(table)
      .getAllByRole("link")
      .map((a) => a.textContent);
    const lending = fleet.models.filter((m) => m.team === "Lending").map((m) => m.name);
    expect(names.sort()).toEqual(lending.sort());
  });

  it("switches a tile to its table view", async () => {
    mockData();
    renderRoute("/overview");
    const tile = await region("Estimated accuracy today");
    await userEvent.click(within(tile).getByRole("button", { name: "Table" }));
    expect(within(tile).getByRole("table")).toBeInTheDocument();
    expect(within(tile).getByRole("button", { name: "Chart" })).toHaveAttribute("aria-pressed", "true");
  });
});

describe("models", () => {
  it("groups models by team", async () => {
    mockData();
    renderRoute("/models");
    for (const team of new Set(fleet.models.map((m) => m.team))) {
      expect(await region(team)).toBeInTheDocument();
    }
  });
});

describe("model page", () => {
  it("shows the estimate with its range, and switches metric", async () => {
    mockData();
    renderRoute("/models/credit-risk");
    expect(await screen.findByRole("heading", { level: 1, name: "credit-risk" })).toBeInTheDocument();
    expect(screen.getByText("Estimated accuracy, Oct 24")).toBeInTheDocument();
    const latest = modelSchema.parse(fixture("models/credit-risk.json")).days.at(-1)?.estimate.accuracy;
    if (!latest) throw new Error("fixture has no days");
    expect(screen.getByText(`Likely ${percentRange(latest.lower, latest.upper)}`)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Recall" }));
    expect(screen.getByText("Estimated recall, Oct 24")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Recall" })).toHaveAttribute("aria-pressed", "true");
  });

  it("links to the open incident", async () => {
    mockData();
    renderRoute("/models/credit-risk");
    const link = await screen.findByRole("link", { name: "Measured accuracy fell outside the estimate" });
    expect(link).toHaveAttribute("href", "/incidents/credit-risk-1");
  });

  it("keeps the slicers when switching tabs", async () => {
    mockData();
    renderRoute("/models/credit-risk?period=7");
    const tabs = await screen.findByRole("navigation", { name: "Model sections" });
    expect(within(tabs).getByRole("link", { name: "Inputs" })).toHaveAttribute(
      "href",
      "/models/credit-risk?period=7&tab=inputs",
    );
    expect(within(tabs).getByRole("link", { name: "Performance" })).toHaveAttribute("aria-current", "page");
  });

  it("explains a model that doesn't exist", async () => {
    mockData();
    renderRoute("/models/nope");
    expect(await screen.findByRole("heading", { name: "Can't find this model" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
  });

  it("offers a retry when the data is malformed", async () => {
    mockData({ "models/credit-risk.json": () => new Response('{"schemaVersion": 1}') });
    renderRoute("/models/credit-risk");
    expect(await screen.findByRole("heading", { name: "Couldn't load this model" })).toBeInTheDocument();
    expect(screen.getByText(/^Unexpected data at/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});

describe("inputs tab", () => {
  it("sends the old inputs address to the tab", async () => {
    mockData();
    const { router } = renderRoute("/models/fraud-screen/inputs");
    await waitFor(() => {
      expect(router.state.location.search).toBe("?tab=inputs");
    });
    expect(await region("Drift by feature and day")).toBeInTheDocument();
  });

  it("ranks features by drift days and opens a feature's distribution", async () => {
    mockData();
    renderRoute("/models/fraud-screen?tab=inputs");
    const table = within(await region("Features")).getByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    const days = rows.map((r) => Number(r.querySelectorAll("td")[4]?.textContent));
    expect(days).toEqual([...days].sort((a, b) => b - a));
    expect(days[0]).toBeGreaterThan(0);

    const last = rows.at(-1);
    const link = last && within(last).getAllByRole("link")[0];
    if (!link?.textContent) throw new Error("no feature link");
    const name = link.textContent;
    await userEvent.click(link);
    expect(await region(`Distribution of ${name}`)).toBeInTheDocument();
  });

  it("shows missing values for a feature that went empty", async () => {
    mockData();
    renderRoute("/models/upsell-propensity?tab=inputs");
    const tile = await region("Missing values");
    expect(within(tile).getByRole("img", { name: /Missing values by day for 1 features/ })).toBeInTheDocument();
  });
});

describe("segments tab", () => {
  it("ranks drops and switches the feature", async () => {
    mockData();
    renderRoute("/models/credit-risk?tab=segments");
    expect(await region("Largest drops by segment")).toBeInTheDocument();
    const select = await screen.findByRole("combobox", { name: "Feature" });
    await userEvent.selectOptions(select, "age");
    expect(await region("Accuracy by age")).toBeInTheDocument();
  });
});

describe("traffic tab", () => {
  it("charts volume, latency and labels", async () => {
    mockData();
    renderRoute("/models/fraud-screen?tab=traffic");
    for (const name of ["Predictions per day", "p95 latency", "Labels in"]) {
      expect(await region(name)).toBeInTheDocument();
    }
  });
});

describe("incidents", () => {
  it("lists open incidents and keeps resolved ones a click away", async () => {
    mockData();
    renderRoute("/incidents?period=90");
    const table = within(await region("Open incidents")).getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(fleet.alerts.length + 1);

    await userEvent.click(screen.getByRole("link", { name: /^Resolved/ }));
    const resolved = within(await region("Resolved incidents")).getByRole("table");
    const [first] = fleet.resolved;
    if (!first) throw new Error("fixture has no resolved incident");
    expect(within(resolved).getByRole("link", { name: first.title })).toHaveAttribute(
      "href",
      `/incidents/${first.id}`,
    );
  });
});

describe("incident page", () => {
  it("names the segment behind a concentrated drop", async () => {
    mockData();
    renderRoute("/incidents/credit-risk-1");
    expect(await screen.findByText(/concentrated where division = Khulna/)).toBeInTheDocument();
    const segments = await region("Segments that cost the most");
    expect(within(segments).getAllByText("division = Khulna")[0]).toBeInTheDocument();
  });

  it("shows traffic shifts when no segment stands out", async () => {
    mockData();
    renderRoute("/incidents/fraud-screen-1");
    expect(await screen.findByText(/^No segment stands out/)).toBeInTheDocument();
    const [shift] = incidentSchema.parse(fixture("alerts/fraud-screen-1.json")).mixShifts;
    if (!shift) throw new Error("fixture has no mix shifts");
    const name = `${percent(shift.reference, 0)} to ${percent(shift.current, 0)}`;
    expect(screen.getAllByRole("img", { name })[0]).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Example predictions" })).not.toBeInTheDocument();
  });

  it("lists every signal in the order it fired", async () => {
    mockData();
    renderRoute("/incidents/fraud-screen-1");
    const list = within(await region("What fired")).getByRole("list");
    const dates = within(list)
      .getAllByRole("listitem")
      .map((li) => li.querySelector("time")?.getAttribute("datetime"));
    expect(dates).toEqual([...dates].sort());
  });

  it("puts the missing feature first for a data quality incident", async () => {
    mockData();
    renderRoute("/incidents/upsell-propensity-1");
    const incident = incidentSchema.parse(fixture("alerts/upsell-propensity-1.json"));
    const [missing] = incident.missingFeatures;
    if (!missing) throw new Error("fixture has no missing feature");
    expect(await screen.findByText(new RegExp(`^${missing.name} arrives empty`))).toBeInTheDocument();
    const table = within(await region("Missing values")).getByRole("table");
    expect(within(table).getByText(percent(missing.nullRate, 1))).toBeInTheDocument();
  });

  it("says when an incident resolved", async () => {
    mockData();
    renderRoute("/incidents/policy-lapse-1");
    expect(await screen.findByText("Resolved")).toBeInTheDocument();
    expect(screen.getByText(/resolved Sep \d+ after \d+ days/)).toBeInTheDocument();
  });
});

describe("explore", () => {
  it("offers bars only for amounts that add up", async () => {
    mockData();
    renderRoute("/explore");
    const bars = await screen.findByRole("button", { name: "Bars by day" });
    expect(bars).toBeDisabled();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Measure" }), "predictions");
    expect(screen.getByRole("button", { name: "Bars by day" })).toBeEnabled();
    expect(await region("Predictions by model")).toBeInTheDocument();
  });

  it("reads the view from the address", async () => {
    mockData();
    renderRoute("/explore?measure=predictions&by=team&view=total");
    const tile = await region("Predictions by team");
    for (const team of new Set(fleet.models.map((m) => m.team))) {
      expect(within(tile).getAllByText(team)[0]).toBeInTheDocument();
    }
  });
});

describe("reports", () => {
  it("links every table's CSV", async () => {
    mockData();
    renderRoute("/reports");
    const table = within(await region("Tables")).getByRole("table");
    const links = within(table).getAllByRole("link", { name: "CSV" });
    expect(links.map((a) => a.getAttribute("href"))).toContain("/data/bi/fact_model_day.csv");
    expect(links).toHaveLength(7);
  });
});

describe("landing page", () => {
  it("states the problem with the demo's own numbers and links into the dashboard", async () => {
    mockData();
    renderRoute("/");
    expect(await screen.findByRole("heading", { level: 1, name: /labels arrive late/ })).toBeInTheDocument();

    const fraud = fleet.models.find((m) => m.id === "fraud-screen");
    if (!fraud) throw new Error("fixture has no fraud-screen");
    const readings = await screen.findByRole("figure", { name: /a fraud model in the demo/ });
    expect(within(readings).getByText(percent(fraud.measured.value))).toBeInTheDocument();
    expect(within(readings).getByText(percent(fraud.estimate.value))).toBeInTheDocument();

    expect(screen.getByRole("link", { name: "Open the live dashboard" })).toHaveAttribute("href", "/overview");
    await waitFor(() => {
      expect(screen.getAllByRole("link", { name: "See the incident" })).toHaveLength(3);
    });
    const proofs = screen.getAllByRole("link", { name: "See the incident" });
    expect(proofs.map((a) => a.getAttribute("href"))).toEqual([
      "/incidents/credit-risk-1",
      "/incidents/claims-triage-1",
      "/incidents/upsell-propensity-1",
    ]);
    expect(await screen.findAllByText(/division = Khulna/)).toHaveLength(2);
  });

  it("still makes its case when the demo cases are missing", async () => {
    mockData({ "fleet.json": () => Response.json({ ...(fixture("fleet.json") as object), alerts: [] }) });
    renderRoute("/");
    expect(await screen.findByRole("heading", { name: "Why models fail quietly" })).toBeInTheDocument();
    expect(screen.queryByRole("figure", { name: /a fraud model/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "See the incident" })).not.toBeInTheDocument();
    expect(screen.getByText(/A small drop overall can be a large one/)).toBeInTheDocument();
  });
});

describe("page titles", () => {
  it.each([
    ["/overview", "Overview – Sentinel"],
    ["/models", "Models – Sentinel"],
    ["/models/credit-risk", "credit-risk – Sentinel"],
    ["/models/credit-risk?tab=segments", "credit-risk segments – Sentinel"],
    ["/incidents/credit-risk-1", "Incident credit-risk-1 – Sentinel"],
    ["/incidents", "Incidents – Sentinel"],
    ["/explore", "Explore – Sentinel"],
    ["/reports", "Reports – Sentinel"],
    ["/nowhere", "Page not found – Sentinel"],
  ])("%s", async (path, title) => {
    mockData();
    renderRoute(path);
    await waitFor(() => {
      expect(document.title).toBe(title);
    });
  });
});
