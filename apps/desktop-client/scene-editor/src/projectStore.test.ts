import { beforeEach, describe, expect, it } from "vitest";

import { buildDescriptor } from "./descriptor";
import { demoProject } from "./demoProject";
import { advancedEventCount, firstScene, stageAtCue, useProjectStore } from "./projectStore";
import { evaluateScene } from "./sceneEvaluation";

function multiSceneProject() {
  const project = structuredClone(demoProject);
  project.chapters.push({
    chapter_id: "chapter/branch",
    title: "支线",
    scenes: [{
      scene_id: "scene/branch-room",
      title: "支线教室",
      cues: [
        {
          cue_id: "cue/branch/001",
          title: "支线开场",
          events: [{
            event_id: "event/branch/dialogue/001",
            kind: "dialogue",
            text: "支线原文",
            duration_ms: 1800,
          }],
        },
        {
          cue_id: "cue/branch/002",
          title: "支线收束",
          events: [{
            event_id: "event/branch/dialogue/002",
            kind: "dialogue",
            text: "支线第二拍",
            duration_ms: 1800,
          }],
        },
      ],
    }],
  });
  return project;
}


describe("shared dual-mode project store", () => {
  beforeEach(() => {
    localStorage.clear();
    useProjectStore.getState().replaceProject(structuredClone(demoProject));
  });

  it("switches editor modes without changing canonical project data", () => {
    const before = structuredClone(useProjectStore.getState().project);

    useProjectStore.getState().setMode("professional");
    useProjectStore.getState().setMode("simple");

    expect(useProjectStore.getState().project).toEqual(before);
  });

  it("keeps namespaced events while the preview projects renderable events", () => {
    const scene = firstScene(useProjectStore.getState().project);
    const cue = scene.cues[2];
    expect(advancedEventCount(cue)).toBe(1);

    const descriptor = buildDescriptor(useProjectStore.getState().project, cue.cue_id);

    expect(descriptor.events.some((event) => event.kind === "halocue.ba:reaction-beat")).toBe(false);
    expect(firstScene(useProjectStore.getState().project).cues[2].events.at(-1)?.kind)
      .toBe("halocue.ba:reaction-beat");
  });

  it("resolves the five visible stage slots at each Cue", () => {
    const scene = firstScene(useProjectStore.getState().project);

    expect(stageAtCue(scene, scene.cues[0].cue_id)).toEqual([
      "character/yuuka", null, "character/noa", null, null,
    ]);
    expect(stageAtCue(scene, scene.cues[1].cue_id)).toEqual([
      "character/yuuka", null, "character/noa", null, "character/koyuki",
    ]);
  });

  it("treats equivalent slot commands as no-op transactions", () => {
    const before = useProjectStore.getState();

    const sameCharacter = before.setSlotCharacter(1, "character/yuuka");
    const sameEmptyOccupant = useProjectStore.getState().swapSlots(2, 4);
    const current = useProjectStore.getState();

    expect(sameCharacter).toEqual({ status: "no-op", revision: before.revision });
    expect(sameEmptyOccupant).toEqual({ status: "no-op", revision: before.revision });
    expect(current.project).toEqual(before.project);
    expect(current.history).toEqual(before.history);
    expect(current.future).toEqual(before.future);
    expect(current.dirty).toBe(before.dirty);
    expect(current.revision).toBe(before.revision);
  });

  it("moves the preview playhead without creating project history", () => {
    const before = useProjectStore.getState();

    before.setPreviewPlayheadFrame(17);
    let current = useProjectStore.getState();
    expect(current.previewPlayheadFrame).toBe(17);
    expect(current.project).toBe(before.project);
    expect(current.history).toEqual(before.history);
    expect(current.revision).toBe(before.revision);
    expect(current.autosave).toEqual(before.autosave);

    current.selectEvent("event/dialogue/001");
    current = useProjectStore.getState();
    expect(current.previewPlayheadFrame).toBeNull();
  });

  it("stores a stable expression state while the adapter resolves a Spine animation", () => {
    const state = useProjectStore.getState();
    state.updateCharacterState(1, { expression_id: "expression/smile" });

    const current = useProjectStore.getState();
    const cue = firstScene(current.project).cues[0];
    const enter = cue.events.find((event) => event.kind === "enter" && event.slot === 1);
    const descriptor = buildDescriptor(current.project, cue.cue_id);
    const actor = descriptor.actors[0];

    expect(enter?.expression_id).toBe("expression/smile");
    expect((actor.stage_media as { animation: string }).animation).toBe("03");
  });

  it("projects motion and emoticon state without replacing stable IDs", () => {
    const state = useProjectStore.getState();
    state.selectCue("cue/conference/002");

    const current = useProjectStore.getState();
    const descriptor = buildDescriptor(current.project, current.selectedCueId);
    const actor = descriptor.actors.find((item) => item.character_id === "character/koyuki");
    const dialogue = descriptor.events.find((event) => event.event_id === "event/dialogue/002");

    expect(actor?.motion_id).toBe("motion/appear");
    expect(dialogue?.emoticon_id).toBe("emoticon/bulb");
    expect(current.project.chapters[0].scenes[0].cues[1].events[0].event_id)
      .toBe("event/enter/koyuki");
  });

  it("authors inherited environment changes as a local Cue override", () => {
    const state = useProjectStore.getState();
    state.selectCue("cue/conference/002");
    state.updateEnvironment({ zoom: 1.12 });

    const current = useProjectStore.getState();
    const cue = firstScene(current.project).cues[1];
    const background = cue.events.find((event) => event.kind === "background");

    expect(background).toEqual(expect.objectContaining({
      resource_id: "aa/background/bg_conference_room",
      zoom: 1.12,
    }));
    expect(background?.event_id).not.toBe("event/background/001");
    expect(buildDescriptor(current.project, current.selectedCueId).background?.resource_id)
      .toBe("aa/background/bg_conference_room");
  });

  it("updates the latest local actor state after a character carries into a later Cue", () => {
    const state = useProjectStore.getState();
    state.selectCue("cue/conference/002");
    state.updateCharacterState(1, { expression_id: "expression/smile" });
    state.updateCharacterState(1, { motion_id: "motion/nod" });

    const cue = firstScene(useProjectStore.getState().project).cues[1];
    const localStateEvents = cue.events.filter((event) => event.kind === "enter" && event.slot === 1);
    expect(localStateEvents).toHaveLength(1);
    expect(localStateEvents[0]).toEqual(expect.objectContaining({
      character_id: "character/yuuka",
      expression_id: "expression/smile",
      motion_id: "motion/nod",
    }));
  });

  it("inserts quick effects as typed events with stable IDs", () => {
    const state = useProjectStore.getState();
    state.addQuickEffect("halocue.ba:screen-shake");

    const current = useProjectStore.getState();
    const cue = firstScene(current.project).cues[0];
    const effect = cue.events.at(-1);
    const descriptor = buildDescriptor(current.project, cue.cue_id);

    expect(effect?.kind).toBe("halocue.ba:screen-shake");
    expect(effect?.event_id).toMatch(/^event\//);
    expect(advancedEventCount(cue)).toBe(0);
    expect(descriptor.events.at(-1)?.kind).toBe("halocue.ba:screen-shake");
  });

  it("adds a professional event through the same canonical command path", () => {
    const state = useProjectStore.getState();
    state.setMode("professional");
    state.addEvent("enter");

    const current = useProjectStore.getState();
    const cue = firstScene(current.project).cues[0];
    const event = cue.events.at(-1);

    expect(event).toEqual(expect.objectContaining({
      kind: "enter",
      slot: 1,
      character_id: "character/yuuka",
    }));
    expect(current.selectedEventId).toBe(event?.event_id);
  });

  it("inserts a professional event relative to the selected stable event", () => {
    const state = useProjectStore.getState();
    const cue = firstScene(state.project).cues[0];
    const originalOrder = cue.events.map((event) => event.event_id);
    const anchorId = originalOrder[1];
    const revisionBefore = state.revision;
    const historyBefore = state.history.length;
    state.selectEvent(anchorId);

    expect(state.addEvent("wait", {
      anchorEventId: anchorId,
      placement: "before",
    })).toEqual({ status: "committed", revision: revisionBefore + 1 });

    let current = useProjectStore.getState();
    const insertedId = current.selectedEventId;
    const events = firstScene(current.project).cues[0].events;
    expect(insertedId).toMatch(/^event\//);
    expect(events.map((event) => event.event_id))
      .toEqual([originalOrder[0], insertedId, ...originalOrder.slice(1)]);
    expect(events[1]).toEqual(expect.objectContaining({ event_id: insertedId, kind: "wait" }));
    expect(current.history).toHaveLength(historyBefore + 1);

    current.undo();
    current = useProjectStore.getState();
    expect(firstScene(current.project).cues[0].events.map((event) => event.event_id))
      .toEqual(originalOrder);
    expect(current.selectedEventId).toBe(anchorId);
  });

  it("deletes a selected professional event and selects its nearest neighbor", () => {
    const state = useProjectStore.getState();
    const cue = firstScene(state.project).cues[0];
    const deletedId = cue.events[1].event_id;
    const neighborId = cue.events[2].event_id;
    state.selectEvent(deletedId);
    state.deleteEvent(deletedId);

    const current = useProjectStore.getState();
    expect(firstScene(current.project).cues[0].events.some((event) => event.event_id === deletedId)).toBe(false);
    expect(current.selectedEventId).toBe(neighborId);
  });

  it("reorders professional events by stable target ID and undoes in one step", () => {
    const state = useProjectStore.getState();
    const cue = firstScene(state.project).cues[0];
    const originalOrder = cue.events.map((event) => event.event_id);
    const sourceId = originalOrder[0];
    const targetId = originalOrder[2];
    const revisionBefore = state.revision;
    const historyBefore = state.history.length;
    state.selectEvent(sourceId);

    expect(state.moveEvent(sourceId, { targetEventId: targetId, placement: "after" }))
      .toEqual({ status: "committed", revision: revisionBefore + 1 });

    let current = useProjectStore.getState();
    expect(firstScene(current.project).cues[0].events.map((event) => event.event_id))
      .toEqual([originalOrder[1], originalOrder[2], sourceId, originalOrder[3]]);
    expect(current.selectedEventId).toBe(sourceId);
    expect(current.history).toHaveLength(historyBefore + 1);

    current.undo();
    current = useProjectStore.getState();
    expect(firstScene(current.project).cues[0].events.map((event) => event.event_id))
      .toEqual(originalOrder);
    expect(current.selectedEventId).toBe(sourceId);
  });

  it("treats equivalent event placements as no-op transactions", () => {
    const state = useProjectStore.getState();
    const cue = firstScene(state.project).cues[0];
    const originalOrder = cue.events.map((event) => event.event_id);
    const revisionBefore = state.revision;
    const historyBefore = state.history;

    expect(state.moveEvent(originalOrder[0], {
      targetEventId: originalOrder[1],
      placement: "before",
    })).toEqual({ status: "no-op", revision: revisionBefore });

    const current = useProjectStore.getState();
    expect(firstScene(current.project).cues[0].events.map((event) => event.event_id))
      .toEqual(originalOrder);
    expect(current.history).toEqual(historyBefore);
  });

  it("deletes a stable multi-selection as one revision and restores it on undo", () => {
    const state = useProjectStore.getState();
    const cue = firstScene(state.project).cues[0];
    const originalOrder = cue.events.map((event) => event.event_id);
    const revisionBefore = state.revision;
    const historyBefore = state.history.length;

    state.selectEvent(originalOrder[1]);
    useProjectStore.getState().selectEvent(originalOrder[2], "toggle");
    let current = useProjectStore.getState();
    expect(current.selectedEventId).toBe(originalOrder[2]);
    expect(current.selectedEventIds).toEqual(originalOrder.slice(1, 3));
    expect(current.eventSelectionAnchorId).toBe(originalOrder[2]);
    expect(current.revision).toBe(revisionBefore);
    expect(current.history).toHaveLength(historyBefore);

    expect(current.deleteSelectedEvents())
      .toEqual({ status: "committed", revision: revisionBefore + 1 });
    current = useProjectStore.getState();
    expect(firstScene(current.project).cues[0].events.map((event) => event.event_id))
      .toEqual([originalOrder[0], originalOrder[3]]);
    expect(current.selectedEventId).toBe(originalOrder[3]);
    expect(current.selectedEventIds).toEqual([originalOrder[3]]);
    expect(current.history).toHaveLength(historyBefore + 1);

    current.undo();
    current = useProjectStore.getState();
    expect(firstScene(current.project).cues[0].events.map((event) => event.event_id))
      .toEqual(originalOrder);
    expect(current.selectedEventId).toBe(originalOrder[2]);
    expect(current.selectedEventIds).toEqual(originalOrder.slice(1, 3));
    expect(current.eventSelectionAnchorId).toBe(originalOrder[2]);
  });

  it("duplicates a stable multi-selection as one newly selected block", () => {
    const state = useProjectStore.getState();
    const cue = firstScene(state.project).cues[0];
    const originalOrder = cue.events.map((event) => event.event_id);
    const revisionBefore = state.revision;
    const historyBefore = state.history.length;
    state.selectEvent(originalOrder[1]);
    useProjectStore.getState().selectEvent(originalOrder[3], "toggle");

    expect(useProjectStore.getState().duplicateSelectedEvents())
      .toEqual({ status: "committed", revision: revisionBefore + 1 });

    let current = useProjectStore.getState();
    const events = firstScene(current.project).cues[0].events;
    const duplicateIds = events.slice(4).map((event) => event.event_id);
    expect(events.map((event) => event.event_id))
      .toEqual([...originalOrder, ...duplicateIds]);
    expect(duplicateIds).toHaveLength(2);
    expect(new Set([...originalOrder, ...duplicateIds]).size).toBe(6);
    expect(events[4]).toEqual({ ...cue.events[1], event_id: duplicateIds[0] });
    expect(events[5]).toEqual({ ...cue.events[3], event_id: duplicateIds[1] });
    expect(current.selectedEventIds).toEqual(duplicateIds);
    expect(current.selectedEventId).toBe(duplicateIds[1]);
    expect(current.eventSelectionAnchorId).toBe(duplicateIds[1]);
    expect(current.history).toHaveLength(historyBefore + 1);

    current.undo();
    current = useProjectStore.getState();
    expect(firstScene(current.project).cues[0].events.map((event) => event.event_id))
      .toEqual(originalOrder);
    expect(current.selectedEventIds).toEqual([originalOrder[1], originalOrder[3]]);
    expect(current.selectedEventId).toBe(originalOrder[3]);
  });

  it("reorders a stable multi-selection as one block and restores it on undo", () => {
    const state = useProjectStore.getState();
    const cue = firstScene(state.project).cues[0];
    const originalOrder = cue.events.map((event) => event.event_id);
    const revisionBefore = state.revision;
    const historyBefore = state.history.length;
    state.selectEvent(originalOrder[1]);
    useProjectStore.getState().selectEvent(originalOrder[3], "toggle");

    expect(useProjectStore.getState().moveEvent(originalOrder[1], {
      targetEventId: originalOrder[0],
      placement: "before",
    })).toEqual({ status: "committed", revision: revisionBefore + 1 });

    let current = useProjectStore.getState();
    expect(firstScene(current.project).cues[0].events.map((event) => event.event_id))
      .toEqual([originalOrder[1], originalOrder[3], originalOrder[0], originalOrder[2]]);
    expect(current.selectedEventIds).toEqual([originalOrder[1], originalOrder[3]]);
    expect(current.selectedEventId).toBe(originalOrder[3]);
    expect(current.eventSelectionAnchorId).toBe(originalOrder[3]);
    expect(current.history).toHaveLength(historyBefore + 1);

    expect(current.moveEvent(originalOrder[1], {
      targetEventId: originalOrder[3],
      placement: "after",
    })).toEqual({ status: "no-op", revision: revisionBefore + 1 });
    expect(useProjectStore.getState().history).toHaveLength(historyBefore + 1);

    current.undo();
    current = useProjectStore.getState();
    expect(firstScene(current.project).cues[0].events.map((event) => event.event_id))
      .toEqual(originalOrder);
    expect(current.selectedEventIds).toEqual([originalOrder[1], originalOrder[3]]);
    expect(current.selectedEventId).toBe(originalOrder[3]);
    expect(current.eventSelectionAnchorId).toBe(originalOrder[3]);
  });

  it("targets edits, evaluation, undo, and redo at the selected Scene", () => {
    const store = useProjectStore.getState();
    store.replaceProject(multiSceneProject());
    store.selectChapter("chapter/branch");
    expect(useProjectStore.getState().selectedSceneId).toBe("scene/branch-room");
    store.selectScene("scene/missing");
    expect(useProjectStore.getState().selectedSceneId).toBe("scene/branch-room");

    let current = useProjectStore.getState();
    expect(current.selectedChapterId).toBe("chapter/branch");
    expect(current.selectedSceneId).toBe("scene/branch-room");
    expect(current.selectedCueId).toBe("cue/branch/001");
    current.updateDialogue({ text: "只修改支线" });

    current = useProjectStore.getState();
    expect(current.project.chapters[0].scenes[0].cues[0].events.at(-1)?.text)
      .toBe("老师，校庆预算的最终确认就拜托您了。");
    expect(current.project.chapters[1].scenes[0].cues[0].events[0].text)
      .toBe("只修改支线");
    expect(buildDescriptor(current.project, current.selectedCueId, {
      sceneId: current.selectedSceneId,
    }).scene_id).toBe("scene/branch-room");
    const branchEvaluation = evaluateScene(current.project, current.selectedCueId, {
      sceneId: current.selectedSceneId,
    });
    expect(branchEvaluation.scene_id).toBe("scene/branch-room");
    expect(branchEvaluation.diagnostics).toEqual([]);

    current.undo();
    current = useProjectStore.getState();
    expect(current.selectedSceneId).toBe("scene/branch-room");
    expect(current.project.chapters[1].scenes[0].cues[0].events[0].text)
      .toBe("支线原文");

    current.redo();
    current = useProjectStore.getState();
    expect(current.selectedSceneId).toBe("scene/branch-room");
    expect(current.project.chapters[1].scenes[0].cues[0].events[0].text)
      .toBe("只修改支线");
  });

  it("repairs Cue selection inside the selected Scene and rejects cross-scene IDs", () => {
    const store = useProjectStore.getState();
    store.replaceProject(multiSceneProject());
    store.selectScene("scene/branch-room");
    store.selectEvent("event/branch/dialogue/001");
    store.selectScene("scene/branch-room");
    expect(useProjectStore.getState().selectedEventId)
      .toBe("event/branch/dialogue/001");
    store.selectCue("cue/conference/001");
    expect(useProjectStore.getState().selectedCueId).toBe("cue/branch/001");

    store.selectCue("cue/branch/002");
    store.deleteCue();
    const current = useProjectStore.getState();
    expect(current.selectedSceneId).toBe("scene/branch-room");
    expect(current.selectedCueId).toBe("cue/branch/001");
    expect(current.project.chapters[1].scenes[0].cues).toHaveLength(1);
    expect(current.project.chapters[0].scenes[0].cues).toHaveLength(3);
  });
});
