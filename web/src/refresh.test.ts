import { describe, expect, it } from "vitest";
import { REFRESH_INTERVAL_MS, shouldRefresh } from "./refresh";

describe("refresh", () => {
  it("polls every 60 seconds", () => {
    expect(REFRESH_INTERVAL_MS).toBe(60_000);
  });
  it("refreshes only while the tab is visible", () => {
    expect(shouldRefresh(true)).toBe(true);
    expect(shouldRefresh(false)).toBe(false);
  });
});
