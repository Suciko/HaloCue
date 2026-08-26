import { create } from "zustand";

import { demoProject } from "./demoProject";
import {
  isProject,
  loadEditorMode,
  projectRepository,
  saveEditorMode,
  type ProjectRepository,
} from "./projectRepository";
import type {
  Cue,
  CueEvent,
  EditorMode,
  HaloCueProject,
  InspectorTab,
  QuickEffectKind,
  Scene,
} from "./types";
import { isDescriptorRenderable } from "./sceneEventRegistry";

const clone = <T,>(value: T): T => structuredClone(value);

function localId(prefix: string): string {
  return `${prefix}/${crypto.randomUUID()}`;
}

export { isProject } from "./projectRepository";

export function firstScene(project: HaloCueProject): Scene {
  const scene = project.chapters[0]?.scenes[0];
  if (!scene) throw new Error("项目至少需要一个场景");
  return scene;
}

export function stageAtCue(scene: Scene, cueId: string): Array<string | null> {
  const slots: Array<string | null> = [null, null, null, null, null];
  for (const cue of scene.cues) {
    for (const event of cue.events) {
      if ((event.kind === "enter" || event.kind === "exit") && event.slot) {
        slots[event.slot - 1] = event.kind === "enter" ? event.character_id || null : null;
      }
    }
    if (cue.cue_id === cueId) break;
  }
  return slots;
}

export function advancedEventCount(cue: Cue): number {
  return cue.events.filter((event) => !isDescriptorRenderable(event.kind)).length;
}

type HistoryEntry = { project: HaloCueProject; selectedCueId: string; selectedEventId: string | null };

type EditorState = {
  project: HaloCueProject;
  mode: EditorMode;
  inspectorTab: InspectorTab;
  selectedCueId: string;
  selectedSlot: number;
  selectedEventId: string | null;
  history: HistoryEntry[];
  future: HistoryEntry[];
  dirty: boolean;
  revision: number;
  setMode: (mode: EditorMode) => void;
  setInspectorTab: (tab: InspectorTab) => void;
  selectCue: (cueId: string) => void;
  selectSlot: (slot: number) => void;
  selectEvent: (eventId: string | null) => void;
  updateProjectTitle: (title: string) => void;
  updateDialogue: (patch: Partial<CueEvent>) => void;
  updateEnvironment: (patch: Partial<CueEvent>) => void;
  setSlotCharacter: (slot: number, characterId: string | null) => void;
  swapSlots: (source: number, target: number) => void;
  updateCharacterState: (slot: number, patch: Partial<CueEvent>) => void;
  addQuickEffect: (kind: QuickEffectKind) => void;
  addCue: (placement: "before" | "after") => void;
  duplicateCue: () => void;
  deleteCue: () => void;
  moveCue: (sourceCueId: string, targetCueId: string) => void;
  updateEvent: (eventId: string, patch: Partial<CueEvent>) => void;
  moveEvent: (eventId: string, direction: -1 | 1) => void;
  undo: () => void;
  redo: () => void;
  replaceProject: (project: HaloCueProject) => void;
  markSaved: () => void;
  resetDemo: () => void;
};

function initialSelection(project: HaloCueProject) {
  const scene = firstScene(project);
  const cue = scene.cues[0];
  if (!cue) throw new Error("场景至少需要一个 Cue");
  return { cueId: cue.cue_id, eventId: cue.events[0]?.event_id || null };
}

export function createProjectStore(repository: ProjectRepository = projectRepository) {
  const initialProject = repository.loadDraft();
  const initial = initialSelection(initialProject);

  return create<EditorState>((set, get) => {
  const commit = (
    mutator: (project: HaloCueProject, cue: Cue, scene: Scene) => void,
    selection?: Partial<Pick<EditorState, "selectedCueId" | "selectedEventId">>,
  ) => {
    const state = get();
    const project = clone(state.project);
    const scene = firstScene(project);
    const cue = scene.cues.find((item) => item.cue_id === state.selectedCueId);
    if (!cue) return;
    mutator(project, cue, scene);
    repository.saveDraft(project);
    set({
      project,
      selectedCueId: selection?.selectedCueId ?? state.selectedCueId,
      selectedEventId: selection?.selectedEventId === undefined
        ? state.selectedEventId : selection.selectedEventId,
      history: [...state.history.slice(-59), {
        project: state.project,
        selectedCueId: state.selectedCueId,
        selectedEventId: state.selectedEventId,
      }],
      future: [],
      dirty: true,
      revision: state.revision + 1,
    });
  };

  return {
    project: initialProject,
    mode: loadEditorMode(),
    inspectorTab: "dialogue",
    selectedCueId: initial.cueId,
    selectedSlot: 1,
    selectedEventId: initial.eventId,
    history: [],
    future: [],
    dirty: false,
    revision: 0,
    setMode: (mode) => {
      saveEditorMode(mode);
      set({ mode });
    },
    setInspectorTab: (inspectorTab) => set({ inspectorTab }),
    selectCue: (selectedCueId) => {
      const cue = firstScene(get().project).cues.find((item) => item.cue_id === selectedCueId);
      set({ selectedCueId, selectedEventId: cue?.events[0]?.event_id || null });
    },
    selectSlot: (selectedSlot) => set({ selectedSlot, inspectorTab: "character" }),
    selectEvent: (selectedEventId) => set({ selectedEventId }),
    updateProjectTitle: (title) => commit((project) => { project.title = title; }),
    updateDialogue: (patch) => commit((_project, cue) => {
      let dialogue = cue.events.find((event) => event.kind === "dialogue");
      if (!dialogue) {
        dialogue = { event_id: localId("event/dialogue"), kind: "dialogue", text: "" };
        cue.events.push(dialogue);
      }
      Object.assign(dialogue, patch);
    }),
    updateEnvironment: (patch) => commit((_project, cue) => {
      let background = cue.events.find((event) => event.kind === "background");
      if (!background) {
        background = { event_id: localId("event/background"), kind: "background" };
        cue.events.unshift(background);
      }
      Object.assign(background, patch);
    }),
    setSlotCharacter: (slot, characterId) => commit((_project, cue) => {
      cue.events = cue.events.filter((event) => !(
        (event.kind === "enter" || event.kind === "exit") && event.slot === slot
      ));
      cue.events.unshift(characterId
        ? { event_id: localId("event/enter"), kind: "enter", slot, character_id: characterId }
        : { event_id: localId("event/exit"), kind: "exit", slot });
    }),
    swapSlots: (source, target) => {
      if (source === target) return;
      const state = get();
      const scene = firstScene(state.project);
      const slots = stageAtCue(scene, state.selectedCueId);
      commit((_project, cue) => {
        cue.events = cue.events.filter((event) => !(
          (event.kind === "enter" || event.kind === "exit")
          && (event.slot === source || event.slot === target)
        ));
        const eventFor = (slot: number, characterId: string | null): CueEvent => characterId
          ? { event_id: localId("event/enter"), kind: "enter", slot, character_id: characterId }
          : { event_id: localId("event/exit"), kind: "exit", slot };
        cue.events.unshift(eventFor(target, slots[source - 1]), eventFor(source, slots[target - 1]));
      });
    },
    updateCharacterState: (slot, patch) => commit((_project, cue, scene) => {
      const characterId = stageAtCue(scene, cue.cue_id)[slot - 1];
      if (!characterId) return;
      let enter = cue.events.find((event) => event.kind === "enter" && event.slot === slot);
      if (!enter) {
        enter = { event_id: localId("event/enter"), kind: "enter", slot, character_id: characterId };
        cue.events.unshift(enter);
      }
      Object.assign(enter, patch);
    }),
    addQuickEffect: (kind) => {
      const state = get();
      const effectDefaults: Record<QuickEffectKind, Partial<CueEvent>> = {
        "halocue.ba:background-pan": { pan_x: 0.035, pan_y: 0 },
        "halocue.ba:screen-shake": { intensity: 0.35 },
        "halocue.ba:screen-text": { text: "屏幕文字" },
        "halocue.ba:hit-effect": { slot: state.selectedSlot, intensity: 0.5 },
      };
      const eventId = localId("event");
      commit((_project, cue) => {
        cue.events.push({ event_id: eventId, kind, ...effectDefaults[kind] });
      }, { selectedEventId: eventId });
    },
    addCue: (placement) => {
      const state = get();
      const cueId = localId("cue");
      commit((_project, cue, scene) => {
        const index = scene.cues.indexOf(cue) + (placement === "after" ? 1 : 0);
        scene.cues.splice(index, 0, {
          cue_id: cueId,
          title: "新演出",
          events: [{
            event_id: localId("event/dialogue"),
            kind: "dialogue",
            text: "",
            duration_ms: 1800,
          }],
        });
      }, { selectedCueId: cueId, selectedEventId: null });
    },
    duplicateCue: () => {
      const cueId = localId("cue");
      commit((_project, cue, scene) => {
        const duplicate = clone(cue);
        duplicate.cue_id = cueId;
        duplicate.title = `${cue.title || "演出"} 副本`;
        duplicate.events = duplicate.events.map((event) => ({ ...event, event_id: localId("event") }));
        scene.cues.splice(scene.cues.indexOf(cue) + 1, 0, duplicate);
      }, { selectedCueId: cueId, selectedEventId: null });
    },
    deleteCue: () => {
      const state = get();
      const scene = firstScene(state.project);
      if (scene.cues.length <= 1) return;
      const index = scene.cues.findIndex((cue) => cue.cue_id === state.selectedCueId);
      const next = scene.cues[Math.max(0, index - 1)];
      commit((_project, cue, draftScene) => {
        draftScene.cues.splice(draftScene.cues.indexOf(cue), 1);
      }, { selectedCueId: next.cue_id, selectedEventId: next.events[0]?.event_id || null });
    },
    moveCue: (sourceCueId, targetCueId) => commit((_project, _cue, scene) => {
      const source = scene.cues.findIndex((cue) => cue.cue_id === sourceCueId);
      const target = scene.cues.findIndex((cue) => cue.cue_id === targetCueId);
      if (source < 0 || target < 0 || source === target) return;
      const [item] = scene.cues.splice(source, 1);
      scene.cues.splice(target, 0, item);
    }),
    updateEvent: (eventId, patch) => commit((_project, cue) => {
      const event = cue.events.find((item) => item.event_id === eventId);
      if (event) Object.assign(event, patch);
    }),
    moveEvent: (eventId, direction) => commit((_project, cue) => {
      const index = cue.events.findIndex((event) => event.event_id === eventId);
      const target = index + direction;
      if (index < 0 || target < 0 || target >= cue.events.length) return;
      const [event] = cue.events.splice(index, 1);
      cue.events.splice(target, 0, event);
    }),
    undo: () => {
      const state = get();
      const previous = state.history.at(-1);
      if (!previous) return;
      repository.saveDraft(previous.project);
      set({
        ...previous,
        history: state.history.slice(0, -1),
        future: [{
          project: state.project,
          selectedCueId: state.selectedCueId,
          selectedEventId: state.selectedEventId,
        }, ...state.future.slice(0, 59)],
        dirty: true,
        revision: state.revision + 1,
      });
    },
    redo: () => {
      const state = get();
      const next = state.future[0];
      if (!next) return;
      repository.saveDraft(next.project);
      set({
        ...next,
        history: [...state.history, {
          project: state.project,
          selectedCueId: state.selectedCueId,
          selectedEventId: state.selectedEventId,
        }],
        future: state.future.slice(1),
        dirty: true,
        revision: state.revision + 1,
      });
    },
    replaceProject: (project) => {
      const normalized = repository.parseProject(project);
      const selection = initialSelection(normalized);
      repository.saveDraft(normalized);
      set({
        project: normalized,
        selectedCueId: selection.cueId,
        selectedEventId: selection.eventId,
        history: [],
        future: [],
        dirty: false,
        revision: get().revision + 1,
      });
    },
    markSaved: () => set({ dirty: false }),
    resetDemo: () => get().replaceProject(clone(demoProject)),
  };
  });
}

export const useProjectStore = createProjectStore();
