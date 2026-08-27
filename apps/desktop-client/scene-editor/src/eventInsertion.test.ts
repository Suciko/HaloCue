import { describe, expect, it } from "vitest";

import { eventInsertionIndex } from "./eventInsertion";

const events = ["a", "b", "c"].map((event_id) => ({ event_id }));

describe("event insertion", () => {
  it("resolves before and after against a stable anchor ID", () => {
    expect(eventInsertionIndex(events, { anchorEventId: "b", placement: "before" })).toBe(1);
    expect(eventInsertionIndex(events, { anchorEventId: "b", placement: "after" })).toBe(2);
  });

  it("appends when the anchor is absent or stale", () => {
    expect(eventInsertionIndex(events)).toBe(3);
    expect(eventInsertionIndex(events, { anchorEventId: null, placement: "before" })).toBe(3);
    expect(eventInsertionIndex(events, { anchorEventId: "missing", placement: "after" })).toBe(3);
  });

  it("returns zero for an empty Cue", () => {
    expect(eventInsertionIndex([], { anchorEventId: "missing", placement: "before" })).toBe(0);
  });
});
