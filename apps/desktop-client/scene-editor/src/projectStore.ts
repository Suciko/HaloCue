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
  EditorSelection,
  EditorTransactionResult,
  EditorMode,
  HaloCueProject,
  InspectorTab,
  QuickEffectKind,
  Scene,
} from "./types";
import { isDescriptorRenderable } from "./sceneEventRegistry";
import { createSceneEvent } from "./sceneEventFactory";
import { projectSceneAtCue, sceneById } from "./cueStateProjection";
import type { ProjectDiagnostic } from "./projectCodec";

const clone = <T,>(value: T): T => structuredClone(value);

function localId(prefix: string): string {
  return `${prefix}/${crypto.randomUUID()}`;
}

export { isProject } from "./projectRepository";

export { firstScene } from "./cueStateProjection";

export function stageAtCue(scene: Scene, cueId: string): Array<string | null> {
  return projectSceneAtCue(scene, cueId).afterCue.slots;
}

export function advancedEventCount(cue: Cue): number {
  return cue.events.filter((event) => !isDescriptorRenderable(event.kind)).length;
}

type HistoryEntry = { project: HaloCueProject } & EditorSelection;

type EditorState = {
  project: HaloCueProject;
  mode: EditorMode;
  inspectorTab: InspectorTab;
  selectedChapterId: string;
  selectedSceneId: string;
  selectedCueId: string;
  selectedSlot: number;
  selectedEventId: string | null;
  history: HistoryEntry[];
  future: HistoryEntry[];
  dirty: boolean;
  revision: number;
  projectDiagnostics: ProjectDiagnostic[];
  setMode: (mode: EditorMode) => void;
  setInspectorTab: (tab: InspectorTab) => void;
  selectChapter: (chapterId: string) => void;
  selectScene: (sceneId: string) => void;
  selectCue: (cueId: string) => void;
  selectSlot: (slot: number) => void;
  selectEvent: (eventId: string | null) => void;
  updateProjectTitle: (title: string) => EditorTransactionResult;
  updateDialogue: (patch: Partial<CueEvent>) => EditorTransactionResult;
  updateEnvironment: (patch: Partial<CueEvent>) => EditorTransactionResult;
  setSlotCharacter: (slot: number, characterId: string | null) => EditorTransactionResult;
  swapSlots: (source: number, target: number) => EditorTransactionResult;
  updateCharacterState: (slot: number, patch: Partial<CueEvent>) => EditorTransactionResult;
  addEvent: (kind: string) => EditorTransactionResult;
  addQuickEffect: (kind: QuickEffectKind) => EditorTransactionResult;
  addCue: (placement: "before" | "after") => EditorTransactionResult;
  duplicateCue: () => EditorTransactionResult;
  deleteCue: () => EditorTransactionResult;
  moveCue: (sourceCueId: string, targetCueId: string) => EditorTransactionResult;
  updateEvent: (eventId: string, patch: Partial<CueEvent>) => EditorTransactionResult;
  deleteEvent: (eventId: string) => EditorTransactionResult;
  moveEvent: (eventId: string, direction: -1 | 1) => EditorTransactionResult;
  undo: () => EditorTransactionResult;
  redo: () => EditorTransactionResult;
  replaceProject: (project: HaloCueProject) => EditorTransactionResult;
  markSaved: () => void;
  resetDemo: () => void;
};

function selectionForScene(
  project: HaloCueProject,
  sceneId: string,
): EditorSelection {
  for (const chapter of project.chapters) {
    const scene = chapter.scenes.find((item) => item.scene_id === sceneId);
    if (!scene) continue;
    const cue = scene.cues[0];
    if (!cue) throw new Error(`场景 ${scene.scene_id} 至少需要一个 Cue`);
    return {
      selectedChapterId: chapter.chapter_id,
      selectedSceneId: scene.scene_id,
      selectedCueId: cue.cue_id,
      selectedEventId: cue.events[0]?.event_id || null,
    };
  }
  throw new Error(`项目中不存在场景 ${sceneId}`);
}

function initialSelection(project: HaloCueProject): EditorSelection {
  for (const chapter of project.chapters) {
    const scene = chapter.scenes.find((item) => item.cues.length > 0);
    if (scene) return selectionForScene(project, scene.scene_id);
  }
  throw new Error("项目至少需要一个包含 Cue 的场景");
}

function selectionSnapshot(state: EditorState): EditorSelection {
  return {
    selectedChapterId: state.selectedChapterId,
    selectedSceneId: state.selectedSceneId,
    selectedCueId: state.selectedCueId,
    selectedEventId: state.selectedEventId,
  };
}

function noOp(state: Pick<EditorState, "revision">): EditorTransactionResult {
  return { status: "no-op", revision: state.revision };
}

function sameProject(left: HaloCueProject, right: HaloCueProject): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function repairTransactionSelection(
  project: HaloCueProject,
  selection: EditorSelection,
): EditorSelection {
  const chapter = project.chapters.find(
    (item) => item.chapter_id === selection.selectedChapterId,
  );
  const scene = chapter?.scenes.find(
    (item) => item.scene_id === selection.selectedSceneId,
  );
  const cue = scene?.cues.find((item) => item.cue_id === selection.selectedCueId);
  if (!chapter || !scene || !cue) {
    throw new Error("编辑事务生成了无效的 Chapter/Scene/Cue 选区");
  }
  if (
    selection.selectedEventId !== null
    && !cue.events.some((event) => event.event_id === selection.selectedEventId)
  ) {
    return {
      ...selection,
      selectedEventId: cue.events[0]?.event_id || null,
    };
  }
  return selection;
}

export function createProjectStore(repository: ProjectRepository = projectRepository) {
  const initialProject = repository.loadDraft();
  const initial = initialSelection(initialProject);

  return create<EditorState>((set, get) => {
  const commit = (
    mutator: (project: HaloCueProject, cue: Cue, scene: Scene) => void,
    selection?: Partial<EditorSelection>,
  ): EditorTransactionResult => {
    const state = get();
    const project = clone(state.project);
    const scene = sceneById(project, state.selectedSceneId);
    const cue = scene.cues.find((item) => item.cue_id === state.selectedCueId);
    if (!cue) return noOp(state);
    mutator(project, cue, scene);
    if (sameProject(project, state.project)) return noOp(state);
    const requestedSelection: EditorSelection = {
      selectedChapterId: selection?.selectedChapterId ?? state.selectedChapterId,
      selectedSceneId: selection?.selectedSceneId ?? state.selectedSceneId,
      selectedCueId: selection?.selectedCueId ?? state.selectedCueId,
      selectedEventId: selection?.selectedEventId === undefined
        ? state.selectedEventId : selection.selectedEventId,
    };
    const nextSelection = repairTransactionSelection(project, requestedSelection);
    repository.saveDraft(project);
    const revision = state.revision + 1;
    set({
      project,
      ...nextSelection,
      history: [...state.history.slice(-59), {
        project: state.project,
        ...selectionSnapshot(state),
      }],
      future: [],
      dirty: true,
      revision,
      projectDiagnostics: [...repository.getDiagnostics()],
    });
    return { status: "committed", revision };
  };

  return {
    project: initialProject,
    mode: loadEditorMode(),
    inspectorTab: "dialogue",
    selectedChapterId: initial.selectedChapterId,
    selectedSceneId: initial.selectedSceneId,
    selectedCueId: initial.selectedCueId,
    selectedSlot: 1,
    selectedEventId: initial.selectedEventId,
    history: [],
    future: [],
    dirty: false,
    revision: 0,
    projectDiagnostics: [...repository.getDiagnostics()],
    setMode: (mode) => {
      saveEditorMode(mode);
      set({ mode });
    },
    setInspectorTab: (inspectorTab) => set({ inspectorTab }),
    selectChapter: (chapterId) => {
      const state = get();
      if (chapterId === state.selectedChapterId) return;
      const chapter = state.project.chapters.find((item) => item.chapter_id === chapterId);
      const scene = chapter?.scenes.find((item) => item.cues.length > 0);
      if (!scene) return;
      set(selectionForScene(state.project, scene.scene_id));
    },
    selectScene: (sceneId) => {
      const state = get();
      if (sceneId === state.selectedSceneId) return;
      try {
        set(selectionForScene(state.project, sceneId));
      } catch (_error) {
        // A stale tree item must not corrupt the current canonical selection.
      }
    },
    selectCue: (selectedCueId) => {
      const state = get();
      if (selectedCueId === state.selectedCueId) return;
      const cue = sceneById(state.project, state.selectedSceneId)
        .cues.find((item) => item.cue_id === selectedCueId);
      if (!cue) return;
      set({ selectedCueId, selectedEventId: cue.events[0]?.event_id || null });
    },
    selectSlot: (selectedSlot) => set({ selectedSlot, inspectorTab: "character" }),
    selectEvent: (selectedEventId) => {
      if (selectedEventId === null) {
        set({ selectedEventId: null });
        return;
      }
      const state = get();
      const cue = sceneById(state.project, state.selectedSceneId)
        .cues.find((item) => item.cue_id === state.selectedCueId);
      if (cue?.events.some((event) => event.event_id === selectedEventId)) {
        set({ selectedEventId });
      }
    },
    updateProjectTitle: (title) => commit((project) => { project.title = title; }),
    updateDialogue: (patch) => commit((_project, cue) => {
      let dialogue = cue.events.find((event) => event.kind === "dialogue");
      if (!dialogue) {
        dialogue = { event_id: localId("event/dialogue"), kind: "dialogue", text: "" };
        cue.events.push(dialogue);
      }
      Object.assign(dialogue, patch);
    }),
    updateEnvironment: (patch) => commit((_project, cue, scene) => {
      let background = cue.events.find((event) => event.kind === "background");
      if (!background) {
        const inherited = projectSceneAtCue(scene, cue.cue_id).beforeCue.backgroundEvent;
        background = {
          ...(inherited || {}),
          event_id: localId("event/background"),
          kind: "background",
        };
        cue.events.unshift(background);
      }
      Object.assign(background, patch);
    }),
    setSlotCharacter: (slot, characterId) => {
      const state = get();
      const scene = sceneById(state.project, state.selectedSceneId);
      const currentCharacterId = projectSceneAtCue(scene, state.selectedCueId)
        .afterCue.slots[slot - 1];
      if (currentCharacterId === characterId) return noOp(state);
      return commit((_project, cue) => {
        cue.events = cue.events.filter((event) => !(
          (event.kind === "enter" || event.kind === "exit") && event.slot === slot
        ));
        cue.events.unshift(characterId
          ? { event_id: localId("event/enter"), kind: "enter", slot, character_id: characterId }
          : { event_id: localId("event/exit"), kind: "exit", slot });
      });
    },
    swapSlots: (source, target) => {
      const state = get();
      if (source === target) return noOp(state);
      const scene = sceneById(state.project, state.selectedSceneId);
      const slots = projectSceneAtCue(scene, state.selectedCueId).afterCue.slots;
      if (slots[source - 1] === slots[target - 1]) return noOp(state);
      return commit((_project, cue) => {
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
      const projection = projectSceneAtCue(scene, cue.cue_id);
      const characterId = projection.afterCue.slots[slot - 1];
      if (!characterId) return;
      let enter = [...cue.events].reverse().find((event) => event.kind === "enter" && event.slot === slot);
      if (!enter) {
        enter = { event_id: localId("event/enter"), kind: "enter", slot, character_id: characterId };
        cue.events.unshift(enter);
      }
      Object.assign(enter, patch);
    }),
    addEvent: (kind) => {
      const state = get();
      const eventId = localId("event");
      return commit((project, cue) => {
        cue.events.push(createSceneEvent(kind, {
          eventId,
          selectedSlot: state.selectedSlot,
          project,
        }));
      }, { selectedEventId: eventId });
    },
    addQuickEffect: (kind) => {
      const state = get();
      const eventId = localId("event");
      return commit((project, cue) => {
        cue.events.push(createSceneEvent(kind, {
          eventId,
          selectedSlot: state.selectedSlot,
          project,
        }));
      }, { selectedEventId: eventId });
    },
    addCue: (placement) => {
      const state = get();
      const cueId = localId("cue");
      return commit((_project, cue, scene) => {
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
      return commit((_project, cue, scene) => {
        const duplicate = clone(cue);
        duplicate.cue_id = cueId;
        duplicate.title = `${cue.title || "演出"} 副本`;
        duplicate.events = duplicate.events.map((event) => ({ ...event, event_id: localId("event") }));
        scene.cues.splice(scene.cues.indexOf(cue) + 1, 0, duplicate);
      }, { selectedCueId: cueId, selectedEventId: null });
    },
    deleteCue: () => {
      const state = get();
      const scene = sceneById(state.project, state.selectedSceneId);
      if (scene.cues.length <= 1) return noOp(state);
      const index = scene.cues.findIndex((cue) => cue.cue_id === state.selectedCueId);
      const next = scene.cues[Math.max(0, index - 1)];
      return commit((_project, cue, draftScene) => {
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
    deleteEvent: (eventId) => {
      const state = get();
      const cue = sceneById(state.project, state.selectedSceneId)
        .cues.find((item) => item.cue_id === state.selectedCueId);
      if (!cue || !cue.events.some((event) => event.event_id === eventId)) return noOp(state);
      const index = cue.events.findIndex((event) => event.event_id === eventId);
      const nextEvent = cue.events[index + 1] || cue.events[index - 1] || null;
      return commit((_project, draftCue) => {
        draftCue.events = draftCue.events.filter((event) => event.event_id !== eventId);
      }, { selectedEventId: nextEvent?.event_id || null });
    },
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
      if (!previous) return noOp(state);
      repository.saveDraft(previous.project);
      const revision = state.revision + 1;
      set({
        ...previous,
        history: state.history.slice(0, -1),
        future: [{
          project: state.project,
          ...selectionSnapshot(state),
        }, ...state.future.slice(0, 59)],
        dirty: true,
        revision,
        projectDiagnostics: [...repository.getDiagnostics()],
      });
      return { status: "committed", revision };
    },
    redo: () => {
      const state = get();
      const next = state.future[0];
      if (!next) return noOp(state);
      repository.saveDraft(next.project);
      const revision = state.revision + 1;
      set({
        ...next,
        history: [...state.history, {
          project: state.project,
          ...selectionSnapshot(state),
        }],
        future: state.future.slice(1),
        dirty: true,
        revision,
        projectDiagnostics: [...repository.getDiagnostics()],
      });
      return { status: "committed", revision };
    },
    replaceProject: (project) => {
      const normalized = repository.parseProject(project);
      const selection = initialSelection(normalized);
      repository.saveDraft(normalized);
      const revision = get().revision + 1;
      set({
        project: normalized,
        ...selection,
        history: [],
        future: [],
        dirty: false,
        revision,
        projectDiagnostics: [...repository.getDiagnostics()],
      });
      return { status: "committed", revision };
    },
    markSaved: () => set({ dirty: false }),
    resetDemo: () => get().replaceProject(clone(demoProject)),
  };
  });
}

export const useProjectStore = createProjectStore();
