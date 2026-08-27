(function (global) {
  "use strict";

  const PERFORMANCE_SCHEMA_VERSION = "scene-performance/1.0";
  const PERFORMANCE_SAMPLE_SCHEMA_VERSION = "scene-performance-sample/1.0";
  const DEFAULT_SHAKE_INTENSITY = 0.35;
  const SHAKE_FREQUENCY_HZ = 12;
  const SHAKE_MAX_X_PX = 14;
  const SHAKE_MAX_Y_PX = 8;
  const EXECUTION_MODES = new Set(["play", "sample", "skip", "reduced-motion"]);

  function clamp(value, minimum, maximum) {
    return Math.max(minimum, Math.min(maximum, value));
  }

  function quantize(value, digits) {
    const factor = 10 ** digits;
    return Math.round(value * factor) / factor;
  }

  function intensity(value) {
    const number = typeof value === "number" && Number.isFinite(value)
      ? value : DEFAULT_SHAKE_INTENSITY;
    return clamp(number, 0, 1);
  }

  function validateInputs(descriptor, timeline) {
    if (!descriptor || descriptor.schema_version !== "scene-descriptor/1.0") {
      throw new Error("unsupported scene descriptor schema");
    }
    if (!timeline || timeline.schema_version !== "render-timeline/1.0") {
      throw new Error("unsupported render timeline schema");
    }
    if (timeline.scene_id !== descriptor.scene_id) {
      throw new Error("scene performance timeline scene_id does not match the descriptor");
    }
    if (!Array.isArray(descriptor.events) || !Array.isArray(timeline.events)) {
      throw new Error("scene performance events must be arrays");
    }
    if (timeline.events.length !== descriptor.events.length) {
      throw new Error("scene performance timeline event count does not match the descriptor");
    }
    timeline.events.forEach((item, index) => {
      if (item.event_id !== descriptor.events[index]?.event_id) {
        throw new Error(`scene performance timeline event ${index} does not match the descriptor`);
      }
    });
  }

  function buildScenePerformance(descriptor, timeline) {
    validateInputs(descriptor, timeline);
    const operations = timeline.events
      .filter((item) => item.kind === "halocue.ba:screen-shake")
      .map((item) => {
        const resolvedIntensity = intensity(item.event?.intensity);
        return {
          operation_id: `${item.event_id}/operation/shake`,
          source_event_id: item.event_id,
          kind: "shake",
          target: { kind: "stage", target_id: "stage/global" },
          channel: "geometry.offset",
          value_space: "relative-to-baseline",
          start_frame: item.start_frame,
          end_frame: item.end_frame,
          amplitude_x_px: quantize(resolvedIntensity * SHAKE_MAX_X_PX, 3),
          amplitude_y_px: quantize(resolvedIntensity * SHAKE_MAX_Y_PX, 3),
          frequency_hz: SHAKE_FREQUENCY_HZ,
        };
      });
    return {
      schema_version: PERFORMANCE_SCHEMA_VERSION,
      frame_rate: timeline.frame_rate,
      scene_id: timeline.scene_id,
      total_frames: timeline.total_frames,
      operations,
      source_map: operations.map((operation) => ({
        source_event_id: operation.source_event_id,
        operation_ids: [operation.operation_id],
        primary_operation_id: operation.operation_id,
      })),
    };
  }

  function sampleScenePerformance(plan, frame, mode = "sample") {
    if (!plan || plan.schema_version !== PERFORMANCE_SCHEMA_VERSION) {
      throw new Error("unsupported scene performance schema");
    }
    if (!Number.isInteger(frame) || frame < 0 || frame >= plan.total_frames) {
      throw new RangeError(`performance frame must be between 0 and ${plan.total_frames - 1}`);
    }
    if (!EXECUTION_MODES.has(mode)) {
      throw new Error(`unsupported performance execution mode ${String(mode)}`);
    }
    const active = mode === "skip" || mode === "reduced-motion"
      ? [] : plan.operations.filter((operation) => (
        frame >= operation.start_frame && frame < operation.end_frame
      ));
    let offsetX = 0;
    let offsetY = 0;
    for (const operation of active) {
      const durationFrames = operation.end_frame - operation.start_frame;
      const localFrame = frame - operation.start_frame;
      const progress = durationFrames <= 1 ? 1 : localFrame / (durationFrames - 1);
      const envelope = 1 - progress;
      const seconds = localFrame / plan.frame_rate;
      const phase = Math.PI * 2 * operation.frequency_hz * seconds;
      offsetX += operation.amplitude_x_px * Math.sin(phase) * envelope;
      offsetY += operation.amplitude_y_px * Math.sin(phase * 1.7) * envelope;
    }
    return {
      schema_version: PERFORMANCE_SAMPLE_SCHEMA_VERSION,
      frame,
      mode,
      active_operation_ids: active.map((operation) => operation.operation_id),
      stage: {
        offset_x_px: quantize(offsetX, 6),
        offset_y_px: quantize(offsetY, 6),
      },
    };
  }

  global.HaloCueScenePerformanceRuntime = Object.freeze({
    PERFORMANCE_SCHEMA_VERSION,
    PERFORMANCE_SAMPLE_SCHEMA_VERSION,
    buildScenePerformance,
    sampleScenePerformance,
  });
}(window));
