import { describe, expect, it } from "vitest";

import { buildRenderTimeline, eventDurationMs } from "./renderTimeline";
import {
  createSceneEventRegistry,
  sceneEventDefinitions,
  sceneEventRegistry,
} from "./sceneEventRegistry";
import type { SceneDescriptor } from "./types";

const descriptor = (events: Array<Record<string, unknown>>): SceneDescriptor => ({
  schema_version: "scene-descriptor/1.0",
  scene_id: "scene/registry",
  presentation: {},
  background: null,
  initial_background: null,
  actors: [],
  initial_actors: [],
  events: events as SceneDescriptor["events"],
});

describe("scene event registry seam", () => {
  it("exposes a unique, stable definition for every render event", () => {
    const definitions = sceneEventDefinitions();
    expect(new Set(definitions.map((event) => event.kind)).size).toBe(definitions.length);
    expect(definitions.every((event) => sceneEventRegistry.isTimelineSupported(event.kind))).toBe(true);
    expect(definitions.every((event) => sceneEventRegistry.isDescriptorRenderable(event.kind))).toBe(true);
    expect(sceneEventRegistry.definition("character-motion")).toEqual(expect.objectContaining({
      visual_only: true,
      default_duration_ms: 500,
      supports_non_blocking: true,
    }));
    expect(sceneEventRegistry.definition("halocue.ba:background-pan")).toEqual(expect.objectContaining({
      supports_non_blocking: true,
    }));
    expect(sceneEventRegistry.definition("halocue.ba:screen-shake")).toEqual(expect.objectContaining({
      supports_non_blocking: true,
    }));
    expect(sceneEventRegistry.definition("halocue.ba:screen-text")).toEqual(expect.objectContaining({
      supports_non_blocking: true,
    }));
    expect(sceneEventDefinitions()
      .filter((event) => ![
        "character-motion",
        "halocue.ba:background-pan",
        "halocue.ba:screen-shake",
        "halocue.ba:screen-text",
      ].includes(event.kind))
      .every((event) => event.supports_non_blocking === false)).toBe(true);
  });

  it("drives fixed defaults and the dialogue policy", () => {
    const events = sceneEventDefinitions().map((event, index) => ({
      event_id: `event/${index}`,
      kind: event.kind,
      ...(event.kind === "dialogue" ? { text: "你好。" } : {}),
    }));
    const timeline = buildRenderTimeline(descriptor(events));
    expect(timeline.events.map((event) => event.duration_ms)).toEqual(
      sceneEventDefinitions().map((event) => event.kind === "dialogue" ? 842 : event.default_duration_ms),
    );
  });

  it("keeps explicit duration validation at the registry seam", () => {
    expect(eventDurationMs({ event_id: "event/short", kind: "wait", duration_ms: 1.1 })).toBe(2);
    expect(() => eventDurationMs({ event_id: "event/bad", kind: "wait", duration_ms: 0 })).toThrow(/positive/);
    expect(() => eventDurationMs({ event_id: "event/bad", kind: "camera" })).toThrow(/unsupported/);
  });

  it("rejects malformed injected manifests before callers can use them", () => {
    expect(() => createSceneEventRegistry({ schema_version: "scene-events/1.0", events: [] })).toThrow(/schema/);
  });
});
