import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mockData, renderRoute } from "../test/render";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("overview", () => {
  it("leads with a sentence and lists models worst first", async () => {
    mockData();
    renderRoute("/");
    expect(
      await screen.findByText("Three of four models need attention: two critical and one with a warning."),
    ).toBeInTheDocument();
    const table = screen.getByRole("table");
    const names = within(table)
      .getAllByRole("link")
      .map((a) => a.textContent);
    expect(names).toEqual(["credit-risk", "fraud-screen", "claims-triage", "churn-predictor"]);
  });

  it("describes every forest-plot glyph for screen readers", async () => {
    mockData();
    renderRoute("/");
    const glyph = await screen.findByRole("img", { name: /^fraud-screen: estimated 79\.1%/ });
    expect(glyph).toHaveAccessibleName(/reference 88\.7%/);
  });
});

describe("model page", () => {
  it("shows the estimate with its range, and switches metric", async () => {
    mockData();
    renderRoute("/models/credit-risk");
    expect(await screen.findByRole("heading", { level: 1, name: "credit-risk" })).toBeInTheDocument();
    expect(screen.getByText("Estimated accuracy, Oct 24")).toBeInTheDocument();
    expect(screen.getByText(/^Likely 73\.7 to 79\.8%$/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("radio", { name: "Recall" }));
    expect(screen.getByText("Estimated recall, Oct 24")).toBeInTheDocument();
  });

  it("links to the open incident", async () => {
    mockData();
    renderRoute("/models/credit-risk");
    const link = await screen.findByRole("link", { name: "Measured accuracy fell outside the estimate" });
    expect(link).toHaveAttribute("href", "/incidents/credit-risk-1");
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

describe("inputs page", () => {
  it("lists drifted features first and expands a distribution", async () => {
    mockData();
    renderRoute("/models/fraud-screen/inputs");
    const table = await screen.findByRole("table");
    const firstRow = within(table).getAllByRole("row")[1];
    if (!firstRow) throw new Error("no rows");
    expect(within(firstRow).getByText("Drifted")).toBeInTheDocument();

    const toggle = within(firstRow).getByRole("button", { name: /Show distribution/ });
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("img", { name: /share of rows per bin/ })).toBeInTheDocument();
  });
});

describe("incident page", () => {
  it("names the segment behind a concentrated drop", async () => {
    mockData();
    renderRoute("/incidents/credit-risk-1");
    expect(await screen.findByText(/concentrated where division = Khulna/)).toBeInTheDocument();
    const segments = screen.getByRole("heading", { name: "Segments" }).closest("section");
    if (!segments) throw new Error("no section");
    expect(within(segments).getAllByText("division = Khulna")[0]).toBeInTheDocument();
  });

  it("shows traffic shifts when no segment stands out", async () => {
    mockData();
    renderRoute("/incidents/fraud-screen-1");
    expect(await screen.findByText(/^No segment stands out/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "25% to 52%" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Example predictions" })).not.toBeInTheDocument();
  });

  it("lists every signal in the order it fired", async () => {
    mockData();
    renderRoute("/incidents/fraud-screen-1");
    const list = (await screen.findByRole("heading", { name: "What fired" })).nextElementSibling;
    if (!list) throw new Error("no list");
    const dates = within(list as HTMLElement)
      .getAllByRole("listitem")
      .map((li) => li.querySelector("time")?.getAttribute("datetime"));
    expect(dates).toEqual([...dates].sort());
  });
});
