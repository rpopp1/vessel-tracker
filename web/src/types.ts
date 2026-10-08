export type LiveState = "live" | "connecting" | "off";
export type Meta = {
  size_classes: { name: string; cargo_group: string }[];
  fade_hours: number;
  stale_hours: number;
};
export type Stats = {
  total: number;
  newest_ts: string | null;
  size_class: Record<string, number>;
  cargo_group: Record<string, number>;
  laden: Record<string, number>;
  flag: Record<string, number>;
  nav_status: Record<string, number>;
};
export type VesselDetail = {
  mmsi: number; name: string | null; imo: number | null; callsign: string | null; flag: string | null;
  length_m: number | null; beam_m: number | null; size_class: string; cargo_group: string;
  draught_m: number | null; laden: boolean | null; destination: string | null; eta: string | null;
  position: { lon: number; lat: number; ts: string; sog: number | null; cog: number | null;
              heading: number | null; nav_status: number | null } | null;
};
export type SearchHit = {
  mmsi: number; name: string | null; imo: number | null; size_class: string; flag: string | null;
  lon: number | null; lat: number | null;
};
