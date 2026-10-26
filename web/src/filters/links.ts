/** "?period=7&tab=inputs" from the current query with some keys set or removed. */
export function withParams(search: string, patch: Record<string, string | null>): string {
  const params = new URLSearchParams(search);
  for (const [key, value] of Object.entries(patch)) {
    if (value === null) params.delete(key);
    else params.set(key, value);
  }
  const text = params.toString();
  return text ? `?${text}` : "";
}
