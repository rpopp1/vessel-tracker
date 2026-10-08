import { useEffect, useState } from "react";
import { getJSON } from "../api";
import type { SearchHit } from "../types";

export default function SearchBar({ onPick }: { onPick: (h: SearchHit) => void }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const term = q.trim();

  useEffect(() => {
    if (term.length < 2) { setHits([]); return; }
    const ctl = new AbortController();
    const t = setTimeout(() => {
      getJSON<SearchHit[]>(`/api/search?q=${encodeURIComponent(term)}`, ctl.signal)
        .then((r) => { if (!ctl.signal.aborted) setHits(r); })
        .catch(() => { if (!ctl.signal.aborted) setHits([]); });
    }, 250);
    return () => { clearTimeout(t); ctl.abort(); };
  }, [term]);

  const clear = () => { setQ(""); setHits([]); };

  return (
    <div className="search">
      <input
        value={q}
        placeholder="Search name, MMSI or IMO"
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Escape") clear(); }}
      />
      {term.length >= 2 && (
        <ul>
          {hits.length === 0 && <li className="none">No matches</li>}
          {hits.map((h) => (
            <li key={h.mmsi}>
              <button onClick={() => { onPick(h); clear(); }}>
                {h.name || "(unnamed)"} <small>{h.size_class} - MMSI {h.mmsi}{h.imo ? ` - IMO ${h.imo}` : ""}</small>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
