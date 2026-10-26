import type { UseQueryResult } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link } from "react-router";
import { DataError } from "../data/api";
import styles from "./QueryState.module.css";

interface Props<T> {
  query: UseQueryResult<T>;
  /** What is being loaded, for messages: "this model", "the fleet". */
  subject: string;
  children: (data: T) => ReactNode;
}

/** Loading and error states for a query, in one place and one voice. */
export function QueryState<T>({ query, subject, children }: Props<T>) {
  if (query.data !== undefined) return <>{children(query.data)}</>;

  if (query.isError) {
    const error = query.error;
    const notFound = error instanceof DataError && error.kind === "not-found";
    return (
      <div className={styles.message} role="alert">
        <h1>{notFound ? `Can't find ${subject}` : `Couldn't load ${subject}`}</h1>
        <p>
          {notFound
            ? "It may have been renamed or removed. Check the address, or pick one from the overview."
            : error.message}
        </p>
        <div className={styles.actions}>
          {!notFound && (
            <button type="button" onClick={() => void query.refetch()}>
              Try again
            </button>
          )}
          <Link to="/overview">Go to overview</Link>
        </div>
      </div>
    );
  }

  return (
    <p className={styles.loading} role="status">
      Loading {subject}
    </p>
  );
}
