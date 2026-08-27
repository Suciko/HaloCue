import { describe, expect, it } from "vitest";

import { duplicateEventBlock } from "./eventDuplication";
import type { CueEvent } from "./types";

const events: CueEvent[] = [
  { event_id: "a", kind: "wait", duration_ms: 100 },
  { event_id: "b", kind: "plugin:custom", nested: { curve: [1, 2, 3] } },
  { event_id: "c", kind: "dialogue", text: "原文" },
  { event_id: "d", kind: "wait", duration_ms: 200 },
];

describe("event block duplication", () => {
  it("copies a disjoint selection as one canonical ordered block", () => {
    const result = duplicateEventBlock(events, ["d", "b"], (_source, index) => `copy-${index}`);
    expect(result.events.map((event) => event.event_id))
      .toEqual(["a", "b", "c", "d", "copy-0", "copy-1"]);
    expect(result.duplicateEventIds).toEqual(["copy-0", "copy-1"]);
    expect(result.events[4]).toEqual({
      event_id: "copy-0",
      kind: "plugin:custom",
      nested: { curve: [1, 2, 3] },
    });
    expect(result.events[5]).toEqual({ event_id: "copy-1", kind: "wait", duration_ms: 200 });
  });

  it("deep-clones unknown payload fields", () => {
    const result = duplicateEventBlock(events, ["b"], () => "copy-b");
    const duplicate = result.events[2];
    expect(duplicate).not.toBe(events[1]);
    expect(duplicate.nested).not.toBe(events[1].nested);
    (duplicate.nested as { curve: number[] }).curve.push(4);
    expect(events[1].nested).toEqual({ curve: [1, 2, 3] });
  });

  it("rejects empty or colliding generated IDs", () => {
    expect(() => duplicateEventBlock(events, ["a"], () => "a")).toThrow("fresh");
    expect(() => duplicateEventBlock(events, ["a"], () => "")).toThrow("fresh");
  });
});
