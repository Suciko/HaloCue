import { beforeEach, describe, expect, it } from "vitest";

import { buildDescriptor } from "./descriptor";
import { demoProject } from "./demoProject";
import { advancedEventCount, firstScene, stageAtCue, useProjectStore } from "./projectStore";


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
});
