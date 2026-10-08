import { NAV_STATUS } from "./filters";
import type { VesselDetail } from "./types";

export type DetailRow = { label: string; value: string; tag?: "inferred" | "estimated" };

const dash = (v: unknown): string => (v === null || v === undefined || v === "" ? "-" : String(v));

/** Locale-independent "YYYY-MM-DD HH:mm UTC"; returns the raw string if unparseable. */
export function formatIso(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

export function detailRows(v: VesselDetail, fmt: (iso: string) => string = formatIso): DetailRow[] {
  const p = v.position;
  return [
    { label: "Size class", value: dash(v.size_class) },
    { label: "Cargo group", value: dash(v.cargo_group.replace(/_/g, " ")), tag: "inferred" },
    { label: "Laden", value: v.laden === null || v.laden === undefined ? "-" : v.laden ? "Laden" : "Ballast", tag: "estimated" },
    { label: "Flag", value: dash(v.flag) },
    { label: "MMSI / IMO", value: `${v.mmsi} / ${dash(v.imo)}` },
    { label: "Dimensions", value: v.length_m ? `${v.length_m} x ${v.beam_m ?? "-"} m` : "-" },
    { label: "Draught", value: v.draught_m ? `${v.draught_m} m` : "-" },
    { label: "Destination", value: dash(v.destination) },
    { label: "ETA", value: v.eta ? fmt(v.eta) : "-" },
    { label: "Speed / course", value: p ? `${dash(p.sog)} kn / ${dash(p.cog)} deg` : "-" },
    { label: "Status", value: p?.nav_status != null ? (NAV_STATUS[p.nav_status] ?? String(p.nav_status)) : "-" },
    { label: "Last seen", value: p ? fmt(p.ts) : "-" },
  ];
}

export function trackStatus(pointCount: number | undefined): string {
  const n = pointCount ?? 0;
  return n < 2
    ? "No track recorded in this period (history only exists while the collector runs)"
    : `${n} positions`;
}

export function trackRange(hours: number, now: Date): { from: string; to: string } {
  return { from: new Date(now.getTime() - hours * 3600_000).toISOString(), to: now.toISOString() };
}

export function hasDrawableTrack(f: GeoJSON.Feature | null): boolean {
  const g = f?.geometry;
  if (!g) return false;
  if (g.type === "LineString") return g.coordinates.length >= 2;
  if (g.type === "MultiLineString") return g.coordinates.some((l) => l.length >= 2);
  return false;
}
