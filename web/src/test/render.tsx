import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { vi } from "vitest";
import { routes } from "../app/router";

const DATA_DIR = resolve(import.meta.dirname, "../../public/data");

/** Read a committed demo JSON file, e.g. "fleet.json" or "models/credit-risk.json". */
export function fixture(path: string): unknown {
  return JSON.parse(readFileSync(resolve(DATA_DIR, path), "utf8"));
}

/** Serve /data/* from the committed demo JSON; overrides replace or break specific files. */
export function mockData(overrides: Record<string, Response | (() => Response)> = {}) {
  const spy = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const path = url.replace(/^.*\/data\//, "");
    const override = overrides[path];
    if (override) return Promise.resolve(typeof override === "function" ? override() : override);
    try {
      return Promise.resolve(new Response(readFileSync(resolve(DATA_DIR, path), "utf8"), { status: 200 }));
    } catch {
      return Promise.resolve(new Response("not found", { status: 404 }));
    }
  });
  return spy;
}

/** Render the real route tree at a path, with a fresh query cache and no retries. */
export function renderRoute(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return {
    router,
    ...render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    ),
  };
}
