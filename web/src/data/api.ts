import { useQuery } from "@tanstack/react-query";
import type { z } from "zod";
import { fleetSchema, incidentSchema, modelSchema } from "./schema";

/** Base URL for data. Static demo JSON today; the step-3 API will serve the same shapes. */
const BASE = `${import.meta.env.BASE_URL}data`;

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
  queryFn: () => fetchValidated(`${BASE}/fleet.json`, fleetSchema),
  staleTime: 60_000,
  retry,
});

export const modelQuery = (id: string) => ({
  queryKey: ["model", id] as const,
  queryFn: () => fetchValidated(`${BASE}/models/${encodeURIComponent(id)}.json`, modelSchema),
  staleTime: 60_000,
  retry,
});

export const incidentQuery = (id: string) => ({
  queryKey: ["incident", id] as const,
  queryFn: () => fetchValidated(`${BASE}/alerts/${encodeURIComponent(id)}.json`, incidentSchema),
  staleTime: 60_000,
  retry,
});

export const useFleet = () => useQuery(fleetQuery());
export const useModel = (id: string) => useQuery(modelQuery(id));
export const useIncident = (id: string) => useQuery(incidentQuery(id));
