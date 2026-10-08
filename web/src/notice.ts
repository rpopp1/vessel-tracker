export type Notice = { kind: "error" | "empty" | "info"; text: string };

export function noticeFor(s: { apiError: boolean; stats: { total: number } | null; filtersActive: boolean }): Notice | null {
  if (s.apiError) {
    return { kind: "error", text: "Cannot reach the API - is it running on port 8000? Showing the last data received." };
  }
  if (s.stats && s.stats.total === 0) {
    return s.filtersActive
      ? { kind: "empty", text: "No vessels match these filters." }
      : {
          kind: "info",
          text: "No tankers tracked yet - the collector may still be starting. Positions appear after each vessel's static data arrives (a few minutes).",
        };
  }
  return null;
}
