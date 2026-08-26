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
});
