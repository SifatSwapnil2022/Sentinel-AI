import { useMemo, useState } from "react";

export type Direction = "asc" | "desc";

/** Rows sorted by a column; click the same column again to reverse. Nulls always sort last. */
export function useSort<T, K extends string>(
  rows: readonly T[],
  get: (row: T, key: K) => string | number | null,
  initial: { key: K; direction: Direction },
) {
  const [sort, setSort] = useState(initial);
  const sorted = useMemo(() => {
    const factor = sort.direction === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const x = get(a, sort.key);
      const y = get(b, sort.key);
      if (x === null && y === null) return 0;
      if (x === null) return 1;
      if (y === null) return -1;
      return (x < y ? -1 : x > y ? 1 : 0) * factor;
    });
  }, [rows, get, sort]);
  const toggle = (key: K) =>
    setSort((s) => ({
      key,
      direction: s.key === key ? (s.direction === "asc" ? "desc" : "asc") : "desc",
    }));
  const ariaSort = (key: K): "ascending" | "descending" | "none" =>
    sort.key === key ? (sort.direction === "asc" ? "ascending" : "descending") : "none";
  return { sorted, sort, toggle, ariaSort };
}
