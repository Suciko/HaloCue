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
      schema_version: "scene-performance/1.0",
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
    expect(plan.operations[0].amplitude_x_px).toBe(14);

    const source = descriptor();
    const timeline = buildRenderTimeline(source);
    expect(() => buildScenePerformance({ ...source, scene_id: "scene/other" }, timeline)).toThrow(/scene_id/);
  });
});
