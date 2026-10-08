import { useEffect, useState } from "react";
import { getJSON } from "./api";
import MapView from "./components/MapView";
import { emptyFilters, type Filters } from "./filters";
import type { Meta } from "./types";

export default function App() {
  const [filters] = useState<Filters>(emptyFilters);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [selected, setSelected] = useState<number | null>(null);

  useEffect(() => { getJSON<Meta>("/api/meta").then(setMeta).catch(console.error); }, []);

  return (
    <div className="app">
      <MapView filters={filters} meta={meta} onSelect={setSelected} track={null} flyTo={null} />
      {selected !== null && <div className="debug">selected {selected}</div>}
    </div>
  );
}
