import { describe, expect, it } from "vitest";

import { eventDropPlacement, reorderEvents } from "./eventReorder";

const events = ["a", "b", "c", "d"].map((event_id) => ({ event_id }));
const ids = (items: readonly { event_id: string }[]) => items.map((item) => item.event_id);

describe("event reorder", () => {
  it("derives a stable before/after target from the row midpoint", () => {
    expect(eventDropPlacement(124, 100, 50)).toBe("before");
    expect(eventDropPlacement(125, 100, 50)).toBe("after");
    expect(eventDropPlacement(149, 100, 50)).toBe("after");
  });

  it("uses the same relative placement for direction and drop commands", () => {
    expect(ids(reorderEvents(events, "b", -1))).toEqual(["b", "a", "c", "d"]);
    expect(ids(reorderEvents(events, "b", { targetEventId: "a", placement: "before" })))
      .toEqual(["b", "a", "c", "d"]);
    expect(ids(reorderEvents(events, "b", 1))).toEqual(["a", "c", "b", "d"]);
    expect(ids(reorderEvents(events, "b", { targetEventId: "c", placement: "after" })))
      .toEqual(["a", "c", "b", "d"]);
  });

  it("moves to either side of a non-adjacent stable target", () => {
    expect(ids(reorderEvents(events, "a", { targetEventId: "d", placement: "before" })))
      .toEqual(["b", "c", "a", "d"]);
    expect(ids(reorderEvents(events, "a", { targetEventId: "d", placement: "after" })))
      .toEqual(["b", "c", "d", "a"]);
  });

  it("returns the original array for equivalent and invalid moves", () => {
    expect(reorderEvents(events, "a", -1)).toBe(events);
    expect(reorderEvents(events, "a", { targetEventId: "b", placement: "before" })).toBe(events);
    expect(reorderEvents(events, "missing", 1)).toBe(events);
    expect(reorderEvents(events, "a", { targetEventId: "missing", placement: "after" })).toBe(events);
  });
});
