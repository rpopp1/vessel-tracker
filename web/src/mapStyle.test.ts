import { describe, expect, it } from "vitest";
import { pickTextFont, vesselOpacityExpression } from "./mapStyle";

describe("vesselOpacityExpression", () => {
  it("uses the given fade threshold", () => {
    const a = vesselOpacityExpression(2) as unknown[];
    const b = vesselOpacityExpression(6) as unknown[];
    expect((a[1] as unknown[])[2]).toBe(2);
    expect((b[1] as unknown[])[2]).toBe(6);
  });
  it("orders stale fade, then unknown laden, then default", () => {
    expect(vesselOpacityExpression(2)).toEqual([
      "case",
      [">", ["to-number", ["get", "age_h"], 0], 2], 0.35,
      ["==", ["get", "laden"], null], 0.6,
      1,
    ]);
  });
});

describe("pickTextFont", () => {
  it("returns the first layer's text-font array", () => {
    const style = { layers: [
      { id: "a", layout: {} },
      { id: "b", layout: { "text-font": ["Noto Sans Regular"] } },
      { id: "c", layout: { "text-font": ["Other"] } },
    ] };
    expect(pickTextFont(style)).toEqual(["Noto Sans Regular"]);
  });
  it("skips layers without layout or text-font", () => {
    expect(pickTextFont({ layers: [{ id: "a" }, { id: "b", layout: { "text-font": ["X", "Y"] } }] })).toEqual(["X", "Y"]);
  });
  it("ignores non-array, empty, non-string and stops-form values", () => {
    const style = { layers: [
      { layout: { "text-font": "Foo" } },
      { layout: { "text-font": [] } },
      { layout: { "text-font": [1, 2] } },
      { layout: { "text-font": { stops: [[0, ["A"]]] } } },
      { layout: { "text-font": ["Good"] } },
    ] };
    expect(pickTextFont(style)).toEqual(["Good"]);
    expect(pickTextFont({ layers: [{ layout: { "text-font": { stops: [] } } }] })).toBeUndefined();
  });
  it("returns undefined for an empty style", () => {
    expect(pickTextFont({})).toBeUndefined();
    expect(pickTextFont({ layers: [] })).toBeUndefined();
  });
});
