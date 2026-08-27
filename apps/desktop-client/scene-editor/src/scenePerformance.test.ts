import { describe, expect, it } from "vitest";

import { buildScenePerformance, sampleScenePerformance } from "./scenePerformance";
import { buildRenderTimeline } from "./renderTimeline";
import type { SceneDescriptor } from "./types";

const descriptor = (intensity: unknown = 0.35): SceneDescriptor => ({
  schema_version: "scene-descriptor/1.0",
  scene_id: "scene/performance",
  presentation: { frame_rate: 30 },
  background: null,
  initial_background: null,
  actors: [],
  initial_actors: [],
  events: [
    { event_id: "event/wait", kind: "wait", duration_ms: 100 },
    { event_id: "event/shake", kind: "halocue.ba:screen-shake", duration_ms: 360, intensity },
    { event_id: "event/after", kind: "wait", duration_ms: 100 },
  ],
});

describe("scene performance compiler", () => {
  it("normalizes a screen-shake event into one stable operation and source map", () => {
    const source = descriptor();
    const timeline = buildRenderTimeline(source);
    const plan = buildScenePerformance(source, timeline);
    const shakeRange = timeline.events[1];

    expect(plan).toEqual({
      schema_version: "scene-performance/1.1",
      frame_rate: 30,
      scene_id: "scene/performance",
      total_frames: timeline.total_frames,
      operations: [{
        operation_id: "event/shake/operation/shake",
        source_event_id: "event/shake",
        kind: "shake",
        target: { kind: "stage", target_id: "stage/global" },
        channel: "geometry.offset",
        value_space: "relative-to-baseline",
        start_frame: shakeRange.start_frame,
        end_frame: shakeRange.end_frame,
        amplitude_x_px: 4.9,
        amplitude_y_px: 2.8,
        frequency_hz: 12,
      }],
      source_map: [{
        source_event_id: "event/shake",
        operation_ids: ["event/shake/operation/shake"],
        primary_operation_id: "event/shake/operation/shake",
      }],
    });
  });

  it("compiles enter and exit into shared character contribution channels", () => {
    const source = descriptor();
    source.initial_actors = [
      { slot: 1, character_id: null, state: "hidden" },
      { slot: 2, character_id: null, state: "hidden" },
      { slot: 3, character_id: null, state: "hidden" },
      { slot: 4, character_id: null, state: "hidden" },
      { slot: 5, character_id: null, state: "hidden" },
    ];
    source.events = [
      { event_id: "event/enter", kind: "enter", slot: 2, character_id: "character/alice" },
      { event_id: "event/wait", kind: "wait", duration_ms: 100 },
      { event_id: "event/exit", kind: "exit", slot: 2 },
    ];
    const timeline = buildRenderTimeline(source);
    const plan = buildScenePerformance(source, timeline);
    const enter = timeline.events[0];
    const exit = timeline.events[2];
    const enterIds = plan.source_map[0].operation_ids;
    const exitIds = plan.source_map[1].operation_ids;

    expect(enterIds).toHaveLength(3);
    expect(exitIds).toHaveLength(3);
    expect(plan.operations.filter((operation) => operation.source_event_id === "event/enter")
      .map((operation) => operation.channel))
      .toEqual(["presentation.opacity", "layout.offset-y", "presentation.scale"]);

    expect(sampleScenePerformance(plan, enter.start_frame, "sample").characters).toEqual([{
      character_id: "character/alice",
      slot: 2,
      opacity: 0,
      offset_y_px: 24,
      scale: 0.97,
    }]);
    expect(sampleScenePerformance(plan, enter.end_frame - 1, "sample").characters).toEqual([{
      character_id: "character/alice",
      slot: 2,
      opacity: 1,
      offset_y_px: 0,
      scale: 1,
    }]);
    expect(sampleScenePerformance(plan, enter.start_frame, "skip").characters[0]).toMatchObject({
      opacity: 1,
      offset_y_px: 0,
      scale: 1,
    });
    expect(sampleScenePerformance(plan, enter.start_frame, "reduced-motion").characters[0]).toMatchObject({
      opacity: 0,
      offset_y_px: 0,
      scale: 1,
    });
    expect(sampleScenePerformance(plan, exit.start_frame, "sample").characters[0]).toMatchObject({
      opacity: 1,
      offset_y_px: 0,
      scale: 1,
    });
    expect(sampleScenePerformance(plan, exit.end_frame - 1, "sample").characters[0]).toMatchObject({
      opacity: 0,
      offset_y_px: 12,
      scale: 0.985,
    });
  });

  it("samples deterministic motion while skip and reduced motion keep the clean baseline", () => {
    const source = descriptor();
    const timeline = buildRenderTimeline(source);
    const plan = buildScenePerformance(source, timeline);
    const frame = timeline.events[1].start_frame + 2;
    const first = sampleScenePerformance(plan, frame, "sample");
    const repeated = sampleScenePerformance(plan, frame, "play");

    expect(first.active_operation_ids).toEqual(["event/shake/operation/shake"]);
    expect(first.stage.offset_x_px).not.toBe(0);
    expect(first.stage.offset_y_px).not.toBe(0);
    expect(repeated.stage).toEqual(first.stage);
    expect(sampleScenePerformance(plan, frame, "skip").stage).toEqual({ offset_x_px: 0, offset_y_px: 0 });
    expect(sampleScenePerformance(plan, frame, "reduced-motion").stage).toEqual({ offset_x_px: 0, offset_y_px: 0 });
    expect(sampleScenePerformance(plan, timeline.events[2].start_frame, "sample").stage)
      .toEqual({ offset_x_px: 0, offset_y_px: 0 });
  });

  it("clamps author intensity and rejects a mismatched timeline", () => {
    const strong = descriptor(8);
    const plan = buildScenePerformance(strong, buildRenderTimeline(strong));
    const shake = plan.operations.find((operation) => operation.kind === "shake");
    expect(shake?.amplitude_x_px).toBe(14);

    const source = descriptor();
    const timeline = buildRenderTimeline(source);
    expect(() => buildScenePerformance({ ...source, scene_id: "scene/other" }, timeline)).toThrow(/scene_id/);
  });
});
