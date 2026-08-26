import { beforeEach, describe, expect, it } from "vitest";

import { demoProject } from "./demoProject";
import { buildRenderTimeline, dialogueDurationMs } from "./renderTimeline";
import { evaluateScene } from "./sceneEvaluation";
import { firstScene, useProjectStore } from "./projectStore";
import type { SceneDescriptor } from "./types";

describe("scene evaluation seam", () => {
  beforeEach(() => {
    localStorage.clear();
    useProjectStore.getState().replaceProject(structuredClone(demoProject));
  });

  it("binds the selected descriptor to a deterministic timeline", () => {
    const scene = firstScene(demoProject);
    const evaluation = evaluateScene(demoProject, scene.cues[1].cue_id);

    expect(evaluation.schema_version).toBe("scene-evaluation/1.0");
    expect(evaluation.scene_id).toBe(scene.scene_id);
    expect(evaluation.timeline.events.map((event) => event.event_id)).toEqual(
      evaluation.descriptor.events.map((event) => event.event_id),
    );
    expect(evaluation.timeline.events.at(-1)?.end_frame).toBe(evaluation.timeline.total_frames);
  });

  it("reports advanced events without dropping them from the project", () => {
    const scene = firstScene(demoProject);
    const evaluation = evaluateScene(demoProject, scene.cues[2].cue_id);

    expect(evaluation.diagnostics).toEqual([
      expect.objectContaining({
        code: "scene.advanced_event_omitted",
        severity: "warning",
      }),
    ]);
    expect(scene.cues[2].events.at(-1)?.kind).toBe("halocue.ba:reaction-beat");
  });

  it("matches the preview timeline duration policy", () => {
    const descriptor: SceneDescriptor = {
      schema_version: "scene-descriptor/1.0",
      scene_id: "scene/timeline",
      presentation: {},
      background: null,
      initial_background: null,
      actors: [],
      initial_actors: [],
      events: [{ event_id: "event/line", kind: "dialogue", text: "你好。" }],
    };
    const timeline = buildRenderTimeline(descriptor);

    expect(timeline.events[0].duration_ms).toBe(dialogueDurationMs("你好。"));
    expect(timeline.events[0].duration_frames).toBe(26);
  });
});
