/** How often the map re-fetches vessels on its own (age_h is computed server-side at fetch time). */
export const REFRESH_INTERVAL_MS = 60_000;

/** Background tabs do not poll; a visible tab does. */
export function shouldRefresh(visible: boolean): boolean {
  return visible;
}
