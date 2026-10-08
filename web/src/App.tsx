import { useEffect, useState } from "react";
import { getJSON } from "./api";
import FilterPanel from "./components/FilterPanel";
import MapView from "./components/MapView";
import SearchBar from "./components/SearchBar";
import VesselPanel from "./components/VesselPanel";
import { emptyFilters, type Filters } from "./filters";
import StatusChip from "./components/StatusChip";
import type { LiveState, Meta, Stats } from "./types";

export default function App() {
  const [filters, setFilters] = useState<Filters>(emptyFilters);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [track, setTrack] = useState<GeoJSON.Feature | null>(null);
  const [flyTo, setFlyTo] = useState<{ lon: number; lat: number; nonce: number } | null>(null);

  const [live, setLive] = useState<LiveState>("off");
  const [liveError, setLiveError] = useState<string | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => { getJSON<Meta>("/api/meta").then(setMeta).catch(console.error); }, []);

  return (
    <div className="app">
      <FilterPanel filters={filters} onChange={setFilters} meta={meta} onStats={setStats} />
      <SearchBar onPick={(h) => {
        setSelected(h.mmsi);
        if (h.lon !== null && h.lat !== null) setFlyTo({ lon: h.lon, lat: h.lat, nonce: Date.now() });
      }} />
      {selected !== null && <VesselPanel key={selected} mmsi={selected} onClose={() => setSelected(null)} onTrack={setTrack} />}
      <MapView filters={filters} meta={meta} onSelect={setSelected} track={track} flyTo={flyTo} onLiveState={setLive} onLiveError={setLiveError} />
      <StatusChip live={live} newestTs={stats?.newest_ts ?? null} errorDetail={liveError} />
    </div>
  );
}
