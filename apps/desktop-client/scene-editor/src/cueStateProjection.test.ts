import { describe, expect, it } from "vitest";

import { buildDescriptor } from "./descriptor";
import { demoProject } from "./demoProject";
import { projectCueState, projectSceneAtCue, VISIBLE_STAGE_SLOT_COUNT } from "./cueStateProjection";
import type { Scene } from "./types";

function sceneWithOrderedChanges(): Scene {
  return {
    scene_id: "scene/projection-order",
    cues: [
      {
        cue_id: "cue/one",
        events: [
          { event_id: "event/bg/one", kind: "background", resource_id: "background/one" },
          { event_id: "event/enter/a", kind: "enter", slot: 1, character_id: "character/a", expression_id: "expression/a" },
        ],
      },
      {
        cue_id: "cue/two",
        events: [
          { event_id: "event/exit/a", kind: "exit", slot: 1 },
          { event_id: "event/enter/b", kind: "enter", slot: 1, character_id: "character/b", motion_id: "motion/b" },
          { event_id: "event/advanced", kind: "vendor:test", payload: true },
          { event_id: "event/dialogue", kind: "dialogue", text: "第二拍" },
          { event_id: "event/bg/two", kind: "background", resource_id: "background/two" },
        ],
      },
    ],
  };
}

describe("CueStateProjection", () => {
  it("replays enter, exit and re-entry in event order without leaking advanced events into stage state", () => {
    const projection = projectSceneAtCue(sceneWithOrderedChanges(), "cue/two");

    expect(projection.beforeCue.slots).toEqual(["character/a", null, null, null, null]);
    expect(projection.afterCue.slots).toEqual(["character/b", null, null, null, null]);
    expect(projection.afterCue.actorStateEvents[0]).toEqual(expect.objectContaining({
      event_id: "event/enter/b",
      motion_id: "motion/b",
    }));
    expect(projection.beforeCue.backgroundEvent?.resource_id).toBe("background/one");
    expect(projection.afterCue.backgroundEvent?.resource_id).toBe("background/two");
    expect(projection.orderedEvents.map((event) => event.event_id)).toEqual([
      "event/bg/one", "event/enter/a", "event/exit/a", "event/enter/b",
      "event/advanced", "event/dialogue", "event/bg/two",
    ]);
    expect(projection.renderableEvents.some((event) => event.event_id === "event/advanced")).toBe(false);
  });

  it("exposes stable current-Cue event indices for contextual editors", () => {
    const projection = projectSceneAtCue(sceneWithOrderedChanges(), "cue/two");

    expect(projection.cueEventIndices).toEqual({ dialogue: 3, background: 4 });
    expect(projection.dialogueEvent?.text).toBe("第二拍");
    expect(projection.cueBackgroundEvent?.resource_id).toBe("background/two");
  });

  it("keeps the five-slot projection equal to descriptor actor slots and state", () => {
    const project = structuredClone(demoProject);
    const selectedCueId = "cue/conference/002";
    const projection = projectCueState(project, selectedCueId);
    const descriptor = buildDescriptor(project, selectedCueId);

    expect(projection.afterCue.slots).toHaveLength(VISIBLE_STAGE_SLOT_COUNT);
    expect(descriptor.actors.map((actor) => actor.character_id)).toEqual(projection.afterCue.slots);
    expect(descriptor.actors[4]).toEqual(expect.objectContaining({
      character_id: "character/koyuki",
      motion_id: "motion/appear",
    }));
  });

  it("ignores out-of-range positions instead of changing the five visible slots", () => {
    const scene = sceneWithOrderedChanges();
    scene.cues[1].events.push({
      event_id: "event/enter/outside",
      kind: "enter",
      slot: 6,
      character_id: "character/outside",
    });

    const projection = projectSceneAtCue(scene, "cue/two");
    expect(projection.afterCue.slots).toHaveLength(VISIBLE_STAGE_SLOT_COUNT);
    expect(projection.afterCue.slots).not.toContain("character/outside");
  });
});
