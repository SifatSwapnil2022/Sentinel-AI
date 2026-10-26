import layout from "../pages/layout.module.css";

type State = "ascending" | "descending" | "none";

/** A column header that sorts its table; the arrow shows the current order. */
export function SortableTh({
  label,
  state,
  onSort,
  numeric = false,
}: {
  label: string;
  state: State;
  onSort: () => void;
  numeric?: boolean | undefined;
}) {
  return (
    <th scope="col" aria-sort={state} className={numeric ? layout.num : undefined}>
      <button type="button" className={layout.sort} onClick={onSort}>
        {label}
        <SortMark state={state} />
      </button>
    </th>
  );
}

function SortMark({ state }: { state: State }) {
  return (
    <svg width="8" height="10" viewBox="0 0 8 10" aria-hidden="true" style={{ opacity: state === "none" ? 0.3 : 1 }}>
      {state !== "descending" && <path d="M4 1 7 4H1z" fill="currentColor" />}
      {state !== "ascending" && <path d="M4 9 1 6h6z" fill="currentColor" />}
    </svg>
  );
}
