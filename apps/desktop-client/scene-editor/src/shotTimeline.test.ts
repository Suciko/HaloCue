import { describe, expect, it } from "vitest";

import { demoProject } from "./demoProject";
import { evaluateScene } from "./sceneEvaluation";
import { buildShotTimeline } from "./shotTimeline";
import type { HaloCueProject } from "./types";

describe("shot timeline projection", () => {
  it("projects the selected Cue into stable semantic tracks", () => {
    const project = structuredClone(demoProject);
    const scene = project.chapters[0].scenes[0];
    const cue = scene.cues[0];
    cue.events.splice(3, 0, {
      event_id: "event/yuuka-nod",
      kind: "character-motion",
      character_id: "character/yuuka",
      slot: 1,
      motion_id: "motion/nod",
      duration_ms: 500,
      wait_for_completion: false,
    });
    const evaluation = evaluateScene(project, cue.cue_id, { sceneId: scene.scene_id });

    const projection = buildShotTimeline({
      sceneId: scene.scene_id,
      cue,
      timeline: evaluation.timeline,
    });

    expect(projection.schema_version).toBe("shot-timeline/1.0");
    expect(projection.trackIds).toEqual(["camera", "stage", "character", "dialogue", "effect"]);
    expect(projection.tracks.map((track) => track.label)).toEqual([
      "Camera",
      "Stage",
      "Character",
      "Dialogue / Overlay",
      "Effect / Timing",
    ]);
    const motion = projection.tracks.find((track) => track.id === "character")?.clips
      .find((clip) => clip.event_id === "event/yuuka-nod");
    const dialogue = projection.tracks.find((track) => track.id === "dialogue")?.clips
      .find((clip) => clip.event_id === "event/dialogue/001");
    expect(motion).toEqual(expect.objectContaining({
      event_id: "event/yuuka-nod",
      kind: "character-motion",
      wait_for_completion: false,
    }));
    expect(dialogue).toEqual(expect.objectContaining({
      event_id: "event/dialogue/001",
      kind: "dialogue",
    }));
    expect(motion?.start_frame).toBe(dialogue?.start_frame);
    expect(motion?.end_frame).toBeLessThan(dialogue?.end_frame ?? 0);
    expect(projection.total_frames).toBe(evaluation.timeline.total_frames);
  });

  it("surfaces cue events absent from the evaluated timeline without dropping the workspace", () => {
    const project = structuredClone(demoProject) as HaloCueProject;
    const scene = project.chapters[0].scenes[0];
    const cue = scene.cues[0];
    const evaluation = evaluateScene(project, cue.cue_id, { sceneId: scene.scene_id });
    cue.events.push({ event_id: "event/unmapped", kind: "dialogue", text: "未映射" });

    const projection = buildShotTimeline({
      sceneId: scene.scene_id,
      cue,
      timeline: evaluation.timeline,
    });

    expect(projection.unmappedEventIds).toEqual(["event/unmapped"]);
    expect(projection.tracks.flatMap((track) => track.clips)
      .some((clip) => clip.event_id === "event/unmapped")).toBe(false);
  });

  it("assigns overlapping clips on one semantic track to stable sub-lanes", () => {
    const project = structuredClone(demoProject);
    const scene = project.chapters[0].scenes[0];
    const cue = scene.cues[0];
    const dialogueIndex = cue.events.findIndex((event) => event.kind === "dialogue");
    cue.events.splice(dialogueIndex, 0, {
      event_id: "event/screen-text",
      kind: "halocue.ba:screen-text",
      text: "三天后",
      duration_ms: 1800,
      wait_for_completion: false,
    });
    const evaluation = evaluateScene(project, cue.cue_id, { sceneId: scene.scene_id });

    const projection = buildShotTimeline({
      sceneId: scene.scene_id,
      cue,
      timeline: evaluation.timeline,
    });
    const track = projection.tracks.find((item) => item.id === "dialogue")!;
    const screenText = track.clips.find((clip) => clip.event_id === "event/screen-text")!;
    const dialogue = track.clips.find((clip) => clip.kind === "dialogue")!;

    expect(screenText.start_frame).toBe(dialogue.start_frame);
    expect(track.lane_count).toBe(2);
    expect(screenText.lane_index).toBe(0);
    expect(dialogue.lane_index).toBe(1);
  });
});
