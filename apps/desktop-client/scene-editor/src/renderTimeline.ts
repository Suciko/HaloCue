import type { CueEvent, RenderTimeline, RenderTimelineEvent, SceneDescriptor } from "./types";
import { durationMs, isTimelineSupported, supportsNonBlocking } from "./sceneEventRegistry";

export const TIMELINE_SCHEMA_VERSION = "render-timeline/1.2" as const;
export const DEFAULT_FRAME_RATE = 30;

function clone<T>(value: T): T {
  return structuredClone(value);
}

function requireFrameRate(value: number): number {
  if (!Number.isInteger(value) || value < 1 || value > 240) {
    throw new RangeError("frameRate must be an integer between 1 and 240");
  }
  return value;
}

export function dialogueDurationMs(text: unknown): number {
  return durationMs({ kind: "dialogue", text });
}

export function eventDurationMs(event: CueEvent): number {
  return durationMs(event);
}

export function buildRenderTimeline(
  descriptor: SceneDescriptor,
  frameRate = DEFAULT_FRAME_RATE,
): RenderTimeline {
  if (!descriptor || descriptor.schema_version !== "scene-descriptor/1.0") {
    throw new Error("unsupported scene descriptor schema");
  }
  if (!Array.isArray(descriptor.events)) throw new TypeError("scene descriptor events must be an array");
  const fps = requireFrameRate(frameRate);
  const seenIds = new Set<string>();
  let cursor = 0;
  let totalFrames = 0;
  const events = descriptor.events.map((source, index): RenderTimelineEvent => {
    const eventId = typeof source.event_id === "string" ? source.event_id.trim() : "";
    if (!eventId) throw new Error(`event ${index} must have a non-empty event_id`);
    if (seenIds.has(eventId)) throw new Error(`duplicate event_id ${eventId}`);
    seenIds.add(eventId);
    if (!isTimelineSupported(source.kind)) {
      throw new RangeError(`unsupported render event kind ${String(source.kind)}`);
    }
    if (source.wait_for_completion === false && !supportsNonBlocking(source.kind)) {
      throw new RangeError(`event kind ${String(source.kind)} does not support non-blocking timing`);
    }
    const durationMs = eventDurationMs(source);
    const durationFrames = Math.max(1, Math.ceil(durationMs * fps / 1000));
    const waitForCompletion = source.wait_for_completion !== false;
    const item: RenderTimelineEvent = {
      event_id: eventId,
      kind: source.kind,
      start_frame: cursor,
      end_frame: cursor + durationFrames,
      duration_frames: durationFrames,
      duration_ms: durationMs,
      wait_for_completion: waitForCompletion,
      event: clone(source),
    };
    if (waitForCompletion) cursor = item.end_frame;
    totalFrames = Math.max(totalFrames, item.end_frame);
    return item;
  });
  return {
    schema_version: TIMELINE_SCHEMA_VERSION,
    frame_rate: fps,
    scene_id: descriptor.scene_id ?? null,
    events,
    total_frames: totalFrames,
  };
}
