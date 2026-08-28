import { isDescriptorRenderable } from "./sceneEventRegistry";
import type { Cue, CueEvent, HaloCueProject, Scene } from "./types";

export const VISIBLE_STAGE_SLOT_COUNT = 5;

export type ProjectedStageState = {
  /** State after replaying every renderable stage event through this point. */
  slots: Array<string | null>;
  actorStateEvents: Array<CueEvent | null>;
  backgroundEvent: CueEvent | null;
};

export type CueStateProjection = {
  scene: Scene;
  cue: Cue;
  cueIndex: number;
  beforeCue: ProjectedStageState;
  afterCue: ProjectedStageState;
  orderedEvents: CueEvent[];
  renderableEvents: CueEvent[];
  cueEvents: CueEvent[];
  dialogueEvent: CueEvent | null;
  /** Background authored in this Cue, if any. It may intentionally omit a resource. */
  cueBackgroundEvent: CueEvent | null;
  cueEventIndices: {
    dialogue: number | null;
    background: number | null;
  };
};

function emptyStageState(): ProjectedStageState {
  return {
    slots: Array.from({ length: VISIBLE_STAGE_SLOT_COUNT }, () => null),
    actorStateEvents: Array.from({ length: VISIBLE_STAGE_SLOT_COUNT }, () => null),
    backgroundEvent: null,
  };
}

function snapshot(state: ProjectedStageState): ProjectedStageState {
  return {
    slots: [...state.slots],
    actorStateEvents: [...state.actorStateEvents],
    backgroundEvent: state.backgroundEvent,
  };
}

function visibleSlot(event: CueEvent): number | null {
  return Number.isInteger(event.slot)
    && Number(event.slot) >= 1
    && Number(event.slot) <= VISIBLE_STAGE_SLOT_COUNT
    ? Number(event.slot)
    : null;
}

function applyEvent(state: ProjectedStageState, event: CueEvent): void {
  const slot = visibleSlot(event);
  if (event.kind === "enter" && slot !== null) {
    const characterId = event.character_id || null;
    state.slots[slot - 1] = characterId;
    state.actorStateEvents[slot - 1] = characterId ? event : null;
    return;
  }
  if (event.kind === "exit" && slot !== null) {
    state.slots[slot - 1] = null;
    state.actorStateEvents[slot - 1] = null;
    return;
  }
  if (event.kind === "background" && event.resource_id) {
    state.backgroundEvent = event;
  }
}

function eventIndex(cue: Cue, kind: string): number | null {
  const index = cue.events.findIndex((event) => event.kind === kind);
  return index >= 0 ? index : null;
}

export function firstScene(project: HaloCueProject): Scene {
  const scene = project.chapters[0]?.scenes[0];
  if (!scene) throw new Error("项目至少需要一个场景");
  return scene;
}

export function sceneById(project: HaloCueProject, sceneId?: string): Scene {
  if (!sceneId) return firstScene(project);
  for (const chapter of project.chapters) {
    const scene = chapter.scenes.find((item) => item.scene_id === sceneId);
    if (scene) return scene;
  }
  throw new Error(`项目中不存在场景 ${sceneId}`);
}

export function projectSceneAtCue(scene: Scene, cueId: string): CueStateProjection {
  const cueIndex = scene.cues.findIndex((cue) => cue.cue_id === cueId);
  if (cueIndex < 0) throw new Error(`场景中不存在 Cue ${cueId}`);
  const cue = scene.cues[cueIndex];
  const state = emptyStageState();
  const orderedEvents: CueEvent[] = [];
  let beforeCue = snapshot(state);

  for (let index = 0; index <= cueIndex; index += 1) {
    if (index === cueIndex) beforeCue = snapshot(state);
    for (const event of scene.cues[index].events) {
      orderedEvents.push(event);
      applyEvent(state, event);
    }
  }

  const dialogueIndex = eventIndex(cue, "dialogue");
  const backgroundIndex = eventIndex(cue, "background");
  return {
    scene,
    cue,
    cueIndex,
    beforeCue,
    afterCue: snapshot(state),
    orderedEvents,
    renderableEvents: orderedEvents.filter((event) => isDescriptorRenderable(event.kind)),
    cueEvents: cue.events,
    dialogueEvent: dialogueIndex === null ? null : cue.events[dialogueIndex],
    cueBackgroundEvent: backgroundIndex === null ? null : cue.events[backgroundIndex],
    cueEventIndices: {
      dialogue: dialogueIndex,
      background: backgroundIndex,
    },
  };
}

export function projectCueState(
  project: HaloCueProject,
  cueId: string,
  options: { sceneId?: string } = {},
): CueStateProjection {
  return projectSceneAtCue(sceneById(project, options.sceneId), cueId);
}

export function characterMotionEventForCue(
  cue: Cue,
  slot: number,
  characterId?: string | null,
): CueEvent | null {
  const reversed = [...cue.events].reverse();
  const explicit = reversed.find((event) => (
    event.kind === "character-motion"
    && event.slot === slot
    && (!characterId || !event.character_id || event.character_id === characterId)
  ));
  if (explicit) return explicit;
  return reversed.find((event) => (
    (event.kind === "enter" && event.slot === slot && event.motion_id !== undefined)
    || (event.kind === "dialogue" && Boolean(characterId)
      && event.character_id === characterId && event.motion_id !== undefined)
  )) || null;
}
