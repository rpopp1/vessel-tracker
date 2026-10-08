import { describe, expect, it } from "vitest";
import { emptyFilters, filtersToParams, normalizeBbox, toggle } from "./filters";

describe("toggle", () => {
  it("adds and removes", () => {
    expect(toggle(["a"], "b")).toEqual(["a", "b"]);
    expect(toggle(["a", "b"], "a")).toEqual(["b"]);
  });
});

describe("normalizeBbox", () => {
  it("leaves a normal view alone", () => {
    expect(normalizeBbox(10, -5, 20, 5)).toEqual([10, -5, 20, 5]);
  });
  it("wraps longitudes past the antimeridian", () => {
    expect(normalizeBbox(-250, -10, -200, 10)).toEqual([110, -10, 160, 10]);
    expect(normalizeBbox(170, -10, 190, 10)).toEqual([170, -10, -170, 10]);
  });
  it("covers the world when the view spans 360 degrees or more", () => {
    expect(normalizeBbox(-400, -90, 400, 90)).toEqual([-180, -90, 180, 90]);
  });
  it("clamps latitude", () => {
    expect(normalizeBbox(0, -100, 10, 100)).toEqual([0, -90, 10, 90]);
  });
});

describe("filtersToParams", () => {
  it("serializes repeated and scalar params", () => {
    const p = filtersToParams(
      { ...emptyFilters, size_class: ["MR", "Suezmax"], laden: false, nav_status: [0] },
      { bbox: [1, 2, 3, 4], zoom: 7 },
    );
    expect(p.getAll("size_class")).toEqual(["MR", "Suezmax"]);
    expect(p.get("laden")).toBe("false");
    expect(p.getAll("nav_status")).toEqual(["0"]);
    expect(p.get("bbox")).toBe("1,2,3,4");
    expect(p.get("zoom")).toBe("7");
  });
  it("omits empty filters", () => {
    expect(filtersToParams(emptyFilters).toString()).toBe("");
  });
});
