import { describe, expect, it } from "vitest";

import { eventDropPlacement, reorderEventBlock, reorderEvents } from "./eventReorder";

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

  it("moves a canonical selected block without changing its internal order", () => {
    expect(ids(reorderEventBlock(events, ["b", "d"], {
      targetEventId: "a",
      placement: "before",
    }))).toEqual(["b", "d", "a", "c"]);
    expect(ids(reorderEventBlock(events, ["a", "c"], {
      targetEventId: "d",
      placement: "after",
    }))).toEqual(["b", "d", "a", "c"]);
  });

  it("moves a selected block by one external item", () => {
    const longer = ["a", "b", "c", "d", "e"].map((event_id) => ({ event_id }));
    expect(ids(reorderEventBlock(longer, ["b", "c"], -1)))
      .toEqual(["b", "c", "a", "d", "e"]);
    expect(ids(reorderEventBlock(longer, ["b", "c"], 1)))
      .toEqual(["a", "d", "b", "c", "e"]);
  });

  it("treats drops inside the block and equivalent boundaries as no-ops", () => {
    expect(reorderEventBlock(events, ["b", "c"], {
      targetEventId: "c",
      placement: "after",
    })).toBe(events);
    expect(reorderEventBlock(events, ["b", "c"], {
      targetEventId: "a",
      placement: "after",
    })).toBe(events);
    expect(reorderEventBlock(events, ["missing"], 1)).toBe(events);
  });
});
