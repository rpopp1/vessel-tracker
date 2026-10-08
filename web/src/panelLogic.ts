import { emptyFilters, type Filters } from "./filters";

export const CARGO_LABELS: Record<string, string> = {
  crude: "Crude", mostly_crude: "Mostly crude", crude_or_products: "Crude or products",
  mostly_products: "Mostly products", products: "Products", products_coastal: "Products / coastal", unknown: "Unknown",
};

export function cargoLabel(key: string): string {
  if (CARGO_LABELS[key]) return CARGO_LABELS[key];
  const s = key.replace(/_/g, " ").trim();
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : key;
}

export function topFlags(statsFlag: Record<string, number> | undefined, selected: string[], limit = 10): string[] {
  const flags = Object.entries(statsFlag ?? {})
    .sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0))
    .slice(0, limit)
    .map(([k]) => k);
  for (const f of selected) if (!flags.includes(f)) flags.push(f);
  return flags;
}

const sameList = <T,>(a: T[], b: T[]) => a.length === b.length && a.every((v, i) => v === b[i]);

export function hasActiveFilters(f: Filters): boolean {
  const e = emptyFilters;
  return !(
    sameList(f.size_class, e.size_class) && sameList(f.cargo_group, e.cargo_group) &&
    sameList(f.flag, e.flag) && sameList(f.nav_status, e.nav_status) &&
    f.laden === e.laden && f.min_speed === e.min_speed && f.max_speed === e.max_speed
  );
}

export function sortedNavKeys(navStatus: Record<string, number> | undefined): string[] {
  return Object.keys(navStatus ?? {}).sort((a, b) => Number(a) - Number(b));
}

export function navKeysWithSelected(navStatus: Record<string, number> | undefined, selected: number[]): string[] {
  const keys = new Set(sortedNavKeys(navStatus));
  for (const s of selected) if (Number.isFinite(s)) keys.add(String(s));
  return [...keys].sort((a, b) => Number(a) - Number(b));
}
