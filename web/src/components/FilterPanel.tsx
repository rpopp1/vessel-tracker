import { useEffect, useRef, useState } from "react";
import { getJSON } from "../api";
import { SIZE_COLORS } from "../colors";
import { emptyFilters, filtersToParams, NAV_STATUS, toggle, type Filters } from "../filters";
import { CARGO_LABELS, cargoLabel, hasActiveFilters, sortedNavKeys, topFlags } from "../panelLogic";
import type { Meta, Stats } from "../types";

type Props = { filters: Filters; onChange: (f: Filters) => void; meta: Meta | null; onStats?: (s: Stats | null) => void };

export default function FilterPanel({ filters, onChange, meta, onStats }: Props) {
  const [stats, setStats] = useState<Stats | null>(null);
  const onStatsRef = useRef(onStats);
  onStatsRef.current = onStats;

  useEffect(() => {
    const ctl = new AbortController();
    const load = () =>
      getJSON<Stats>(`/api/stats?${filtersToParams(filters)}`, ctl.signal)
        .then((s) => { setStats(s); onStatsRef.current?.(s); })
        // keep previous counts on failure; stats stays null only if never loaded
        .catch((e) => { if (e.name !== "AbortError") console.error(e); });
    load();
    const t = setInterval(load, 15000);
    return () => { ctl.abort(); clearInterval(t); };
  }, [filters]);

  const n = (m: Record<string, number> | undefined, k: string) => m?.[k] ?? 0;
  const anyActive = hasActiveFilters(filters);
  const flags = topFlags(stats?.flag, filters.flag);

  const row = (key: string, label: string, count: number, active: boolean, onClick: () => void, color?: string) => (
    <button key={key} className={`row ${active ? "active" : ""}`} onClick={onClick}>
      {color && <span className="swatch" style={{ background: color }} />}
      <span className="label">{label}</span>
      <span className="count">{count.toLocaleString()}</span>
    </button>
  );

  return (
    <aside className="panel left">
      <h1>Tankers <small>{stats ? stats.total.toLocaleString() : "-"}</small></h1>
      {anyActive && <button className="clear" onClick={() => onChange(emptyFilters)}>Clear filters</button>}

      <h2>Size class</h2>
      {(meta?.size_classes ?? []).map((c) =>
        row(c.name, c.name, n(stats?.size_class, c.name), filters.size_class.includes(c.name),
          () => onChange({ ...filters, size_class: toggle(filters.size_class, c.name) }), SIZE_COLORS[c.name]))}

      <h2>Cargo group <em>inferred</em></h2>
      {Object.keys(CARGO_LABELS).map((k) =>
        row(k, cargoLabel(k), n(stats?.cargo_group, k), filters.cargo_group.includes(k),
          () => onChange({ ...filters, cargo_group: toggle(filters.cargo_group, k) })))}

      <h2>Laden / ballast <em>estimated</em></h2>
      {row("laden", "Laden", n(stats?.laden, "laden"), filters.laden === true,
        () => onChange({ ...filters, laden: filters.laden === true ? null : true }))}
      {row("ballast", "Ballast", n(stats?.laden, "ballast"), filters.laden === false,
        () => onChange({ ...filters, laden: filters.laden === false ? null : false }))}

      <h2>Flag</h2>
      {flags.map((f) => row(f, f, n(stats?.flag, f), filters.flag.includes(f),
        () => onChange({ ...filters, flag: toggle(filters.flag, f) })))}

      <h2>Status</h2>
      {sortedNavKeys(stats?.nav_status).map((k) =>
        row(k, NAV_STATUS[Number(k)] ?? `Status ${k}`, n(stats?.nav_status, k), filters.nav_status.includes(Number(k)),
          () => onChange({ ...filters, nav_status: toggle(filters.nav_status, Number(k)) })))}
    </aside>
  );
}
