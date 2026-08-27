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
  EditorAutosaveState,
  EditorSelection,
  EditorTransactionResult,
  EditorMode,
  HaloCueProject,
  InspectorTab,
  QuickEffectKind,
  Scene,
} from "./types";
import { AutosaveCoordinator } from "./autosave";
import { isDescriptorRenderable } from "./sceneEventRegistry";
import { createSceneEvent } from "./sceneEventFactory";
import { reorderEventBlock, type EventMove } from "./eventReorder";
import { eventInsertionIndex, type EventInsertion } from "./eventInsertion";
import {
  repairEventSelection,
  selectEventIds,
  selectionAfterEventDeletion,
  type EventSelectionMode,
} from "./eventSelection";
import { duplicateEventBlock } from "./eventDuplication";
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
export type EditorTransactionInterruption = "commit" | "cancel";
type ActiveEditorTransaction = {
  key: string;
  interruption: EditorTransactionInterruption;
  base: HistoryEntry;
  dirty: boolean;
  projectDiagnostics: ProjectDiagnostic[];
};

type EditorState = {
  project: HaloCueProject;
  mode: EditorMode;
  inspectorTab: InspectorTab;
  selectedChapterId: string;
  selectedSceneId: string;
  selectedCueId: string;
  selectedSlot: number;
  selectedEventId: string | null;
  selectedEventIds: string[];
  eventSelectionAnchorId: string | null;
  previewPlayheadFrame: number | null;
  history: HistoryEntry[];
  future: HistoryEntry[];
  dirty: boolean;
  revision: number;
  previewRevision: number;
  activeTransaction: ActiveEditorTransaction | null;
  autosave: EditorAutosaveState;
  projectDiagnostics: ProjectDiagnostic[];
  setMode: (mode: EditorMode) => void;
  setInspectorTab: (tab: InspectorTab) => void;
  selectChapter: (chapterId: string) => void;
  selectScene: (sceneId: string) => void;
  selectCue: (cueId: string) => void;
  selectSlot: (slot: number) => void;
  selectEvent: (eventId: string | null, mode?: EventSelectionMode) => void;
  setPreviewPlayheadFrame: (frame: number | null) => void;
  beginTransaction: (key: string, options?: { interruption?: EditorTransactionInterruption }) => void;
  previewDialogue: (key: string, patch: Partial<CueEvent>) => void;
  previewEnvironment: (key: string, patch: Partial<CueEvent>) => void;
  previewEvent: (key: string, eventId: string, patch: Partial<CueEvent>) => void;
  previewCharacterState: (key: string, slot: number, patch: Partial<CueEvent>) => void;
  commitTransaction: (key: string) => EditorTransactionResult;
  cancelTransaction: (key: string) => void;
  flushAutosave: () => void;
  retryAutosave: () => void;
  updateProjectTitle: (title: string) => EditorTransactionResult;
  updateDialogue: (patch: Partial<CueEvent>) => EditorTransactionResult;
  updateEnvironment: (patch: Partial<CueEvent>) => EditorTransactionResult;
  setSlotCharacter: (slot: number, characterId: string | null) => EditorTransactionResult;
  swapSlots: (source: number, target: number) => EditorTransactionResult;
  updateCharacterState: (slot: number, patch: Partial<CueEvent>) => EditorTransactionResult;
  addEvent: (kind: string, insertion?: EventInsertion) => EditorTransactionResult;
  addQuickEffect: (kind: QuickEffectKind) => EditorTransactionResult;
  addCue: (placement: "before" | "after") => EditorTransactionResult;
  duplicateCue: () => EditorTransactionResult;
  deleteCue: () => EditorTransactionResult;
  moveCue: (sourceCueId: string, targetCueId: string) => EditorTransactionResult;
  updateEvent: (eventId: string, patch: Partial<CueEvent>) => EditorTransactionResult;
  deleteEvent: (eventId: string) => EditorTransactionResult;
  deleteSelectedEvents: () => EditorTransactionResult;
  duplicateSelectedEvents: () => EditorTransactionResult;
  moveEvent: (eventId: string, move: EventMove) => EditorTransactionResult;
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
      selectedEventIds: cue.events[0] ? [cue.events[0].event_id] : [],
      eventSelectionAnchorId: cue.events[0]?.event_id || null,
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
    selectedEventIds: [...state.selectedEventIds],
    eventSelectionAnchorId: state.eventSelectionAnchorId,
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
  return { ...selection, ...repairEventSelection(cue.events, selection) };
}

function applyEnvironmentPatch(
  cue: Cue,
  scene: Scene,
  patch: Partial<CueEvent>,
): void {
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
}

function applyDialoguePatch(cue: Cue, patch: Partial<CueEvent>): void {
  let dialogue = cue.events.find((event) => event.kind === "dialogue");
  if (!dialogue) {
    dialogue = { event_id: localId("event/dialogue"), kind: "dialogue", text: "" };
    cue.events.push(dialogue);
  }
  Object.assign(dialogue, patch);
}

function applyEventPatch(cue: Cue, eventId: string, patch: Partial<CueEvent>): boolean {
  const event = cue.events.find((item) => item.event_id === eventId);
  if (!event) return false;
  Object.assign(event, patch);
  return true;
}

function applyCharacterMotionPatch(
  cue: Cue,
  scene: Scene,
  slot: number,
  motionId: unknown,
): void {
  const projection = projectSceneAtCue(scene, cue.cue_id);
  const characterId = projection.afterCue.slots[slot - 1];
  if (!characterId) return;
  const normalizedMotionId = typeof motionId === "string" && motionId
    ? motionId
    : "motion/idle";
  const isLegacyMotionCarrier = (event: CueEvent) => (
    (event.kind === "enter" && event.slot === slot)
    || (event.kind === "dialogue" && event.character_id === characterId)
  );
  cue.events.forEach((event) => {
    if (isLegacyMotionCarrier(event)) delete event.motion_id;
  });
  const existingIndex = cue.events.findIndex((event) => (
    event.kind === "character-motion" && event.slot === slot
  ));
  if (normalizedMotionId === "motion/idle") {
    cue.events = cue.events.filter((event) => !(
      event.kind === "character-motion" && event.slot === slot
    ));
    return;
  }
  if (existingIndex >= 0) {
    Object.assign(cue.events[existingIndex], {
      character_id: characterId,
      motion_id: normalizedMotionId,
    });
    return;
  }
  const motionEvent: CueEvent = {
    event_id: localId("event/character-motion"),
    kind: "character-motion",
    slot,
    character_id: characterId,
    motion_id: normalizedMotionId,
  };
  const lastPlacementIndex = cue.events.reduce((found, event, index) => (
    event.kind === "enter" && event.slot === slot ? index : found
  ), -1);
  const dialogueIndex = cue.events.findIndex((event) => event.kind === "dialogue");
  const insertionIndex = lastPlacementIndex >= 0
    ? lastPlacementIndex + 1
    : dialogueIndex >= 0 ? dialogueIndex : cue.events.length;
  cue.events.splice(insertionIndex, 0, motionEvent);
}

function characterMotionInsertionIndex(
  cue: Cue,
  beforeSlots: Array<string | null>,
  event: CueEvent,
  requestedIndex: number,
): number {
  const slot = Number(event.slot);
  const characterId = event.character_id;
  if (!Number.isInteger(slot) || slot < 1 || slot > 5 || !characterId) return requestedIndex;
  let occupant = beforeSlots[slot - 1];
  const validPositions: number[] = [];
  for (let position = 0; position <= cue.events.length; position += 1) {
    if (occupant === characterId) validPositions.push(position);
    const current = cue.events[position];
    if (current?.kind === "enter" && current.slot === slot) {
      occupant = current.character_id || null;
    } else if (current?.kind === "exit" && current.slot === slot) {
      occupant = null;
    }
  }
  return validPositions.find((position) => position >= requestedIndex)
    ?? validPositions.at(-1)
    ?? requestedIndex;
}

function applyCharacterStatePatch(
  cue: Cue,
  scene: Scene,
  slot: number,
  patch: Partial<CueEvent>,
): void {
  const statePatch = { ...patch };
  if (Object.prototype.hasOwnProperty.call(statePatch, "motion_id")) {
    applyCharacterMotionPatch(cue, scene, slot, statePatch.motion_id);
    delete statePatch.motion_id;
  }
  if (Object.keys(statePatch).length === 0) return;
  const projection = projectSceneAtCue(scene, cue.cue_id);
  const characterId = projection.afterCue.slots[slot - 1];
  if (!characterId) return;
  const currentState = projection.afterCue.actorStateEvents[slot - 1];
  if (Object.entries(statePatch).every(([key, value]) => currentState?.[key] === value)) return;
  let enter = [...cue.events].reverse()
    .find((event) => event.kind === "enter" && event.slot === slot);
  if (!enter) {
    enter = { event_id: localId("event/enter"), kind: "enter", slot, character_id: characterId };
    cue.events.unshift(enter);
  }
  Object.assign(enter, statePatch);
}

export function createProjectStore(repository: ProjectRepository = projectRepository) {
  const initialProject = repository.loadDraft();
  const initial = initialSelection(initialProject);

  return create<EditorState>((set, get) => {
  const autosaveCoordinator = new AutosaveCoordinator<HaloCueProject>(
    (project) => repository.saveDraft(project),
    (autosave) => set({ autosave }),
  );

  const commitActiveTransaction = (key?: string): EditorTransactionResult => {
    const state = get();
    const active = state.activeTransaction;
    if (!active || (key !== undefined && active.key !== key)) return noOp(state);
    if (sameProject(state.project, active.base.project)) {
      set({
        ...active.base,
        activeTransaction: null,
        previewRevision: state.previewRevision + 1,
      });
      return noOp(state);
    }
    try {
      repository.serializeProject(state.project);
    } catch (error) {
      set({
        ...active.base,
        dirty: active.dirty,
        projectDiagnostics: active.projectDiagnostics,
        activeTransaction: null,
        previewRevision: state.previewRevision + 1,
      });
      throw error;
    }
    const revision = state.revision + 1;
    const autosave = autosaveCoordinator.request(state.project, revision);
    set({
      history: [...state.history.slice(-59), active.base],
      future: [],
      dirty: true,
      revision,
      activeTransaction: null,
      autosave,
      projectDiagnostics: [...repository.getDiagnostics()],
    });
    return { status: "committed", revision };
  };

  const cancelActiveTransaction = (key?: string): void => {
    const state = get();
    const active = state.activeTransaction;
    if (!active || (key !== undefined && active.key !== key)) return;
    set({
      ...active.base,
      dirty: active.dirty,
      projectDiagnostics: active.projectDiagnostics,
      activeTransaction: null,
      previewRevision: state.previewRevision + 1,
    });
  };

  const finishActiveTransaction = (): EditorTransactionResult => {
    const state = get();
    const active = state.activeTransaction;
    if (!active) return noOp(state);
    if (active.interruption === "cancel") {
      cancelActiveTransaction(active.key);
      return noOp(get());
    }
    return commitActiveTransaction(active.key);
  };

  const previewActiveTransaction = (
    key: string,
    mutator: (project: HaloCueProject, cue: Cue, scene: Scene) => void,
  ): void => {
    const state = get();
    const active = state.activeTransaction;
    if (!active || active.key !== key) {
      throw new Error(`编辑事务 ${key} 尚未开始`);
    }
    if (
      state.selectedSceneId !== active.base.selectedSceneId
      || state.selectedCueId !== active.base.selectedCueId
    ) {
      throw new Error(`编辑事务 ${key} 的目标选区已改变`);
    }
    const project = clone(state.project);
    const scene = sceneById(project, state.selectedSceneId);
    const cue = scene.cues.find((item) => item.cue_id === state.selectedCueId);
    if (!cue) throw new Error(`编辑事务 ${key} 的 Cue 已不存在`);
    mutator(project, cue, scene);
    if (sameProject(project, state.project)) return;
    set({ project, previewRevision: state.previewRevision + 1 });
  };

  const commit = (
    mutator: (project: HaloCueProject, cue: Cue, scene: Scene) => void,
    selection?: Partial<EditorSelection>,
  ): EditorTransactionResult => {
    finishActiveTransaction();
    const state = get();
    const project = clone(state.project);
    const scene = sceneById(project, state.selectedSceneId);
    const cue = scene.cues.find((item) => item.cue_id === state.selectedCueId);
    if (!cue) return noOp(state);
    mutator(project, cue, scene);
    if (sameProject(project, state.project)) return noOp(state);
    const selectedEventId = selection?.selectedEventId === undefined
      ? state.selectedEventId : selection.selectedEventId;
    const eventSelectionWasExplicit = selection?.selectedEventId !== undefined;
    const requestedSelection: EditorSelection = {
      selectedChapterId: selection?.selectedChapterId ?? state.selectedChapterId,
      selectedSceneId: selection?.selectedSceneId ?? state.selectedSceneId,
      selectedCueId: selection?.selectedCueId ?? state.selectedCueId,
      selectedEventId,
      selectedEventIds: selection?.selectedEventIds
        ?? (eventSelectionWasExplicit ? selectedEventId ? [selectedEventId] : [] : state.selectedEventIds),
      eventSelectionAnchorId: selection?.eventSelectionAnchorId === undefined
        ? eventSelectionWasExplicit ? selectedEventId : state.eventSelectionAnchorId
        : selection.eventSelectionAnchorId,
    };
    const nextSelection = repairTransactionSelection(project, requestedSelection);
    repository.serializeProject(project);
    const revision = state.revision + 1;
    const autosave = autosaveCoordinator.request(project, revision);
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
      previewPlayheadFrame: selection ? null : state.previewPlayheadFrame,
      autosave,
      projectDiagnostics: [...repository.getDiagnostics()],
    });
    return { status: "committed", revision };
  };

  const deleteEvents = (eventIds: Iterable<string>): EditorTransactionResult => {
    finishActiveTransaction();
    const state = get();
    const cue = sceneById(state.project, state.selectedSceneId)
      .cues.find((item) => item.cue_id === state.selectedCueId);
    if (!cue) return noOp(state);
    const requested = new Set(eventIds);
    const deletedIds = cue.events
      .filter((event) => requested.has(event.event_id))
      .map((event) => event.event_id);
    if (deletedIds.length === 0) return noOp(state);
    const nextSelection = selectionAfterEventDeletion(cue.events, deletedIds);
    return commit((_project, draftCue) => {
      const deleted = new Set(deletedIds);
      draftCue.events = draftCue.events.filter((event) => !deleted.has(event.event_id));
    }, nextSelection);
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
    selectedEventIds: initial.selectedEventIds,
    eventSelectionAnchorId: initial.eventSelectionAnchorId,
    previewPlayheadFrame: null,
    history: [],
    future: [],
    dirty: false,
    revision: 0,
    previewRevision: 0,
    activeTransaction: null,
    autosave: autosaveCoordinator.currentState(),
    projectDiagnostics: [...repository.getDiagnostics()],
    setMode: (mode) => {
      finishActiveTransaction();
      saveEditorMode(mode);
      set({
        mode,
        previewPlayheadFrame: mode === "simple" ? null : get().previewPlayheadFrame,
      });
    },
    setInspectorTab: (inspectorTab) => {
      finishActiveTransaction();
      set({ inspectorTab });
    },
    selectChapter: (chapterId) => {
      finishActiveTransaction();
      const state = get();
      if (chapterId === state.selectedChapterId) return;
      const chapter = state.project.chapters.find((item) => item.chapter_id === chapterId);
      const scene = chapter?.scenes.find((item) => item.cues.length > 0);
      if (!scene) return;
      set({ ...selectionForScene(state.project, scene.scene_id), previewPlayheadFrame: null });
    },
    selectScene: (sceneId) => {
      finishActiveTransaction();
      const state = get();
      if (sceneId === state.selectedSceneId) return;
      try {
        set({ ...selectionForScene(state.project, sceneId), previewPlayheadFrame: null });
      } catch (_error) {
        // A stale tree item must not corrupt the current canonical selection.
      }
    },
    selectCue: (selectedCueId) => {
      finishActiveTransaction();
      const state = get();
      if (selectedCueId === state.selectedCueId) {
        if (state.previewPlayheadFrame !== null) set({ previewPlayheadFrame: null });
        return;
      }
      const cue = sceneById(state.project, state.selectedSceneId)
        .cues.find((item) => item.cue_id === selectedCueId);
      if (!cue) return;
      set({
        selectedCueId,
        selectedEventId: cue.events[0]?.event_id || null,
        selectedEventIds: cue.events[0] ? [cue.events[0].event_id] : [],
        eventSelectionAnchorId: cue.events[0]?.event_id || null,
        previewPlayheadFrame: null,
      });
    },
    selectSlot: (selectedSlot) => {
      finishActiveTransaction();
      set({ selectedSlot, inspectorTab: "character" });
    },
    selectEvent: (selectedEventId, mode = "replace") => {
      finishActiveTransaction();
      if (selectedEventId === null) {
        set({
          selectedEventId: null,
          selectedEventIds: [],
          eventSelectionAnchorId: null,
          previewPlayheadFrame: null,
        });
        return;
      }
      const state = get();
      const cue = sceneById(state.project, state.selectedSceneId)
        .cues.find((item) => item.cue_id === state.selectedCueId);
      if (!cue) return;
      const selection = selectEventIds(cue.events, state, selectedEventId, mode);
      if (selection === state) return;
      set({ ...selection, previewPlayheadFrame: null });
    },
    setPreviewPlayheadFrame: (frame) => {
      if (frame === null) {
        set({ previewPlayheadFrame: null });
        return;
      }
      if (!Number.isInteger(frame) || frame < 0) {
        throw new Error("预览播放头必须是非负整数帧");
      }
      set({ previewPlayheadFrame: frame });
    },
    beginTransaction: (key, options) => {
      if (!key) throw new Error("编辑事务需要稳定的 key");
      const current = get().activeTransaction;
      if (current?.key === key) return;
      if (current) finishActiveTransaction();
      const state = get();
      set({
        activeTransaction: {
          key,
          interruption: options?.interruption ?? "commit",
          base: {
            project: state.project,
            ...selectionSnapshot(state),
          },
          dirty: state.dirty,
          projectDiagnostics: state.projectDiagnostics,
        },
      });
    },
    previewDialogue: (key, patch) => previewActiveTransaction(key, (_project, cue) => {
      applyDialoguePatch(cue, patch);
    }),
    previewEnvironment: (key, patch) => previewActiveTransaction(key, (_project, cue, scene) => {
      applyEnvironmentPatch(cue, scene, patch);
    }),
    previewEvent: (key, eventId, patch) => previewActiveTransaction(key, (_project, cue) => {
      if (!applyEventPatch(cue, eventId, patch)) {
        throw new Error(`编辑事务 ${key} 的事件 ${eventId} 已不存在`);
      }
    }),
    previewCharacterState: (key, slot, patch) => previewActiveTransaction(
      key,
      (_project, cue, scene) => applyCharacterStatePatch(cue, scene, slot, patch),
    ),
    commitTransaction: (key) => commitActiveTransaction(key),
    cancelTransaction: (key) => cancelActiveTransaction(key),
    flushAutosave: () => autosaveCoordinator.flush(),
    retryAutosave: () => autosaveCoordinator.retry(),
    updateProjectTitle: (title) => commit((project) => { project.title = title; }),
    updateDialogue: (patch) => commit((_project, cue) => {
      applyDialoguePatch(cue, patch);
    }),
    updateEnvironment: (patch) => commit((_project, cue, scene) => {
      applyEnvironmentPatch(cue, scene, patch);
    }),
    setSlotCharacter: (slot, characterId) => {
      finishActiveTransaction();
      const state = get();
      const scene = sceneById(state.project, state.selectedSceneId);
      const currentCharacterId = projectSceneAtCue(scene, state.selectedCueId)
        .afterCue.slots[slot - 1];
      if (currentCharacterId === characterId) return noOp(state);
      return commit((_project, cue) => {
        cue.events = cue.events.filter((event) => !(
          (event.kind === "enter" || event.kind === "exit" || event.kind === "character-motion")
          && event.slot === slot
        ));
        cue.events.unshift(characterId
          ? { event_id: localId("event/enter"), kind: "enter", slot, character_id: characterId }
          : { event_id: localId("event/exit"), kind: "exit", slot });
      });
    },
    swapSlots: (source, target) => {
      finishActiveTransaction();
      const state = get();
      if (source === target) return noOp(state);
      const scene = sceneById(state.project, state.selectedSceneId);
      const slots = projectSceneAtCue(scene, state.selectedCueId).afterCue.slots;
      if (slots[source - 1] === slots[target - 1]) return noOp(state);
      return commit((_project, cue) => {
        cue.events = cue.events.filter((event) => !(
          (event.kind === "enter" || event.kind === "exit" || event.kind === "character-motion")
          && (event.slot === source || event.slot === target)
        ));
        const eventFor = (slot: number, characterId: string | null): CueEvent => characterId
          ? { event_id: localId("event/enter"), kind: "enter", slot, character_id: characterId }
          : { event_id: localId("event/exit"), kind: "exit", slot };
        cue.events.unshift(eventFor(target, slots[source - 1]), eventFor(source, slots[target - 1]));
      });
    },
    updateCharacterState: (slot, patch) => commit(
      (_project, cue, scene) => applyCharacterStatePatch(cue, scene, slot, patch),
    ),
    addEvent: (kind, insertion) => {
      const state = get();
      const eventId = localId("event");
      const selectedCharacterId = projectSceneAtCue(
        sceneById(state.project, state.selectedSceneId),
        state.selectedCueId,
      ).afterCue.slots[state.selectedSlot - 1];
      return commit((project, cue) => {
        const event = createSceneEvent(kind, {
          eventId,
          selectedSlot: state.selectedSlot,
          selectedCharacterId,
          project,
        });
        const requestedIndex = eventInsertionIndex(cue.events, insertion);
        const insertionIndex = kind === "character-motion"
          ? characterMotionInsertionIndex(
            cue,
            projectSceneAtCue(
              sceneById(project, state.selectedSceneId),
              state.selectedCueId,
            ).beforeCue.slots,
            event,
            requestedIndex,
          )
          : requestedIndex;
        cue.events.splice(insertionIndex, 0, event);
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
      finishActiveTransaction();
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
      applyEventPatch(cue, eventId, patch);
    }),
    deleteEvent: (eventId) => deleteEvents([eventId]),
    deleteSelectedEvents: () => deleteEvents(get().selectedEventIds),
    duplicateSelectedEvents: () => {
      finishActiveTransaction();
      const state = get();
      const cue = sceneById(state.project, state.selectedSceneId)
        .cues.find((item) => item.cue_id === state.selectedCueId);
      if (!cue) return noOp(state);
      const selectedSources = cue.events.filter((event) => state.selectedEventIds.includes(event.event_id));
      if (selectedSources.length === 0) return noOp(state);
      const duplicateEventIds = selectedSources.map(() => localId("event"));
      const duplicateIdFor = new Map(selectedSources.map((event, index) => (
        [event.event_id, duplicateEventIds[index]]
      )));
      const selectedEventId = state.selectedEventId
        ? duplicateIdFor.get(state.selectedEventId) ?? duplicateEventIds[0]
        : duplicateEventIds[0];
      const eventSelectionAnchorId = state.eventSelectionAnchorId
        ? duplicateIdFor.get(state.eventSelectionAnchorId) ?? selectedEventId
        : selectedEventId;
      return commit((_project, draftCue) => {
        draftCue.events = duplicateEventBlock(
          draftCue.events,
          state.selectedEventIds,
          (_source, index) => duplicateEventIds[index],
        ).events;
      }, {
        selectedEventId,
        selectedEventIds: duplicateEventIds,
        eventSelectionAnchorId,
      });
    },
    moveEvent: (eventId, move) => {
      const state = get();
      const sourceEventIds = state.selectedEventIds.includes(eventId)
        ? state.selectedEventIds
        : [eventId];
      return commit((_project, cue) => {
        cue.events = reorderEventBlock(cue.events, sourceEventIds, move).slice();
      });
    },
    undo: () => {
      finishActiveTransaction();
      const state = get();
      const previous = state.history.at(-1);
      if (!previous) return noOp(state);
      repository.serializeProject(previous.project);
      const revision = state.revision + 1;
      const autosave = autosaveCoordinator.request(previous.project, revision);
      set({
        ...previous,
        history: state.history.slice(0, -1),
        future: [{
          project: state.project,
          ...selectionSnapshot(state),
        }, ...state.future.slice(0, 59)],
        dirty: true,
        revision,
        previewPlayheadFrame: null,
        autosave,
        projectDiagnostics: [...repository.getDiagnostics()],
      });
      return { status: "committed", revision };
    },
    redo: () => {
      finishActiveTransaction();
      const state = get();
      const next = state.future[0];
      if (!next) return noOp(state);
      repository.serializeProject(next.project);
      const revision = state.revision + 1;
      const autosave = autosaveCoordinator.request(next.project, revision);
      set({
        ...next,
        history: [...state.history, {
          project: state.project,
          ...selectionSnapshot(state),
        }],
        future: state.future.slice(1),
        dirty: true,
        revision,
        previewPlayheadFrame: null,
        autosave,
        projectDiagnostics: [...repository.getDiagnostics()],
      });
      return { status: "committed", revision };
    },
    replaceProject: (project) => {
      const normalized = repository.parseProject(project);
      const selection = initialSelection(normalized);
      const revision = get().revision + 1;
      repository.serializeProject(normalized);
      const autosave = autosaveCoordinator.request(normalized, revision);
      set({
        project: normalized,
        ...selection,
        history: [],
        future: [],
        dirty: false,
        revision,
        previewRevision: get().previewRevision + 1,
        activeTransaction: null,
        previewPlayheadFrame: null,
        autosave,
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
