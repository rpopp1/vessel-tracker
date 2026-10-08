import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef, useState } from "react";
import { getJSON } from "../api";
import { DEFAULT_COLOR, SIZE_COLORS } from "../colors";
import { CLUSTER_ZOOM, filtersToParams, normalizeBbox, type Filters } from "../filters";
import { pickTextFont, vesselOpacityExpression } from "../mapStyle";
import type { LiveState, Meta } from "../types";

type Props = {
  filters: Filters;
  meta: Meta | null;
  onSelect: (mmsi: number) => void;
  track: GeoJSON.Feature | null;
  flyTo: { lon: number; lat: number; nonce: number } | null;
  onLiveState?: (s: LiveState) => void;
};

const STYLE = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";
const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

function triangle(solid: boolean): ImageData {
  const s = 32;
  const c = document.createElement("canvas");
  c.width = c.height = s;
  const g = c.getContext("2d")!;
  g.beginPath();
  g.moveTo(s / 2, 3); g.lineTo(s - 6, s - 4); g.lineTo(s / 2, s - 9); g.lineTo(6, s - 4);
  g.closePath();
  if (solid) { g.fillStyle = "#000"; g.fill(); } else { g.lineWidth = 3; g.strokeStyle = "#000"; g.stroke(); }
  return g.getImageData(0, 0, s, s);
}

export default function MapView({ filters, meta, onSelect, track, flyTo }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [ready, setReady] = useState(false);
  const [view, setView] = useState<{ bbox: number[]; zoom: number } | null>(null);
  const featuresRef = useRef<Map<number, GeoJSON.Feature>>(new Map());
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const fadeHours = meta?.fade_hours ?? 2;
  const fadeHoursRef = useRef(fadeHours);
  fadeHoursRef.current = fadeHours;

  // create the map once
  useEffect(() => {
    const map = new maplibregl.Map({ container: el.current!, style: STYLE, center: [0, 25], zoom: 2, attributionControl: { compact: true } });
    mapRef.current = map;
    const updateView = () => {
      const b = map.getBounds();
      setView({ bbox: normalizeBbox(b.getWest(), b.getSouth(), b.getEast(), b.getNorth()), zoom: Math.floor(map.getZoom()) });
    };
    map.on("load", () => {
      map.addImage("tri-solid", triangle(true), { sdf: true });
      map.addImage("tri-hollow", triangle(false), { sdf: true });
      map.addSource("vessels", { type: "geojson", data: EMPTY });
      map.addSource("track", { type: "geojson", data: EMPTY });
      map.addLayer({ id: "track", type: "line", source: "track", paint: { "line-color": "#ffffff", "line-width": 2, "line-opacity": 0.8 } });
      map.addLayer({
        id: "clusters", type: "circle", source: "vessels", filter: ["has", "cluster"],
        paint: {
          "circle-color": "#3b82f6", "circle-opacity": 0.65,
          "circle-radius": ["step", ["get", "count"], 12, 10, 16, 50, 22, 200, 28],
        },
      });
      // reuse a glyph font the basemap style actually serves, rather than guessing a name
      const textFont = pickTextFont(map.getStyle());
      if (!textFont) console.warn("no text-font found in basemap style; cluster counts may not render");
      map.addLayer({
        id: "cluster-count", type: "symbol", source: "vessels", filter: ["has", "cluster"],
        layout: {
          "text-field": ["get", "count"], "text-size": 12, "text-allow-overlap": true,
          ...(textFont ? { "text-font": textFont } : {}),
        },
        paint: { "text-color": "#fff" },
      });
      map.addLayer({
        id: "vessels", type: "symbol", source: "vessels", filter: ["!", ["has", "cluster"]],
        layout: {
          "icon-image": ["case", ["==", ["get", "laden"], false], "tri-hollow", "tri-solid"],
          "icon-rotate": ["to-number", ["get", "cog"], 0],
          "icon-rotation-alignment": "map",
          "icon-allow-overlap": true,
          "icon-size": 0.55,
        },
        paint: {
          "icon-color": ["match", ["get", "size_class"],
            ...Object.entries(SIZE_COLORS).flat(), DEFAULT_COLOR] as unknown as maplibregl.ExpressionSpecification,
          "icon-opacity": vesselOpacityExpression(fadeHoursRef.current) as unknown as maplibregl.ExpressionSpecification,
        },
      });
      map.on("click", "vessels", (e) => {
        const mmsi = e.features?.[0]?.properties?.mmsi;
        if (mmsi) onSelectRef.current(Number(mmsi));
      });
      map.on("click", "clusters", (e) => {
        const c = (e.features?.[0]?.geometry as GeoJSON.Point).coordinates as [number, number];
        map.easeTo({ center: c, zoom: map.getZoom() + 2 });
      });
      for (const layer of ["vessels", "clusters"]) {
        map.on("mouseenter", layer, () => (map.getCanvas().style.cursor = "pointer"));
        map.on("mouseleave", layer, () => (map.getCanvas().style.cursor = ""));
      }
      map.on("moveend", updateView);
      updateView();
      setReady(true);
    });
    return () => map.remove();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // fetch vessels whenever the view or filters change
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !view) return;
    const ctl = new AbortController();
    const params = filtersToParams(filters, { bbox: view.bbox, zoom: view.zoom });
    getJSON<GeoJSON.FeatureCollection>(`/api/vessels?${params}`, ctl.signal)
      .then((fc) => {
        featuresRef.current = new Map(
          fc.features.filter((f) => !f.properties?.cluster).map((f) => [f.properties!.mmsi as number, f]),
        );
        (map.getSource("vessels") as maplibregl.GeoJSONSource).setData(fc);
      })
      .catch((e) => { if (e.name !== "AbortError") console.error(e); });
    return () => ctl.abort();
  }, [ready, view, filters]);

  useEffect(() => {
    const src = mapRef.current?.getSource("track") as maplibregl.GeoJSONSource | undefined;
    src?.setData(track ?? EMPTY);
  }, [track, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    map.setPaintProperty("vessels", "icon-opacity", vesselOpacityExpression(fadeHours) as unknown as maplibregl.ExpressionSpecification);
  }, [fadeHours, ready]);

  useEffect(() => {
    if (flyTo) mapRef.current?.flyTo({ center: [flyTo.lon, flyTo.lat], zoom: Math.max(mapRef.current.getZoom(), 8) });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flyTo?.nonce, flyTo?.lon, flyTo?.lat]);

  void CLUSTER_ZOOM;
  return <div ref={el} className="map" />;
}
