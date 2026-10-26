import { useEffect } from "react";

/** Give the browser tab a page-specific title (WCAG 2.4.2), e.g. "credit-risk – Sentinel". */
export function useTitle(page: string | null): void {
  useEffect(() => {
    document.title = page ? `${page} – Sentinel` : "Sentinel";
  }, [page]);
}
