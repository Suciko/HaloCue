(function (global) {
  "use strict";

  // These values are compatibility data extracted from the authorized AA
  // PreviewScene and Character/ScenarioAnimation metadata. They are not AA
  // source code or asset bytes.
  const SLOT_WORLD_X = Object.freeze([-925, -435, 0, 435, 925]);
  const SLOT_WORLD_Z = Object.freeze([-0.9, -1, -1.1, -1.05, -0.95]);
  const DESIGN_WIDTH = 2560;
  const DESIGN_HEIGHT = 1440;
  // PreviewScene's orthographic camera and 0.0012012012 UI-root scale
  // expose 2960 authored units horizontally in its 1280x720 render target.
  // Character world positions therefore use a wider span than the 2560px
  // dialogue design canvas.
  const CHARACTER_VIEW_WIDTH = 2960;
  const MOVE_DURATION_MS = 500;
  const STANDBY_LUMINANCE_MULTIPLIER = 0.6;
  const TYPEWRITER_FRAMES_PER_GRAPHEME = 1;
  const TYPEWRITER_PUNCTUATION_PAUSE_FRAMES = 3;
  const TYPEWRITER_NEWLINE_PAUSE_FRAMES = 6;
  const DEFAULT_FRAME_RATE = 30;
  const EVENT_REGISTRY = global.HaloCueSceneEventRegistry;
  const PUNCTUATION = new Set(Array.from("，。！？；：、,.!?;:"));

  const DIALOGUE_LAYOUT = Object.freeze({
    container: Object.freeze({ x: 0, y: -832 }),
    name: Object.freeze({ x: -1189.9999, y: 426 }),
    text: Object.freeze({ x: -1184, y: 321 }),
    line: Object.freeze({ x: 0, y: 361 }),
    textBackground: Object.freeze({ x: 0, y: 272, rotation: -90 }),
  });

  function slotWorldPosition(slot) {
    if (!Number.isInteger(slot) || slot < 1 || slot > SLOT_WORLD_X.length) {
      throw new RangeError("AA slot must be an integer from 1 to 5.");
    }
    return Object.freeze({
      x: SLOT_WORLD_X[slot - 1],
      y: 0,
      z: SLOT_WORLD_Z[slot - 1],
    });
  }

  function worldXToPercent(x) {
    return ((Number(x) + CHARACTER_VIEW_WIDTH / 2) / CHARACTER_VIEW_WIDTH) * 100;
  }

  const SLOT_LEFT_PERCENT = Object.freeze(
    SLOT_WORLD_X.map((worldX) => worldXToPercent(worldX)),
  );

  function clamp01(value) {
    return Math.max(0, Math.min(1, Number(value)));
  }

  function easeInOutCubic(progress) {
    const t = clamp01(progress);
    return t < 0.5 ? 4 * t ** 3 : 1 - (-2 * t + 2) ** 3 / 2;
  }

  function interpolate(from, to, progress) {
    const eased = easeInOutCubic(progress);
    return from + (to - from) * eased;
  }

  function effectiveLuminance(rawLuminance, isStandby, ignoreStandby) {
    const raw = clamp01(rawLuminance);
    return raw * (isStandby && !ignoreStandby ? STANDBY_LUMINANCE_MULTIPLIER : 1);
  }

  function createCharacterState(slot, actor) {
    const position = slotWorldPosition(slot);
    return {
      slot,
      character_id: actor?.character_id ?? null,
      position,
      leftPercent: worldXToPercent(position.x),
      luminance: effectiveLuminance(1, false, false),
      rawLuminance: 1,
      isStandby: false,
      isOnTop: false,
      sortingOrder: slot,
      isCloseup: false,
      opacity: actor?.state === "visible" ? 1 : 0,
    };
  }

  function setPos(character, position) {
    const next = {
      x: Number(position?.x ?? 0),
      y: Number(position?.y ?? 0),
      z: Number(position?.z ?? 0),
    };
    character.position = next;
    character.leftPercent = worldXToPercent(next.x);
    return next;
  }

  function setLuminance(character, luminance, ignoreStandby) {
    character.rawLuminance = clamp01(luminance);
    character.luminance = effectiveLuminance(
      character.rawLuminance,
      character.isStandby,
      Boolean(ignoreStandby),
    );
    return character.luminance;
  }

  function updateStandby(character, standby) {
    character.isStandby = Boolean(standby);
    return setLuminance(character, character.rawLuminance, false);
  }

  function setOnTop(character, nextOrder) {
    character.isOnTop = true;
    character.sortingOrder = Number.isFinite(nextOrder) ? nextOrder : 1000 + character.slot;
    return character.sortingOrder;
  }

  function setCloseup(character, closeup) {
    character.isCloseup = Boolean(closeup);
    return character.isCloseup;
  }

  function moveAnimation(character, toPosition, durationMs) {
    const from = { ...character.position };
    const to = { ...toPosition };
    const duration = Number.isFinite(durationMs) ? Math.max(0, durationMs) : MOVE_DURATION_MS;
    return {
      from,
      to,
      durationMs: duration,
      easing: "ease-in-out-cubic",
      sample(progress) {
        return {
          x: interpolate(from.x, to.x, progress),
          y: interpolate(from.y, to.y, progress),
          z: interpolate(from.z, to.z, progress),
        };
      },
      complete() {
        return setPos(character, to);
      },
    };
  }

  function fadeAnimation(character, fadeIn, durationMs) {
    const duration = Number.isFinite(durationMs) ? Math.max(0, durationMs) : MOVE_DURATION_MS;
    const from = fadeIn ? 0 : character.opacity;
    const to = fadeIn ? 1 : 0;
    return {
      from,
      to,
      durationMs: duration,
      easing: "ease-in-out-cubic",
      sample(progress) {
        return interpolate(from, to, progress);
      },
      complete() {
        character.opacity = to;
        return character.opacity;
      },
    };
  }

  function hideAnimation(character) {
    character.opacity = 0;
    character.isOnTop = false;
    return character.opacity;
  }

  function graphemes(text) {
    return Array.from(String(text ?? ""));
  }

  function typewriterFrame(text, visibleCount) {
    return graphemes(text).slice(0, Math.max(0, Math.floor(visibleCount))).join("");
  }

  function typewriterCost(grapheme) {
    return TYPEWRITER_FRAMES_PER_GRAPHEME
      + (grapheme === "\n"
        ? TYPEWRITER_NEWLINE_PAUSE_FRAMES
        : PUNCTUATION.has(grapheme) ? TYPEWRITER_PUNCTUATION_PAUSE_FRAMES : 0);
  }

  function typewriterFrameAtFrame(text, localFrame) {
    const chars = graphemes(text);
    let budget = Math.max(0, Math.floor(localFrame));
    let revealCount = 0;
    for (const grapheme of chars) {
      const cost = typewriterCost(grapheme);
      if (budget < cost) break;
      budget -= cost;
      revealCount += 1;
    }
    return {
      visibleText: typewriterFrame(text, revealCount),
      revealCount,
      complete: revealCount >= chars.length,
    };
  }

  function typewriterDuration(text, charMs) {
    const frameMs = Number.isFinite(charMs) ? charMs : 32;
    return graphemes(text).reduce((total, grapheme) => total + typewriterCost(grapheme) * frameMs, 0);
  }

  function requireFrameRate(value) {
    if (!Number.isInteger(value) || value < 1 || value > 240) {
      throw new RangeError("frameRate must be an integer between 1 and 240");
    }
    return value;
  }

  function eventDurationMs(event) {
    if (!EVENT_REGISTRY || typeof EVENT_REGISTRY.durationMs !== "function") {
      throw new Error("scene event registry adapter is not loaded");
    }
    return EVENT_REGISTRY.durationMs(event);
  }

  function buildRenderTimeline(descriptor, options) {
    if (!descriptor || descriptor.schema_version !== "scene-descriptor/1.0") {
      throw new Error("unsupported scene descriptor schema");
    }
    if (!Array.isArray(descriptor.events)) {
      throw new Error("scene descriptor events must be an array");
    }
    const frameRate = requireFrameRate(options?.frameRate ?? DEFAULT_FRAME_RATE);
    const seenIds = new Set();
    let cursor = 0;
    const events = descriptor.events.map((source, index) => {
      if (!source || typeof source !== "object" || Array.isArray(source)) {
        throw new TypeError(`event ${index} must be an object`);
      }
      const eventId = typeof source.event_id === "string" ? source.event_id.trim() : "";
      if (!eventId) throw new Error(`event ${index} must have a non-empty event_id`);
      if (seenIds.has(eventId)) throw new Error(`duplicate event_id ${eventId}`);
      seenIds.add(eventId);
      if (!EVENT_REGISTRY || !EVENT_REGISTRY.isTimelineSupported(source.kind)) {
        throw new RangeError(`unsupported render event kind ${String(source.kind)}`);
      }
      const durationMs = eventDurationMs(source);
      const durationFrames = Math.max(1, Math.ceil(durationMs * frameRate / 1000));
      const startFrame = cursor;
      const endFrame = startFrame + durationFrames;
      cursor = endFrame;
      return {
        event_id: eventId,
        kind: source.kind,
        start_frame: startFrame,
        end_frame: endFrame,
        duration_frames: durationFrames,
        duration_ms: durationMs,
        event: JSON.parse(JSON.stringify(source)),
      };
    });
    return {
      schema_version: "render-timeline/1.0",
      frame_rate: frameRate,
      scene_id: descriptor.scene_id ?? null,
      events,
      total_frames: cursor,
    };
  }

  function sampleRenderTimeline(timeline, frame) {
    if (!timeline || timeline.schema_version !== "render-timeline/1.0") {
      throw new Error("unsupported render timeline schema");
    }
    if (!timeline.total_frames || !timeline.events.length) {
      return { frame: 0, eventIndex: -1, item: null, localFrame: 0, localMs: 0, progress: 0 };
    }
    const requested = Number.isFinite(Number(frame)) ? Math.floor(Number(frame)) : 0;
    const resolvedFrame = Math.max(0, Math.min(timeline.total_frames - 1, requested));
    const eventIndex = timeline.events.findIndex((item) => (
      resolvedFrame >= item.start_frame && resolvedFrame < item.end_frame
    ));
    const item = timeline.events[eventIndex];
    const localFrame = resolvedFrame - item.start_frame;
    return {
      frame: resolvedFrame,
      eventIndex,
      item,
      localFrame,
      localMs: localFrame * 1000 / timeline.frame_rate,
      progress: item.duration_frames <= 1 ? 1 : localFrame / (item.duration_frames - 1),
    };
  }

  function timelineFrameForEvent(timeline, eventIndex, complete) {
    const index = Math.max(0, Math.min(timeline.events.length - 1, Math.floor(Number(eventIndex) || 0)));
    const item = timeline.events[index];
    if (!item) return 0;
    return complete === false ? item.start_frame : item.end_frame - 1;
  }

  function queueTypewriter(text, options) {
    const chars = graphemes(text);
    const charMs = Number.isFinite(options?.charMs) ? options.charMs : 32;
    return {
      text: String(text ?? ""),
      length: chars.length,
      durationMs: typewriterDuration(text, charMs),
      frame(elapsedMs) {
        return typewriterFrameAtFrame(text, Math.ceil(Math.max(0, elapsedMs) / charMs));
      },
      complete() {
        return typewriterFrame(text, chars.length);
      },
    };
  }

  global.HaloCueAARuntime = Object.freeze({
    DESIGN_WIDTH,
    DESIGN_HEIGHT,
    CHARACTER_VIEW_WIDTH,
    DEFAULT_FRAME_RATE,
    DIALOGUE_LAYOUT,
    MOVE_DURATION_MS,
    SLOT_WORLD_X,
    SLOT_WORLD_Z,
    SLOT_LEFT_PERCENT,
    STANDBY_LUMINANCE_MULTIPLIER,
    buildRenderTimeline,
    clamp01,
    createCharacterState,
    effectiveLuminance,
    easeInOutCubic,
    eventDurationMs,
    fadeAnimation,
    hideAnimation,
    moveAnimation,
    queueTypewriter,
    sampleRenderTimeline,
    setCloseup,
    setLuminance,
    setOnTop,
    setPos,
    slotWorldPosition,
    typewriterDuration,
    typewriterFrame,
    typewriterFrameAtFrame,
    timelineFrameForEvent,
    updateStandby,
    worldXToPercent,
  });
}(window));
