import { sceneEventRegistry } from "./sceneEventRegistry";
import type { CueEvent, HaloCueProject } from "./types";

export type SceneEventFactoryContext = {
  eventId: string;
  selectedSlot: number;
  project: HaloCueProject;
};

/**
 * Creates the smallest valid event payload for the professional command menu.
 * Effect-specific knobs stay here, while kind support, labels, and duration
 * policy remain owned by the Scene Event Registry Module.
 */
export function createSceneEvent(
  kind: string,
  { eventId, selectedSlot, project }: SceneEventFactoryContext,
): CueEvent {
  if (!sceneEventRegistry.isTimelineSupported(kind)) {
    throw new RangeError(`unsupported scene event kind ${kind}`);
  }
  const firstCharacter = project.characters[0]?.character_id;
  switch (kind) {
    case "dialogue":
      return { event_id: eventId, kind, text: "" };
    case "enter":
      return {
        event_id: eventId,
        kind,
        slot: selectedSlot,
        ...(firstCharacter ? { character_id: firstCharacter } : {}),
      };
    case "exit":
      return { event_id: eventId, kind, slot: selectedSlot };
    case "halocue.ba:background-pan":
      return { event_id: eventId, kind, pan_x: 0.035, pan_y: 0 };
    case "halocue.ba:screen-shake":
      return { event_id: eventId, kind, intensity: 0.35 };
    case "halocue.ba:screen-text":
      return { event_id: eventId, kind, text: "屏幕文字" };
    case "halocue.ba:hit-effect":
      return { event_id: eventId, kind, slot: selectedSlot, intensity: 0.5 };
    default:
      return { event_id: eventId, kind };
  }
}

