export const CLUSTER_ZOOM = 5;

export type Filters = {
  size_class: string[];
  cargo_group: string[];
  laden: boolean | null;
  flag: string[];
  nav_status: number[];
  min_speed: number | null;
  max_speed: number | null;
};

export const emptyFilters: Filters = {
  size_class: [], cargo_group: [], laden: null, flag: [], nav_status: [], min_speed: null, max_speed: null,
};

export const NAV_STATUS: Record<number, string> = {
  0: "Under way (engine)", 1: "At anchor", 2: "Not under command", 3: "Restricted maneuverability",
  4: "Constrained by draught", 5: "Moored", 6: "Aground", 7: "Fishing", 8: "Under way (sailing)", 15: "Undefined",
};

export function toggle<T>(list: T[], v: T): T[] {
  return list.includes(v) ? list.filter((x) => x !== v) : [...list, v];
}

const clampLat = (x: number) => Math.max(-90, Math.min(90, x));
const wrapLon = (x: number) => ((((x + 180) % 360) + 360) % 360) - 180;

export function normalizeBbox(w: number, s: number, e: number, n: number): [number, number, number, number] {
  if (e - w >= 360) return [-180, clampLat(s), 180, clampLat(n)];
  return [wrapLon(w), clampLat(s), wrapLon(e), clampLat(n)];
}

export function filtersToParams(f: Filters, extra: { bbox?: number[]; zoom?: number } = {}): URLSearchParams {
  const p = new URLSearchParams();
  if (extra.bbox) p.set("bbox", extra.bbox.join(","));
  if (extra.zoom !== undefined) p.set("zoom", String(extra.zoom));
  f.size_class.forEach((v) => p.append("size_class", v));
  f.cargo_group.forEach((v) => p.append("cargo_group", v));
  if (f.laden !== null) p.set("laden", String(f.laden));
  f.flag.forEach((v) => p.append("flag", v));
  f.nav_status.forEach((v) => p.append("nav_status", String(v)));
  if (f.min_speed !== null) p.set("min_speed", String(f.min_speed));
  if (f.max_speed !== null) p.set("max_speed", String(f.max_speed));
  return p;
}
