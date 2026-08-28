import { describe, expect, it } from "vitest";

import { demoProject } from "./demoProject";
import { createSceneEvent } from "./sceneEventFactory";

describe("scene event factory", () => {
  it("creates useful professional defaults without writing duration policy", () => {
    expect(createSceneEvent("enter", {
      eventId: "event/new-enter",
      selectedSlot: 3,
      project: demoProject,
    })).toEqual({
      event_id: "event/new-enter",
      kind: "enter",
      slot: 3,
      character_id: "character/yuuka",
    });
    expect(createSceneEvent("halocue.ba:screen-shake", {
      eventId: "event/new-shake",
      selectedSlot: 3,
      project: demoProject,
    })).toEqual({
      event_id: "event/new-shake",
      kind: "halocue.ba:screen-shake",
      intensity: 0.35,
      wait_for_completion: true,
    });
    expect(createSceneEvent("halocue.ba:screen-text", {
      eventId: "event/new-screen-text",
      selectedSlot: 3,
      project: demoProject,
    })).toEqual({
      event_id: "event/new-screen-text",
      kind: "halocue.ba:screen-text",
      text: "屏幕文字",
      wait_for_completion: true,
    });
    expect(createSceneEvent("character-motion", {
      eventId: "event/new-motion",
      selectedSlot: 3,
      selectedCharacterId: "character/koyuki",
      project: demoProject,
    })).toEqual({
      event_id: "event/new-motion",
      kind: "character-motion",
      slot: 3,
      character_id: "character/koyuki",
      motion_id: "motion/nod",
      wait_for_completion: true,
    });
  });

  it("rejects an event that the shared registry cannot render", () => {
    expect(() => createSceneEvent("camera", {
      eventId: "event/camera",
      selectedSlot: 1,
      project: demoProject,
    })).toThrow(/unsupported/);
  });
});
