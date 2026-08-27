(function (global) {
  "use strict";

  const PERFORMANCE_SCHEMA_VERSION = "scene-performance/1.3";
  const PERFORMANCE_SAMPLE_SCHEMA_VERSION = "scene-performance-sample/1.0";
  const DEFAULT_SHAKE_INTENSITY = 0.35;
  const SHAKE_FREQUENCY_HZ = 12;
  const SHAKE_MAX_X_PX = 14;
  const SHAKE_MAX_Y_PX = 8;
  const CHARACTER_ENTER_OFFSET_Y_PX = 24;
  const CHARACTER_EXIT_OFFSET_Y_PX = 12;
  const CHARACTER_ENTER_SCALE = 0.97;
  const CHARACTER_EXIT_SCALE = 0.985;
  const NOD_OFFSET_Y_KEYFRAMES = Object.freeze([
    { offset: 0, value: 0 },
    { offset: 0.32, value: 4 },
    { offset: 0.68, value: -2 },
    { offset: 1, value: 0 },
  ]);
  const NOD_ROTATION_KEYFRAMES = Object.freeze([
    { offset: 0, value: 0 },
    { offset: 0.32, value: 1.5 },
    { offset: 0.68, value: -1 },
    { offset: 1, value: 0 },
  ]);
  const APPEAR_OPACITY_KEYFRAMES = Object.freeze([
    { offset: 0, value: 0.55 },
    { offset: 0.55, value: 1 },
    { offset: 1, value: 1 },
  ]);
  const APPEAR_OFFSET_Y_KEYFRAMES = Object.freeze([
    { offset: 0, value: 10 },
    { offset: 0.55, value: -3 },
    { offset: 1, value: 0 },
  ]);
  const APPEAR_SCALE_KEYFRAMES = Object.freeze([
    { offset: 0, value: 0.985 },
    { offset: 0.55, value: 1.01 },
    { offset: 1, value: 1 },
  ]);
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
    if (!timeline || timeline.schema_version !== "render-timeline/1.1") {
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
    const operations = [];
    const slotCharacters = new Map();
    for (const actor of descriptor.initial_actors || []) {
      const slot = Number(actor?.slot);
      const characterId = typeof actor?.character_id === "string" ? actor.character_id : "";
      if (Number.isInteger(slot) && slot >= 1 && slot <= 5 && characterId && actor.state === "visible") {
        slotCharacters.set(slot, characterId);
      }
    }
    const addCharacterTween = (
      item, characterId, slot, suffix, channel, valueSpace, from, to,
    ) => operations.push({
      operation_id: `${item.event_id}/operation/${suffix}`,
      source_event_id: item.event_id,
      kind: "numeric-tween",
      target: { kind: "character", character_id: characterId, slot },
      channel,
      value_space: valueSpace,
      start_frame: item.start_frame,
      end_frame: item.end_frame,
      from,
      to,
      easing: "ease-out-cubic",
    });
    const addCharacterKeyframes = (
      item, characterId, slot, suffix, channel, valueSpace, keyframes, easing,
    ) => operations.push({
      operation_id: `${item.event_id}/operation/${suffix}`,
      source_event_id: item.event_id,
      kind: "numeric-keyframes",
      target: { kind: "character", character_id: characterId, slot },
      channel,
      value_space: valueSpace,
      start_frame: item.start_frame,
      end_frame: item.end_frame,
      keyframes: keyframes.map((keyframe) => ({ ...keyframe })),
      easing,
    });
    const addNod = (item, characterId, slot) => {
      addCharacterKeyframes(
        item, characterId, slot, "motion-nod-offset-y", "layout.offset-y",
        "relative-to-baseline", NOD_OFFSET_Y_KEYFRAMES, "ease-in-out-strong",
      );
      addCharacterKeyframes(
        item, characterId, slot, "motion-nod-rotation", "presentation.rotation",
        "relative-to-baseline", NOD_ROTATION_KEYFRAMES, "ease-in-out-strong",
      );
    };
    const addAppear = (item, characterId, slot) => {
      addCharacterKeyframes(
        item, characterId, slot, "motion-appear-opacity", "presentation.opacity",
        "factor-from-baseline", APPEAR_OPACITY_KEYFRAMES, "ease-out-emphasized",
      );
      addCharacterKeyframes(
        item, characterId, slot, "motion-appear-offset-y", "layout.offset-y",
        "relative-to-baseline", APPEAR_OFFSET_Y_KEYFRAMES, "ease-out-emphasized",
      );
      addCharacterKeyframes(
        item, characterId, slot, "motion-appear-scale", "presentation.scale",
        "factor-from-baseline", APPEAR_SCALE_KEYFRAMES, "ease-out-emphasized",
      );
    };
    const addCapabilityMotion = (item, characterId, slot) => {
      if (item.event?.motion_id === "motion/nod") addNod(item, characterId, slot);
      if (item.event?.motion_id === "motion/appear") addAppear(item, characterId, slot);
    };
    for (const item of timeline.events) {
      if (item.kind === "halocue.ba:screen-shake") {
        const resolvedIntensity = intensity(item.event?.intensity);
        operations.push({
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
        });
      }
      if (item.kind === "enter") {
        const slot = Number(item.event?.slot);
        const characterId = typeof item.event?.character_id === "string"
          ? item.event.character_id : "";
        if (!Number.isInteger(slot) || slot < 1 || slot > 5 || !characterId) continue;
        const isStateUpdate = slotCharacters.get(slot) === characterId;
        if (!isStateUpdate) {
          addCharacterTween(item, characterId, slot, "opacity", "presentation.opacity", "absolute", 0, 1);
          addCharacterTween(item, characterId, slot, "offset-y", "layout.offset-y", "relative-to-baseline", CHARACTER_ENTER_OFFSET_Y_PX, 0);
          addCharacterTween(item, characterId, slot, "scale", "presentation.scale", "factor-from-baseline", CHARACTER_ENTER_SCALE, 1);
        }
        addCapabilityMotion(item, characterId, slot);
        slotCharacters.set(slot, characterId);
      }
      if (item.kind === "dialogue" && ["motion/nod", "motion/appear"].includes(String(item.event?.motion_id))) {
        const characterId = typeof item.event?.character_id === "string" ? item.event.character_id : "";
        const slot = [...slotCharacters.entries()]
          .find(([, currentCharacterId]) => currentCharacterId === characterId)?.[0];
        if (slot) addCapabilityMotion(item, characterId, slot);
      }
      if (item.kind === "character-motion") {
        const slot = Number(item.event?.slot);
        if (!Number.isInteger(slot) || slot < 1 || slot > 5) continue;
        const occupiedCharacterId = slotCharacters.get(slot) || "";
        const characterId = typeof item.event?.character_id === "string"
          ? item.event.character_id
          : occupiedCharacterId;
        if (!occupiedCharacterId || characterId !== occupiedCharacterId) {
          continue;
        }
        addCapabilityMotion(item, characterId, slot);
      }
      if (item.kind === "exit") {
        const slot = Number(item.event?.slot);
        const characterId = typeof item.event?.character_id === "string"
          ? item.event.character_id : slotCharacters.get(slot) || "";
        if (!Number.isInteger(slot) || slot < 1 || slot > 5 || !characterId) continue;
        addCharacterTween(item, characterId, slot, "opacity", "presentation.opacity", "absolute", 1, 0);
        addCharacterTween(item, characterId, slot, "offset-y", "layout.offset-y", "relative-to-baseline", 0, CHARACTER_EXIT_OFFSET_Y_PX);
        addCharacterTween(item, characterId, slot, "scale", "presentation.scale", "factor-from-baseline", 1, CHARACTER_EXIT_SCALE);
        slotCharacters.delete(slot);
      }
    }
    const sourceOperationIds = new Map();
    for (const operation of operations) {
      const ids = sourceOperationIds.get(operation.source_event_id) || [];
      ids.push(operation.operation_id);
      sourceOperationIds.set(operation.source_event_id, ids);
    }
    return {
      schema_version: PERFORMANCE_SCHEMA_VERSION,
      frame_rate: timeline.frame_rate,
      scene_id: timeline.scene_id,
      total_frames: timeline.total_frames,
      operations,
      source_map: [...sourceOperationIds.entries()].map(([sourceEventId, operationIds]) => ({
        source_event_id: sourceEventId,
        operation_ids: operationIds,
        primary_operation_id: operationIds[0],
      })),
    };
  }

  function cubicBezierCoordinate(t, first, second) {
    const inverse = 1 - t;
    return 3 * inverse * inverse * t * first
      + 3 * inverse * t * t * second
      + t * t * t;
  }

  function cubicBezierDerivative(t, first, second) {
    const inverse = 1 - t;
    return 3 * inverse * inverse * first
      + 6 * inverse * t * (second - first)
      + 3 * t * t * (1 - second);
  }

  function cubicBezierEasing(progress, x1, y1, x2, y2) {
    const target = clamp(progress, 0, 1);
    let parameter = target;
    for (let iteration = 0; iteration < 8; iteration += 1) {
      const error = cubicBezierCoordinate(parameter, x1, x2) - target;
      const derivative = cubicBezierDerivative(parameter, x1, x2);
      if (Math.abs(error) < 1e-7 || Math.abs(derivative) < 1e-7) break;
      parameter = clamp(parameter - error / derivative, 0, 1);
    }
    let lower = 0;
    let upper = 1;
    for (let iteration = 0; iteration < 12; iteration += 1) {
      const current = cubicBezierCoordinate(parameter, x1, x2);
      if (Math.abs(current - target) < 1e-7) break;
      if (current < target) lower = parameter;
      else upper = parameter;
      parameter = (lower + upper) / 2;
    }
    return cubicBezierCoordinate(parameter, y1, y2);
  }

  function sampleKeyframes(keyframes, progress, easing) {
    const terminal = keyframes.at(-1);
    if (!terminal) return 0;
    if (progress >= terminal.offset) return terminal.value;
    const nextIndex = keyframes.findIndex((keyframe) => keyframe.offset >= progress);
    if (nextIndex <= 0) return keyframes[0]?.value || 0;
    const previous = keyframes[nextIndex - 1];
    const next = keyframes[nextIndex];
    const span = next.offset - previous.offset;
    const localProgress = span <= 0 ? 1 : (progress - previous.offset) / span;
    const eased = easing === "ease-in-out-strong"
      ? cubicBezierEasing(localProgress, 0.77, 0, 0.175, 1)
      : cubicBezierEasing(localProgress, 0.23, 1, 0.32, 1);
    return previous.value + (next.value - previous.value) * eased;
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
    const inRange = plan.operations.filter((operation) => (
      frame >= operation.start_frame && frame < operation.end_frame
    ));
    const active = mode === "skip" || mode === "reduced-motion"
      ? inRange.filter((operation) => operation.kind === "numeric-tween") : inRange;
    let offsetX = 0;
    let offsetY = 0;
    const characterSamples = new Map();
    for (const operation of active) {
      const durationFrames = operation.end_frame - operation.start_frame;
      const localFrame = frame - operation.start_frame;
      const progress = durationFrames <= 1 ? 1 : localFrame / (durationFrames - 1);
      if (operation.kind === "shake") {
        const envelope = 1 - progress;
        const seconds = localFrame / plan.frame_rate;
        const phase = Math.PI * 2 * operation.frequency_hz * seconds;
        offsetX += operation.amplitude_x_px * Math.sin(phase) * envelope;
        offsetY += operation.amplitude_y_px * Math.sin(phase * 1.7) * envelope;
        continue;
      }
      const value = operation.kind === "numeric-keyframes"
        ? sampleKeyframes(operation.keyframes, progress, operation.easing)
        : (() => {
          const eased = 1 - (1 - progress) ** 3;
          const useFinal = mode === "skip"
            || (mode === "reduced-motion" && operation.channel !== "presentation.opacity");
          return useFinal ? operation.to : operation.from + (operation.to - operation.from) * eased;
        })();
      const key = `${operation.target.character_id}|${operation.target.slot}`;
      const sample = characterSamples.get(key) || {
        character_id: operation.target.character_id,
        slot: operation.target.slot,
        opacity: null,
        offset_y_px: 0,
        rotation_deg: 0,
        scale: 1,
      };
      if (operation.channel === "presentation.opacity") {
        sample.opacity = quantize(operation.value_space === "factor-from-baseline"
          ? (sample.opacity ?? 1) * value
          : value, 6);
      }
      if (operation.channel === "layout.offset-y") {
        sample.offset_y_px = quantize(sample.offset_y_px + value, 6);
      }
      if (operation.channel === "presentation.rotation") {
        sample.rotation_deg = quantize(sample.rotation_deg + value, 6);
      }
      if (operation.channel === "presentation.scale") {
        sample.scale = quantize(operation.value_space === "factor-from-baseline"
          ? sample.scale * value
          : value, 6);
      }
      characterSamples.set(key, sample);
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
      characters: [...characterSamples.values()],
    };
  }

  global.HaloCueScenePerformanceRuntime = Object.freeze({
    PERFORMANCE_SCHEMA_VERSION,
    PERFORMANCE_SAMPLE_SCHEMA_VERSION,
    buildScenePerformance,
    sampleScenePerformance,
  });
}(window));
