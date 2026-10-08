import type { LiveState } from "./types";

export type Frame =
  | { type: "positions"; features: GeoJSON.Feature[] }
  | { type: "error"; detail: string };

export const INITIAL_RETRY_MS = 1000;
export const MAX_RETRY_MS = 30000;
export const STALE_SECONDS = 300;

export function wsUrl(loc: { protocol: string; host: string }): string {
  const proto = loc.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${loc.host}/ws/positions`;
}

export function nextRetryDelay(current: number): number {
  return Math.min(current * 2, MAX_RETRY_MS);
}

export function parseFrame(data: string): Frame | null {
  let m: unknown;
  try { m = JSON.parse(data); } catch { return null; }
  if (typeof m !== "object" || m === null || Array.isArray(m)) return null;
  const o = m as Record<string, unknown>;
  if (o.type === "positions") {
    if (!Array.isArray(o.features)) return null;
    const features = o.features.filter((f): f is GeoJSON.Feature => {
      if (typeof f !== "object" || f === null) return false;
      const p = (f as { properties?: unknown }).properties;
      return typeof p === "object" && p !== null && typeof (p as { mmsi?: unknown }).mmsi === "number";
    });
    return { type: "positions", features };
  }
  if (o.type === "error" && typeof o.detail === "string") return { type: "error", detail: o.detail };
  return null;
}

export function mergeFeatures(
  current: Map<number, GeoJSON.Feature>,
  incoming: GeoJSON.Feature[],
): Map<number, GeoJSON.Feature> {
  const out = new Map(current);
  for (const f of incoming) out.set(f.properties!.mmsi as number, f);
  return out;
}

export function chipModel(
  live: LiveState,
  newestTs: string | null,
  now: number,
  errorDetail?: string | null,
): { label: string; tone: "ok" | "warn" | "idle"; ageText: string } {
  const parsed = newestTs ? new Date(newestTs).getTime() : NaN;
  const age = Number.isNaN(parsed) ? null : Math.max(0, Math.round((now - parsed) / 1000));
  let ageText = age === null ? "no data yet"
    : age < 90 ? `${age}s ago`
    : age < 5400 ? `${Math.round(age / 60)} min ago`
    : `${Math.round(age / 3600)} h ago`;
  const stale = age === null || age > STALE_SECONDS;
  if (age !== null && stale) ageText += " (feed may be down)";
  let label = live === "live" ? "Live" : live === "connecting" ? "Reconnecting" : "Zoom in for live updates";
  const feedError = errorDetail === "temporarily unavailable" || errorDetail === "service unavailable";
  if (feedError) label += ` - ${errorDetail}`;
  const tone = feedError || stale ? "warn" : live === "live" ? "ok" : "idle";
  return { label, tone, ageText };
}

export const HEALTHY_OPEN_MS = 5000;

export function retryAfterClose(
  prevDelay: number,
  openedForMs: number,
  gotPositions: boolean,
): { waitMs: number; nextDelay: number } {
  if (gotPositions || openedForMs >= HEALTHY_OPEN_MS) {
    return { waitMs: INITIAL_RETRY_MS, nextDelay: INITIAL_RETRY_MS };
  }
  return { waitMs: prevDelay, nextDelay: nextRetryDelay(prevDelay) };
}
