import { describe, expect, it } from "vitest";
import { noticeFor } from "./notice";

const ok = (total: number) => ({ total });

describe("noticeFor", () => {
  it("api error -> error banner", () => {
    expect(noticeFor({ apiError: true, stats: null, filtersActive: false })).toEqual({
      kind: "error",
      text: "Cannot reach the API - is it running on port 8000? Showing the last data received.",
    });
  });
  it("api error takes precedence over empty results", () => {
    expect(noticeFor({ apiError: true, stats: ok(0), filtersActive: true })?.kind).toBe("error");
    expect(noticeFor({ apiError: true, stats: ok(0), filtersActive: false })?.kind).toBe("error");
  });
  it("zero results with filters -> empty", () => {
    expect(noticeFor({ apiError: false, stats: ok(0), filtersActive: true })).toEqual({
      kind: "empty", text: "No vessels match these filters.",
    });
  });
  it("zero results without filters -> info", () => {
    expect(noticeFor({ apiError: false, stats: ok(0), filtersActive: false })).toEqual({
      kind: "info",
      text: "No tankers tracked yet - the collector may still be starting. Positions appear after each vessel's static data arrives (a few minutes).",
    });
  });
  it("vessels present -> nothing", () => {
    expect(noticeFor({ apiError: false, stats: ok(3), filtersActive: true })).toBeNull();
    expect(noticeFor({ apiError: false, stats: ok(3), filtersActive: false })).toBeNull();
  });
  it("stats not loaded yet -> nothing", () => {
    expect(noticeFor({ apiError: false, stats: null, filtersActive: true })).toBeNull();
    expect(noticeFor({ apiError: false, stats: null, filtersActive: false })).toBeNull();
  });
});
