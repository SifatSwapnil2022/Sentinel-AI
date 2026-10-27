import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { fleetSchema } from "../data/schema";
import { fixture, mockData, renderRoute } from "../test/render";

const fleet = fleetSchema.parse(fixture("fleet.json"));

async function region(name: string | RegExp) {
  const all = await screen.findAllByRole("region", { name });
  const tile = all.find((e) => e.tagName === "SECTION");
  if (!tile) throw new Error(`no tile named ${String(name)}`);
  return tile;
}

/** Capture what a CSV button would save, instead of downloading it. */
function captureDownloads() {
  const files: { name: string; text: Promise<string> }[] = [];
  const blobs = new Map<string, Blob>();
  vi.spyOn(URL, "createObjectURL").mockImplementation((blob) => {
    const url = `blob:${blobs.size}`;
    blobs.set(url, blob as Blob);
    return url;
  });
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    const blob = blobs.get(this.href);
    if (blob) files.push({ name: this.download, text: blob.text() });
  });
  return files;
}

beforeAll(() => {
  // jsdom has <dialog> but not its modal methods.
  HTMLDialogElement.prototype.showModal = function (this: HTMLDialogElement) {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function (this: HTMLDialogElement) {
    this.open = false;
    this.dispatchEvent(new Event("close"));
  };
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("filter bar", () => {
  it("writes each slicer to the address and clears them", async () => {
    mockData();
    const { router } = renderRoute("/overview");
    const bar = await screen.findByRole("region", { name: "Filters" });
    const search = () => new URLSearchParams(router.state.location.search);

    await userEvent.click(within(bar).getByRole("button", { name: "7 days" }));
    expect(search().get("period")).toBe("7");
    await userEvent.click(within(bar).getByRole("button", { name: "Compare with previous period" }));
    expect(search().get("compare")).toBe("previous");
    await userEvent.click(within(bar).getByRole("button", { name: "Critical" }));
    expect(search().get("status")).toBe("critical");
    await userEvent.click(within(bar).getByText("All teams"));
    await userEvent.click(within(bar).getByRole("checkbox", { name: "Lending" }));
    expect(search().get("team")).toBe("Lending");
    await userEvent.type(within(bar).getByRole("searchbox", { name: "Find a model" }), "credit");
    expect(search().get("q")).toBe("credit");

    const table = within(await region("Models")).getByRole("table");
    expect(within(table).getAllByRole("link").map((a) => a.textContent)).toEqual(["credit-risk"]);

    await userEvent.click(within(bar).getByRole("button", { name: "Clear filters" }));
    expect(router.state.location.search).toBe("");
  });

  it("shows and clears a custom date range", async () => {
    mockData();
    const { router } = renderRoute("/models/credit-risk?from=2026-10-01&to=2026-10-10");
    const clear = await screen.findByRole("button", { name: "Clear the selected dates" });
    expect(screen.getByText("Oct 1 to Oct 10")).toBeInTheDocument();
    await userEvent.click(clear);
    expect(router.state.location.search).toBe("");
  });

  it("copies the current link", async () => {
    mockData();
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    renderRoute("/overview?period=7");
    await userEvent.click(await screen.findByRole("button", { name: "Copy link" }));
    expect(writeText).toHaveBeenCalledOnce();
    expect(await screen.findByRole("button", { name: "Link copied" })).toBeInTheDocument();
  });
});

describe("tiles", () => {
  it("download the data behind a chart", async () => {
    mockData();
    const files = captureDownloads();
    renderRoute("/overview");
    await userEvent.click(within(await region("Models")).getByRole("button", { name: "CSV" }));
    expect(files[0]?.name).toMatch(/^sentinel_models_.*\.csv$/);
    const text = (await files[0]?.text) ?? "";
    expect(text.split("\n")).toHaveLength(fleet.models.length + 2);
  });

  it("open full screen and close again", async () => {
    mockData();
    renderRoute("/overview");
    const tile = await region("Incidents");
    await userEvent.click(within(tile).getByRole("button", { name: "Expand Incidents" }));
    const dialog = screen.getByRole("dialog", { name: "Incidents" });
    expect(within(dialog).getByRole("figure")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("show every overview chart as a table", async () => {
    mockData();
    renderRoute("/overview?compare=previous");
    for (const name of ["Incidents", "Accuracy against reference, by day"]) {
      const tile = await region(name);
      await userEvent.click(within(tile).getByRole("button", { name: "Table" }));
      expect(within(tile).getByRole("table")).toBeInTheDocument();
    }
    expect(within(await region("Models")).getByRole("button", { name: /Previous period/ })).toBeInTheDocument();
  });
});

describe("sorting", () => {
  it("reorders the models table and marks the column", async () => {
    mockData();
    renderRoute("/overview");
    const table = within(await region("Models")).getByRole("table");
    await userEvent.click(within(table).getByRole("button", { name: /^Predictions/ }));
    const header = within(table).getByRole("columnheader", { name: /^Predictions/ });
    expect(header).toHaveAttribute("aria-sort", "descending");
    const volumes = within(table)
      .getAllByRole("row")
      .slice(1)
      .map((r) => r.querySelectorAll("td")[8]?.textContent ?? "");
    expect(volumes.length).toBe(fleet.models.length);
    await userEvent.click(within(table).getByRole("button", { name: /^Predictions/ }));
    expect(header).toHaveAttribute("aria-sort", "ascending");
  });
});

describe("model tabs", () => {
  it("performance shows daily values and label checks as tables", async () => {
    mockData();
    renderRoute("/models/credit-risk?compare=previous");
    for (const name of [/^Estimated accuracy$/, "Check against labels"]) {
      const tile = await region(name);
      await userEvent.click(within(tile).getByRole("button", { name: "Table" }));
      expect(within(tile).getByRole("table")).toBeInTheDocument();
    }
    expect(screen.getAllByText("Below range")[0]).toBeInTheDocument();
  });

  it("zooms to the days picked on the accuracy chart with the keyboard", async () => {
    mockData();
    const { router } = renderRoute("/models/fraud-screen");
    const chart = await screen.findByRole("group", { name: /Accuracy over 30 days/ });
    chart.focus();
    for (const key of ["{Home}", "{Enter}", "{ArrowRight}", "{ArrowRight}", "{ArrowRight}", "{Enter}"]) {
      await userEvent.keyboard(key);
    }
    await waitFor(() => {
      expect(router.state.location.search).toBe("?from=2026-09-25&to=2026-09-28");
    });
  });

  it("traffic shows a table and compares with the previous period", async () => {
    mockData();
    renderRoute("/models/fraud-screen?tab=traffic&compare=previous");
    expect(await screen.findByText(/on previous period$/)).toBeInTheDocument();
    const tile = await region("Predictions per day");
    await userEvent.click(within(tile).getByRole("button", { name: "Table" }));
    expect(within(tile).getAllByRole("row")).toHaveLength(31);
  });

  it("inputs show the drift heatmap as a table", async () => {
    mockData();
    renderRoute("/models/claims-triage?tab=inputs");
    const tile = await region("Drift by feature and day");
    await userEvent.click(within(tile).getByRole("button", { name: "Table" }));
    expect(within(tile).getAllByRole("row")).toHaveLength(31);
    const features = within(await region("Features")).getByRole("table");
    await userEvent.click(within(features).getByRole("button", { name: /^Feature/ }));
    expect(within(features).getByRole("columnheader", { name: /^Feature/ })).toHaveAttribute("aria-sort", "descending");
  });

  it("segments jump from a ranked drop to its feature", async () => {
    mockData();
    renderRoute("/models/credit-risk?tab=segments");
    const drops = await region("Largest drops by segment");
    const first = within(drops).getAllByRole("button").find((b) => b.textContent.includes(" = "));
    if (!first) throw new Error("no ranked segment");
    const feature = first.textContent.split(" = ")[0] ?? "";
    await userEvent.click(first);
    expect(await region(`Accuracy by ${feature}`)).toBeInTheDocument();
  });

  it("lists a model's incident history", async () => {
    mockData();
    renderRoute("/models/policy-lapse?tab=incidents");
    const table = within(await region("Incidents")).getByRole("table");
    expect(within(table).getByRole("cell", { name: "Resolved" })).toBeInTheDocument();
    expect(screen.getByRole("figure", { name: "Incidents for policy-lapse" })).toBeInTheDocument();
  });

  it("says when a model has no incidents", async () => {
    mockData();
    renderRoute("/models/wallet-fraud?tab=incidents");
    expect(await screen.findByText(/^No incidents in the 90 days on record/)).toBeInTheDocument();
  });
});

describe("explore", () => {
  it("compares the period totals with the period before", async () => {
    mockData();
    renderRoute("/explore?measure=predictions&by=fleet&compare=previous");
    const summary = within(await region("Summary")).getByRole("table");
    expect(within(summary).getByRole("columnheader", { name: "Change" })).toBeInTheDocument();
    expect(within(summary).getByText(/^[+−]\d+\.\d%$/)).toBeInTheDocument();
  });

  it("switches to period totals", async () => {
    mockData();
    const { router } = renderRoute("/explore?measure=gap");
    await userEvent.click(await screen.findByRole("button", { name: "Period total" }));
    expect(router.state.location.search).toContain("view=total");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Group by" }), "team");
    expect(await region("Accuracy against reference by team")).toBeInTheDocument();
  });
});

describe("charts", () => {
  it("show a readout when the pointer moves over a daily chart", async () => {
    mockData();
    renderRoute("/models/fraud-screen?tab=traffic");
    const tile = await region("p95 latency");
    const plot = tile.querySelector("svg rect[fill='transparent']");
    if (!plot) throw new Error("no hit area");
    fireEvent.pointerMove(plot, { clientX: 400 });
    expect(within(tile).getByText(/\d+ ms$/, { selector: "span" })).toBeInTheDocument();
    fireEvent.pointerLeave(plot);
  });
});

describe("not found", () => {
  it("offers a way back", async () => {
    mockData();
    renderRoute("/nowhere");
    expect(await screen.findByRole("heading", { name: "This page doesn't exist" })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /overview/i })[0]).toBeInTheDocument();
  });
});

describe("LLM apps", () => {
  it("opens on the critical incident and highlights the leaked number", async () => {
    mockData();
    renderRoute("/llm");
    expect(await screen.findByRole("heading", { level: 1, name: "support-assistant" })).toBeInTheDocument();
    const tile = await region("Answers exposed customer phone numbers");
    const [first] = within(tile).getAllByRole("article");
    const mark = first?.querySelector("mark");
    expect(mark?.textContent).toMatch(/^01[3-9]\d{8}$/);
  });

  it("switches incident from the table", async () => {
    mockData();
    const { router } = renderRoute("/llm?period=90");
    const table = within(await region("Incidents")).getByRole("table");
    await userEvent.click(within(table).getByRole("link", { name: "Answers stated things the articles don't say" }));
    expect(router.state.location.search).toContain("incident=support-assistant-llm-1");
    const tile = await region("Answers stated things the articles don't say");
    expect(within(tile).getAllByRole("article")[0]?.querySelector("mark")).not.toBeNull();
  });
});
