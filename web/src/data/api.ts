import { useQuery } from "@tanstack/react-query";
import type { z } from "zod";
import { dailySchema, fleetSchema, incidentSchema, llmSchema, modelSchema } from "./schema";

/**
 * Where documents come from. Both sources serve identical shapes (the server's parity test
 * holds them to it): the static demo JSON shipped with the app, or a live Sentinel API when
 * `VITE_SENTINEL_API` is set at build time ("/" for the same origin, or a full URL).
 */
export interface DataSource {
  live: boolean;
  fleet: string;
  daily: string;
  /** LLM app monitoring. The API has no LLM endpoints yet, so this is always the demo file. */
  llm: string;
  model: (id: string) => string;
  incident: (id: string) => string;
  /** One table of the BI star schema as CSV. */
  export: (table: string) => string;
}

export function dataSource(api: string | undefined, base: string): DataSource {
  if (api !== undefined && api !== "") {
    const root = api.replace(/\/+$/, "");
    return {
      live: true,
      fleet: `${root}/v1/fleet`,
      daily: `${root}/v1/fleet/daily`,
      llm: `${base}data/llm.json`,
      model: (id) => `${root}/v1/models/${encodeURIComponent(id)}`,
      incident: (id) => `${root}/v1/incidents/${encodeURIComponent(id)}`,
      export: (table) => `${root}/v1/export/${encodeURIComponent(table)}.csv`,
    };
  }
  const root = `${base}data`;
  return {
    live: false,
    fleet: `${root}/fleet.json`,
    daily: `${root}/fleet-daily.json`,
    llm: `${root}/llm.json`,
    model: (id) => `${root}/models/${encodeURIComponent(id)}.json`,
    incident: (id) => `${root}/alerts/${encodeURIComponent(id)}.json`,
    export: (table) => `${root}/bi/${encodeURIComponent(table)}.csv`,
  };
}

export const source = dataSource(import.meta.env.VITE_SENTINEL_API, import.meta.env.BASE_URL);

/** Live data refreshes in the background; the static demo never changes. */
const freshness = source.live
  ? { staleTime: 15_000, refetchInterval: 60_000 }
  : { staleTime: Number.POSITIVE_INFINITY };

export class DataError extends Error {
  constructor(
    message: string,
    readonly kind: "not-found" | "network" | "invalid",
    readonly url: string,
  ) {
    super(message);
    this.name = "DataError";
  }
}

export async function fetchValidated<T>(url: string, schema: z.ZodType<T>): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, { headers: { Accept: "application/json" } });
  } catch {
    throw new DataError("Couldn't reach the data source. Check your connection.", "network", url);
  }
  if (response.status === 404) {
    throw new DataError("Not found.", "not-found", url);
  }
  if (!response.ok) {
    throw new DataError(`The data source answered ${response.status}.`, "network", url);
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new DataError("The data source sent something that isn't JSON.", "invalid", url);
  }
  const parsed = schema.safeParse(body);
  if (!parsed.success) {
    const first = parsed.error.issues[0];
    const where = first?.path.join(".") ?? "root";
    throw new DataError(`Unexpected data at ${where}: ${first?.message ?? "invalid"}.`, "invalid", url);
  }
  return parsed.data;
}

const retry = (count: number, error: Error) =>
  !(error instanceof DataError && error.kind !== "network") && count < 2;

export const fleetQuery = () => ({
  queryKey: ["fleet"] as const,
  queryFn: () => fetchValidated(source.fleet, fleetSchema),
  ...freshness,
  retry,
});

export const dailyQuery = () => ({
  queryKey: ["daily"] as const,
  queryFn: () => fetchValidated(source.daily, dailySchema),
  ...freshness,
  retry,
});

export const modelQuery = (id: string) => ({
  queryKey: ["model", id] as const,
  queryFn: () => fetchValidated(source.model(id), modelSchema),
  ...freshness,
  retry,
});

export const incidentQuery = (id: string) => ({
  queryKey: ["incident", id] as const,
  queryFn: () => fetchValidated(source.incident(id), incidentSchema),
  ...freshness,
  retry,
});

export const llmQuery = () => ({
  queryKey: ["llm"] as const,
  queryFn: () => fetchValidated(source.llm, llmSchema),
  ...freshness,
  retry,
});

export const useLlm = () => useQuery(llmQuery());
export const useFleet = () => useQuery(fleetQuery());
export const useDaily = () => useQuery(dailyQuery());
export const useModel = (id: string) => useQuery(modelQuery(id));
export const useIncident = (id: string) => useQuery(incidentQuery(id));
