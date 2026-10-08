import { describe, expect, it } from "vitest";
import { chipModel, mergeFeatures, nextRetryDelay, parseFrame, wsUrl } from "./liveLogic";

const feat = (mmsi: unknown, extra: object = {}): GeoJSON.Feature => ({
  type: "Feature", geometry: { type: "Point", coordinates: [0, 0] }, properties: { mmsi, ...extra },
});

describe("wsUrl", () => {
  it("uses ws for http", () => expect(wsUrl({ protocol: "http:", host: "a:1" })).toBe("ws://a:1/ws/positions"));
  it("uses wss for https", () => expect(wsUrl({ protocol: "https:", host: "a" })).toBe("wss://a/ws/positions"));
});

describe("nextRetryDelay", () => {
  it("doubles", () => expect(nextRetryDelay(1000)).toBe(2000));
  it("caps at 30000", () => {
    expect(nextRetryDelay(20000)).toBe(30000);
    expect(nextRetryDelay(30000)).toBe(30000);
  });
});

describe("parseFrame", () => {
  it("returns null for malformed / non-object / unknown", () => {
    expect(parseFrame("{nope")).toBeNull();
    expect(parseFrame("5")).toBeNull();
    expect(parseFrame("null")).toBeNull();
    expect(parseFrame("[]")).toBeNull();
    expect(parseFrame('{"type":"hello"}')).toBeNull();
  });
  it("returns null when features is not an array", () => {
    expect(parseFrame('{"type":"positions","features":{}}')).toBeNull();
    expect(parseFrame('{"type":"positions"}')).toBeNull();
  });
  it("filters features without numeric mmsi", () => {
    const r = parseFrame(JSON.stringify({ type: "positions", features: [feat(1), feat("2"), feat(null), { type: "Feature" }, null] }));
    expect(r).toEqual({ type: "positions", features: [feat(1)] });
  });
  it("parses error frames", () => {
    expect(parseFrame('{"type":"error","detail":"service unavailable"}')).toEqual({ type: "error", detail: "service unavailable" });
    expect(parseFrame('{"type":"error"}')).toBeNull();
  });
});

describe("mergeFeatures", () => {
  it("returns a new map, later wins, does not mutate", () => {
    const cur = new Map([[1, feat(1, { v: 1 })]]);
    const out = mergeFeatures(cur, [feat(1, { v: 2 }), feat(2), feat(2, { v: 3 })]);
    expect(out).not.toBe(cur);
    expect(cur.size).toBe(1);
    expect(cur.get(1)!.properties!.v).toBe(1);
    expect(out.get(1)!.properties!.v).toBe(2);
    expect(out.get(2)!.properties!.v).toBe(3);
  });
});

describe("chipModel", () => {
  const now = Date.parse("2026-01-01T12:00:00Z");
  const ago = (s: number) => new Date(now - s * 1000).toISOString();
  it("live and fresh", () => {
    expect(chipModel("live", ago(10), now)).toEqual({ label: "Live", tone: "ok", ageText: "10s ago" });
  });
  it("age formats", () => {
    expect(chipModel("live", ago(89), now).ageText).toBe("89s ago");
    expect(chipModel("live", ago(120), now).ageText).toBe("2 min ago");
    expect(chipModel("live", ago(5400), now).ageText).toBe("2 h ago (feed may be down)");
  });
  it("stale warns with suffix", () => {
    expect(chipModel("live", ago(301), now)).toEqual({ label: "Live", tone: "warn", ageText: "5 min ago (feed may be down)" });
  });
  it("no data is warn without suffix", () => {
    expect(chipModel("live", null, now)).toEqual({ label: "Live", tone: "warn", ageText: "no data yet" });
  });
  it("connecting and off labels", () => {
    expect(chipModel("connecting", ago(10), now).label).toBe("Reconnecting");
    expect(chipModel("connecting", ago(10), now).tone).toBe("idle");
    expect(chipModel("off", ago(10), now)).toEqual({ label: "Zoom in for live updates", tone: "idle", ageText: "10s ago" });
  });
  it("error detail forces warn and appends to label", () => {
    const m = chipModel("live", ago(10), now, "temporarily unavailable");
    expect(m.tone).toBe("warn");
    expect(m.label).toBe("Live - temporarily unavailable");
    expect(chipModel("live", ago(10), now, "invalid subscription").tone).toBe("ok");
  });
});
