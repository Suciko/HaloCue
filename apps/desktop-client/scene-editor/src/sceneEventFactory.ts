import { createEditorEvent } from "./eventEditorCatalog";
import type { CueEvent, HaloCueProject } from "./types";

export type SceneEventFactoryContext = {
  eventId: string;
  selectedSlot: number;
  selectedCharacterId?: string | null;
  project: HaloCueProject;
};

/** Compatibility seam for callers that create events through the old factory name. */
export function createSceneEvent(
  kind: string,
  { eventId, selectedSlot, selectedCharacterId, project }: SceneEventFactoryContext,
): CueEvent {
  return createEditorEvent(kind, { eventId, selectedSlot, selectedCharacterId, project });
}
