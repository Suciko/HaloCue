import { describe, expect, it } from "vitest";

import { demoProject } from "./demoProject";
import { buildPreviewIntent } from "./previewIntent";
import { evaluateScene } from "./sceneEvaluation";

describe("preview intent", () => {
  it("resolves simple Cue selection to the Cue completed state", () => {
    const cue = demoProject.chapters[0].scenes[0].cues[1];
    const evaluation = evaluateScene(demoProject, cue.cue_id);
    const intent = buildPreviewIntent(demoProject, evaluation, {
      cueId: cue.cue_id,
      kind: "cue",
    });
    const dialogue = evaluation.timeline.events.find(
      (event) => event.event_id === "event/dialogue/002",
    )!;

    expect(intent).toEqual({
      schema_version: "preview-intent/1.0",
      scene_id: "scene/conference-room",
      cue_id: cue.cue_id,
      selection_kind: "cue",
      selected_event_id: null,
      target: {
        event_id: dialogue.event_id,
        frame: dialogue.end_frame - 1,
        alignment: "end",
        resolution: "cue-terminal",
      },
    });
  });

  it("resolves a professional event selection to its exact start frame", () => {
    const cue = demoProject.chapters[0].scenes[0].cues[1];
    const evaluation = evaluateScene(demoProject, cue.cue_id);
    const intent = buildPreviewIntent(demoProject, evaluation, {
      cueId: cue.cue_id,
      kind: "event",
      eventId: "event/enter/koyuki",
    });
    const enter = evaluation.timeline.events.find(
      (event) => event.event_id === "event/enter/koyuki",
    )!;

    expect(intent.target).toEqual({
      event_id: enter.event_id,
      frame: enter.start_frame,
      alignment: "start",
      resolution: "selected-event",
    });
  });

  it("anchors an unrendered extension event to the preceding rendered state", () => {
    const cue = demoProject.chapters[0].scenes[0].cues[2];
    const evaluation = evaluateScene(demoProject, cue.cue_id);
    const intent = buildPreviewIntent(demoProject, evaluation, {
      cueId: cue.cue_id,
      kind: "event",
      eventId: "event/advanced/beat",
    });
    const dialogue = evaluation.timeline.events.find(
      (event) => event.event_id === "event/dialogue/003",
    )!;

    expect(intent.target).toEqual({
      event_id: dialogue.event_id,
      frame: dialogue.end_frame - 1,
      alignment: "end",
      resolution: "prior-renderable",
    });
    expect(intent.selected_event_id).toBe("event/advanced/beat");
  });

  it("uses an explicit scene-start fallback when an extension has no prior frame", () => {
    const project = structuredClone(demoProject);
    const cue = project.chapters[0].scenes[0].cues[0];
    cue.events.unshift({
      event_id: "event/advanced/opening",
      kind: "halocue.ba:camera-track",
    });
    const evaluation = evaluateScene(project, cue.cue_id);
    const intent = buildPreviewIntent(project, evaluation, {
      cueId: cue.cue_id,
      kind: "event",
      eventId: "event/advanced/opening",
    });

    expect(intent.target).toEqual({
      event_id: evaluation.timeline.events[0].event_id,
      frame: evaluation.timeline.events[0].start_frame,
      alignment: "start",
      resolution: "scene-start",
    });
  });

  it("rejects stale event selection instead of silently targeting another event", () => {
    const cue = demoProject.chapters[0].scenes[0].cues[1];
    const evaluation = evaluateScene(demoProject, cue.cue_id);

    expect(() => buildPreviewIntent(demoProject, evaluation, {
      cueId: cue.cue_id,
      kind: "event",
      eventId: "event/missing",
    })).toThrow(/不存在事件/);
  });

  it("resolves a professional playhead to its exact containing event frame", () => {
    const cue = demoProject.chapters[0].scenes[0].cues[1];
    const evaluation = evaluateScene(demoProject, cue.cue_id);
    const dialogue = evaluation.timeline.events.find(
      (event) => event.event_id === "event/dialogue/002",
    )!;
    const frame = dialogue.start_frame + 3;

    const intent = buildPreviewIntent(demoProject, evaluation, {
      cueId: cue.cue_id,
      kind: "playhead",
      frame,
    });

    expect(intent).toEqual({
      schema_version: "preview-intent/1.1",
      scene_id: "scene/conference-room",
      cue_id: cue.cue_id,
      selection_kind: "playhead",
      selected_event_id: null,
      target: {
        event_id: dialogue.event_id,
        frame,
        alignment: "exact",
        resolution: "explicit-frame",
      },
    });
  });
});
