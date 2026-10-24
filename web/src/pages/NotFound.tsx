import { isRouteErrorResponse, Link, useRouteError } from "react-router";
import layout from "./layout.module.css";

export function NotFound() {
  return (
    <div className={layout.page}>
      <header className={layout.header}>
        <h1>This page doesn't exist</h1>
        <p className={layout.meta}>Check the address, or start from the overview.</p>
        <p>
          <Link to="/">Go to overview</Link>
        </p>
      </header>
    </div>
  );
}

/** Last-resort boundary for errors thrown while rendering. */
export function RouteError() {
  const error = useRouteError();
  const detail = isRouteErrorResponse(error)
    ? `${error.status} ${error.statusText}`
    : error instanceof Error
      ? error.message
      : "Unknown error";
  return (
    <main style={{ padding: "48px 24px", maxWidth: "60ch" }}>
      <h1>Something broke on this page</h1>
      <p style={{ margin: "12px 0" }}>Reloading usually fixes it. If it doesn't, the detail below helps.</p>
      <pre style={{ whiteSpace: "pre-wrap", fontSize: 13 }}>{detail}</pre>
      <p>
        <a href="/">Go to overview</a>
      </p>
    </main>
  );
}
