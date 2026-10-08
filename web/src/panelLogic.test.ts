import { describe, expect, it } from "vitest";
import { cargoLabel, hasActiveFilters, sortedNavKeys, topFlags } from "./panelLogic";
import { emptyFilters } from "./filters";

describe("topFlags", () => {
  it("returns top N by count, ties alphabetical", () => {
    expect(topFlags({ B: 5, A: 5, C: 9, D: 1 }, [], 3)).toEqual(["C", "A", "B"]);
  });
  it("appends selected flags not in list, without duplicates", () => {
    expect(topFlags({ A: 3, B: 2 }, ["B", "Z"], 1)).toEqual(["A", "B", "Z"]);
  });
  it("handles undefined stats", () => {
    expect(topFlags(undefined, ["X"])).toEqual(["X"]);
  });
  it("defaults limit to 10", () => {
    const m: Record<string, number> = {};
    for (let i = 0; i < 15; i++) m["F" + String(i).padStart(2, "0")] = 100 - i;
    expect(topFlags(m, [])).toHaveLength(10);
  });
});

describe("hasActiveFilters", () => {
  it("false for empty", () => {
    expect(hasActiveFilters({ ...emptyFilters })).toBe(false);
  });
  it("true for each field", () => {
    expect(hasActiveFilters({ ...emptyFilters, size_class: ["MR"] })).toBe(true);
    expect(hasActiveFilters({ ...emptyFilters, cargo_group: ["crude"] })).toBe(true);
    expect(hasActiveFilters({ ...emptyFilters, laden: false })).toBe(true);
    expect(hasActiveFilters({ ...emptyFilters, flag: ["PA"] })).toBe(true);
    expect(hasActiveFilters({ ...emptyFilters, nav_status: [1] })).toBe(true);
    expect(hasActiveFilters({ ...emptyFilters, min_speed: 0 })).toBe(true);
    expect(hasActiveFilters({ ...emptyFilters, max_speed: 5 })).toBe(true);
  });
  it("independent of key order", () => {
    const f = { nav_status: [], flag: [], laden: null, cargo_group: [], size_class: [], max_speed: null, min_speed: null };
    expect(hasActiveFilters(f)).toBe(false);
  });
});

describe("sortedNavKeys", () => {
  it("sorts numerically", () => {
    expect(sortedNavKeys({ "15": 1, "5": 1, "1": 1, "0": 1 })).toEqual(["0", "1", "5", "15"]);
  });
  it("handles undefined", () => {
    expect(sortedNavKeys(undefined)).toEqual([]);
  });
});

describe("cargoLabel", () => {
  it("maps known keys", () => {
    expect(cargoLabel("mostly_crude")).toBe("Mostly crude");
    expect(cargoLabel("products_coastal")).toBe("Products / coastal");
  });
  it("falls back for unknown keys", () => {
    expect(cargoLabel("foo_bar")).toBe("Foo bar");
  });
});
