import { describe, expect, it } from "vitest";
import { detailRows, hasDrawableTrack, trackRange, trackStatus } from "./vesselLogic";
import type { VesselDetail } from "./types";

const base: VesselDetail = {
  mmsi: 123456789, name: "TEST", imo: 9999999, callsign: null, flag: "PA",
  length_m: 250, beam_m: 44, size_class: "VLCC", cargo_group: "mostly_crude",
  draught_m: 18.5, laden: true, destination: "ROTTERDAM", eta: "2026-10-10T12:00:00Z",
  position: { lon: 1, lat: 2, ts: "2026-10-08T01:02:03Z", sog: 12.3, cog: 45, heading: null, nav_status: 0 },
};
const row = (v: VesselDetail, label: string) => detailRows(v, (s) => `F(${s})`).find((r) => r.label === label)!;

describe("detailRows", () => {
  it("formats a full vessel", () => {
    expect(row(base, "Cargo group")).toEqual({ label: "Cargo group", value: "mostly crude", tag: "inferred" });
    expect(row(base, "Laden")).toEqual({ label: "Laden", value: "Laden", tag: "estimated" });
    expect(row(base, "MMSI / IMO").value).toBe("123456789 / 9999999");
    expect(row(base, "Dimensions").value).toBe("250 x 44 m");
    expect(row(base, "Draught").value).toBe("18.5 m");
    expect(row(base, "ETA").value).toBe("F(2026-10-10T12:00:00Z)");
    expect(row(base, "Last seen").value).toBe("F(2026-10-08T01:02:03Z)");
    expect(row(base, "Speed / course").value).toBe("12.3 kn / 45 deg");
    expect(row(base, "Status").value).toBe("Under way (engine)");
  });
  it("uses dashes for missing data", () => {
    const v = { ...base, flag: "", imo: null, length_m: null, draught_m: null, laden: null, destination: null, eta: null, position: null };
    const g = (l: string) => row(v, l).value;
    expect(g("Flag")).toBe("-");
    expect(g("MMSI / IMO")).toBe("123456789 / -");
    expect(g("Dimensions")).toBe("-");
    expect(g("Draught")).toBe("-");
    expect(g("Laden")).toBe("-");
    expect(g("Destination")).toBe("-");
    expect(g("ETA")).toBe("-");
    expect(g("Speed / course")).toBe("-");
    expect(g("Status")).toBe("-");
    expect(g("Last seen")).toBe("-");
  });
  it("labels ballast, partial dimensions, unknown nav status", () => {
    const v = { ...base, laden: false, beam_m: null, position: { ...base.position!, nav_status: 99, sog: null } };
    expect(row(v, "Laden").value).toBe("Ballast");
    expect(row(v, "Dimensions").value).toBe("250 x - m");
    expect(row(v, "Status").value).toBe("99");
    expect(row(v, "Speed / course").value).toBe("- kn / 45 deg");
  });
  it("default formatter is locale independent", () => {
    expect(detailRows(base).find((r) => r.label === "ETA")!.value).toBe("2026-10-10 12:00 UTC");
  });
});

describe("trackStatus", () => {
  const none = "No track recorded in this period (history only exists while the collector runs)";
  it("handles few points", () => {
    expect(trackStatus(undefined)).toBe(none);
    expect(trackStatus(0)).toBe(none);
    expect(trackStatus(1)).toBe(none);
    expect(trackStatus(2)).toBe("2 positions");
    expect(trackStatus(40)).toBe("40 positions");
  });
});

describe("trackRange", () => {
  it("returns ISO strings hours apart", () => {
    const now = new Date("2026-10-08T12:00:00.000Z");
    expect(trackRange(24, now)).toEqual({ from: "2026-10-07T12:00:00.000Z", to: "2026-10-08T12:00:00.000Z" });
    expect(trackRange(168, now).from).toBe("2026-10-01T12:00:00.000Z");
  });
});

describe("hasDrawableTrack", () => {
  const f = (geometry: unknown) => ({ type: "Feature", properties: {}, geometry }) as GeoJSON.Feature;
  it("rejects null/empty/degenerate", () => {
    expect(hasDrawableTrack(null)).toBe(false);
    expect(hasDrawableTrack(f({ type: "MultiLineString", coordinates: [] }))).toBe(false);
    expect(hasDrawableTrack(f({ type: "MultiLineString", coordinates: [[[0, 0]]] }))).toBe(false);
    expect(hasDrawableTrack(f({ type: "Point", coordinates: [0, 0] }))).toBe(false);
    expect(hasDrawableTrack(f(null))).toBe(false);
  });
  it("accepts lines with >= 2 points", () => {
    expect(hasDrawableTrack(f({ type: "MultiLineString", coordinates: [[[0, 0]], [[0, 0], [1, 1]]] }))).toBe(true);
    expect(hasDrawableTrack(f({ type: "LineString", coordinates: [[0, 0], [1, 1]] }))).toBe(true);
    expect(hasDrawableTrack(f({ type: "LineString", coordinates: [[0, 0]] }))).toBe(false);
  });
});

describe("detailRows null safety", () => {
  const rows = (v: unknown) => detailRows(v as VesselDetail, (s) => `F(${s})`);
  const get = (r: ReturnType<typeof rows>, l: string) => r.find((x) => x.label === l)!;
  it("null cargo_group", () => {
    const r = rows({ ...base, cargo_group: null });
    expect(get(r, "Cargo group")).toEqual({ label: "Cargo group", value: "-", tag: "inferred" });
  });
  it("undefined size_class", () => {
    expect(get(rows({ ...base, size_class: undefined }), "Size class").value).toBe("-");
  });
  it("null position and partial position", () => {
    const r = rows({ ...base, position: null });
    expect(get(r, "Speed / course").value).toBe("-");
    expect(get(r, "Status").value).toBe("-");
    expect(get(r, "Last seen").value).toBe("-");
    const p = rows({ ...base, position: { lon: 1, lat: 2 } });
    expect(get(p, "Speed / course").value).toBe("- kn / - deg");
    expect(get(p, "Status").value).toBe("-");
    expect(get(p, "Last seen").value).toBe("-");
  });
  it("entirely sparse object", () => {
    const r = rows({});
    expect(r).toHaveLength(12);
    expect(get(r, "Cargo group")).toEqual({ label: "Cargo group", value: "-", tag: "inferred" });
    expect(get(r, "Laden")).toEqual({ label: "Laden", value: "-", tag: "estimated" });
    for (const l of ["Size class", "Flag", "Dimensions", "Draught", "Destination", "ETA", "Speed / course", "Status", "Last seen"]) {
      expect(get(r, l).value).toBe("-");
    }
    expect(get(r, "MMSI / IMO").value).toBe("- / -");
  });
});
