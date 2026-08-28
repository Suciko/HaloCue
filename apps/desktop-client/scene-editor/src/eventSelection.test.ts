import { describe, expect, it } from "vitest";

import {
  repairEventSelection,
  selectEventIds,
  selectionAfterEventDeletion,
} from "./eventSelection";

const events = ["a", "b", "c", "d"].map((event_id) => ({ event_id }));
const initial = {
  selectedEventId: "b",
  selectedEventIds: ["b"],
  eventSelectionAnchorId: "b",
};

describe("event multi-selection", () => {
  it("replaces, toggles, and preserves canonical event order", () => {
    expect(selectEventIds(events, initial, "d", "replace")).toEqual({
      selectedEventId: "d",
      selectedEventIds: ["d"],
      eventSelectionAnchorId: "d",
    });
    expect(selectEventIds(events, initial, "d", "toggle")).toEqual({
      selectedEventId: "d",
      selectedEventIds: ["b", "d"],
      eventSelectionAnchorId: "d",
    });
    expect(selectEventIds(events, initial, "b", "toggle")).toEqual(initial);
  });

  it("selects contiguous and additive ranges from a stable anchor", () => {
    expect(selectEventIds(events, initial, "d", "range")).toEqual({
      selectedEventId: "d",
      selectedEventIds: ["b", "c", "d"],
      eventSelectionAnchorId: "b",
    });
    const disjoint = selectEventIds(events, initial, "d", "toggle");
    expect(selectEventIds(events, disjoint, "a", "add-range")).toEqual({
      selectedEventId: "a",
      selectedEventIds: ["a", "b", "c", "d"],
      eventSelectionAnchorId: "d",
    });
  });

  it("repairs stale IDs and chooses the nearest surviving deletion position", () => {
    expect(repairEventSelection(events, {
      selectedEventId: "missing",
      selectedEventIds: ["missing", "c"],
      eventSelectionAnchorId: "missing",
    })).toEqual({
      selectedEventId: "c",
      selectedEventIds: ["c"],
      eventSelectionAnchorId: "c",
    });
    expect(selectionAfterEventDeletion(events, ["b", "c"])).toEqual({
      selectedEventId: "d",
      selectedEventIds: ["d"],
      eventSelectionAnchorId: "d",
    });
    expect(selectionAfterEventDeletion(events, ["c", "d"]).selectedEventId).toBe("b");
  });
});
