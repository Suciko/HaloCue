import { describe, expect, it } from "vitest";

import { demoProject } from "./demoProject";
import {
  createEditorEvent,
  eventEditorDefinition,
  eventEditorDefinitions,
  eventSummary,
} from "./eventEditorCatalog";
import { sceneEventDefinitions } from "./sceneEventRegistry";

const context = {
  eventId: "event/catalog-test",
  selectedSlot: 3,
  project: demoProject,
};

describe("event editor catalog seam", () => {
  it("has an editor definition for every registered timeline event", () => {
    const definitions = eventEditorDefinitions();
    expect(definitions.map((item) => item.kind)).toEqual(sceneEventDefinitions().map((item) => item.kind));
    expect(definitions.every((item) => typeof item.label === "string" && item.label.length > 0)).toBe(true);
    expect(definitions.every((item) => typeof item.create === "function")).toBe(true);
  });

  it("creates typed defaults through one catalog entry", () => {
    expect(createEditorEvent("enter", context)).toEqual(expect.objectContaining({
      event_id: context.eventId,
      kind: "enter",
      slot: 3,
      character_id: "character/yuuka",
    }));
    expect(createEditorEvent("halocue.ba:background-pan", context)).toEqual(expect.objectContaining({
      kind: "halocue.ba:background-pan",
      pan_x: 0.035,
      pan_y: 0,
    }));
  });

  it("keeps summaries stable and does not mutate event payloads", () => {
    const event = { event_id: "event/summary", kind: "dialogue", text: "你好" };
    expect(eventSummary(event)).toBe("你好");
    expect(event).toEqual({ event_id: "event/summary", kind: "dialogue", text: "你好" });
  });

  it("uses a generic fallback only for registered events without custom fields", () => {
    const definition = eventEditorDefinition("wait");
    expect(definition).toEqual(expect.objectContaining({ kind: "wait", icon: "wait", fields: [] }));
    expect(eventEditorDefinition("vendor:unknown")).toBeUndefined();
    expect(() => createEditorEvent("vendor:unknown", context)).toThrow(/unsupported/);
  });
});
