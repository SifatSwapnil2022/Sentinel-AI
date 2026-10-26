import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router";
import { EMPTY, type Filters, filtersToParams, parseFilters } from "./filters";

/** The global slicers, read from and written to the URL. */
export function useFilters() {
  const [params, setParams] = useSearchParams();
  const filters = useMemo(() => parseFilters(params), [params]);

  const update = useCallback(
    (patch: Partial<Filters>) => {
      setParams((current) => filtersToParams({ ...parseFilters(current), ...patch }, current), {
        replace: true,
      });
    },
    [setParams],
  );

  const reset = useCallback(() => {
    setParams((current) => filtersToParams(EMPTY, current), { replace: true });
  }, [setParams]);

  return { filters, update, reset };
}
