import { useEffect, useRef, useState } from "react";
import { getJSON } from "../api";
import type { VesselDetail } from "../types";
import { detailRows, hasDrawableTrack, trackRange, trackStatus } from "../vesselLogic";

const RANGES = [{ label: "24h", hours: 24 }, { label: "7d", hours: 168 }, { label: "30d", hours: 720 }];

export default function VesselPanel({ mmsi, onClose, onTrack }: {
  mmsi: number; onClose: () => void; onTrack: (t: GeoJSON.Feature | null) => void;
}) {
  const [v, setV] = useState<VesselDetail | null>(null);
  const [error, setError] = useState(false);
  const [range, setRange] = useState<number | null>(null);
  const [trackInfo, setTrackInfo] = useState("");
  const onTrackRef = useRef(onTrack);
  onTrackRef.current = onTrack;

  useEffect(() => {
    const ctl = new AbortController();
    setV(null); setError(false); setRange(null); setTrackInfo(""); onTrackRef.current(null);
    getJSON<VesselDetail>(`/api/vessels/${mmsi}`, ctl.signal)
      .then((d) => { if (!ctl.signal.aborted) setV(d); })
      .catch(() => { if (!ctl.signal.aborted) setError(true); });
    return () => { ctl.abort(); onTrackRef.current(null); };
  }, [mmsi]);

  useEffect(() => {
    onTrackRef.current(null);
    if (range === null) { setTrackInfo(""); return; }
    const ctl = new AbortController();
    const { from, to } = trackRange(range, new Date());
    setTrackInfo("Loading track...");
    getJSON<GeoJSON.Feature>(`/api/vessels/${mmsi}/track?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`, ctl.signal)
      .then((t) => {
        if (ctl.signal.aborted) return;
        setTrackInfo(trackStatus(t.properties?.point_count));
        onTrackRef.current(hasDrawableTrack(t) ? t : null);
      })
      .catch(() => {
        if (ctl.signal.aborted) return;
        onTrackRef.current(null);
        setTrackInfo("Could not load track");
      });
    return () => ctl.abort();
  }, [range, mmsi]);

  return (
    <aside className="panel right">
      <button className="close" onClick={onClose} aria-label="Close">x</button>
      {error && <p>Vessel not found.</p>}
      {!v && !error && <p>Loading...</p>}
      {v && (
        <>
          <h1>{v.name || "(unnamed)"}</h1>
          <dl>
            {detailRows(v).map((r) => (
              <Row key={r.label} label={r.label} value={r.value} tag={r.tag} />
            ))}
          </dl>
          <div className="tracks">
            <span>Track</span>
            {RANGES.map((r) => (
              <button key={r.label} className={range === r.hours ? "on" : ""} onClick={() => setRange(range === r.hours ? null : r.hours)}>{r.label}</button>
            ))}
          </div>
          {trackInfo && <p className="muted">{trackInfo}</p>}
        </>
      )}
    </aside>
  );
}

function Row({ label, value, tag }: { label: string; value: string; tag?: string }) {
  return (
    <>
      <dt>{label}{tag && <em>{tag}</em>}</dt>
      <dd>{value}</dd>
    </>
  );
}
