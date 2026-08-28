import { eventLabel } from "./eventEditorCatalog";
import type { Cue, RenderTimeline, RenderTimelineEvent } from "./types";

export const SHOT_TIMELINE_SCHEMA_VERSION = "shot-timeline/1.0" as const;

export const SHOT_TIMELINE_TRACKS = [
  { id: "camera", label: "Camera" },
  { id: "stage", label: "Stage" },
  { id: "character", label: "Character" },
  { id: "dialogue", label: "Dialogue / Overlay" },
  { id: "effect", label: "Effect / Timing" },
] as const;

export type ShotTimelineTrackId = (typeof SHOT_TIMELINE_TRACKS)[number]["id"];

export type ShotTimelineClip = {
  event_id: string;
  kind: string;
  track_id: ShotTimelineTrackId;
  lane_index: number;
  label: string;
  start_frame: number;
  end_frame: number;
  duration_frames: number;
  duration_ms: number;
  wait_for_completion: boolean;
  character_id?: string;
  slot?: number;
};

export type ShotTimelineTrack = {
  id: ShotTimelineTrackId;
  label: string;
  lane_count: number;
  clips: ShotTimelineClip[];
};

export type ShotTimelineProjection = {
  schema_version: typeof SHOT_TIMELINE_SCHEMA_VERSION;
  scene_id: string;
  cue_id: string;
  frame_rate: number;
  start_frame: number;
  end_frame: number;
  total_frames: number;
  trackIds: ShotTimelineTrackId[];
  tracks: ShotTimelineTrack[];
  unmappedEventIds: string[];
};

function trackIdFor(event: RenderTimelineEvent): ShotTimelineTrackId {
  if (event.kind === "halocue.ba:background-pan" || event.kind.includes("camera")) {
    return "camera";
  }
  if (event.kind === "background") return "stage";
  if (event.kind === "dialogue" || event.kind === "halocue.ba:screen-text") {
    return "dialogue";
  }
  if (event.kind === "enter" || event.kind === "exit" || event.kind === "character-motion") {
    return "character";
  }
  return "effect";
}

type UnplacedShotTimelineClip = Omit<ShotTimelineClip, "lane_index">;

function clipFor(event: RenderTimelineEvent): UnplacedShotTimelineClip {
  const source = event.event;
  return {
    event_id: event.event_id,
    kind: event.kind,
    track_id: trackIdFor(event),
    label: eventLabel(event.kind) || event.kind,
    start_frame: event.start_frame,
    end_frame: event.end_frame,
    duration_frames: event.duration_frames,
    duration_ms: event.duration_ms,
    wait_for_completion: event.wait_for_completion,
    ...(typeof source.character_id === "string" ? { character_id: source.character_id } : {}),
    ...(typeof source.slot === "number" ? { slot: source.slot } : {}),
  };
}

function assignClipLanes(clips: UnplacedShotTimelineClip[]): {
  clips: ShotTimelineClip[];
  lane_count: number;
} {
  const laneEndFrames: number[] = [];
  const placed = clips.map((clip) => {
    let laneIndex = laneEndFrames.findIndex((endFrame) => endFrame <= clip.start_frame);
    if (laneIndex < 0) laneIndex = laneEndFrames.length;
    laneEndFrames[laneIndex] = clip.end_frame;
    return { ...clip, lane_index: laneIndex };
  });
  return {
    clips: placed,
    lane_count: Math.max(1, laneEndFrames.length),
  };
}

export function buildShotTimeline({
  sceneId,
  cue,
  timeline,
}: {
  sceneId: string;
  cue: Cue;
  timeline: RenderTimeline;
}): ShotTimelineProjection {
  const timelineByEventId = new Map(timeline.events.map((event) => [event.event_id, event]));
  const clips = cue.events
    .map((event) => timelineByEventId.get(event.event_id))
    .filter((event): event is RenderTimelineEvent => Boolean(event))
    .map(clipFor);
  const unmappedEventIds = cue.events
    .filter((event) => !timelineByEventId.has(event.event_id))
    .map((event) => event.event_id);
  const tracks = SHOT_TIMELINE_TRACKS.map(({ id, label }) => ({
    id,
    label,
    ...assignClipLanes(clips.filter((clip) => clip.track_id === id)),
  }));
  const startFrame = clips.reduce(
    (minimum, clip) => Math.min(minimum, clip.start_frame),
    clips[0]?.start_frame ?? 0,
  );
  const endFrame = clips.reduce(
    (maximum, clip) => Math.max(maximum, clip.end_frame),
    startFrame,
  );
  return {
    schema_version: SHOT_TIMELINE_SCHEMA_VERSION,
    scene_id: sceneId,
    cue_id: cue.cue_id,
    frame_rate: timeline.frame_rate,
    start_frame: startFrame,
    end_frame: endFrame,
    total_frames: timeline.total_frames,
    trackIds: SHOT_TIMELINE_TRACKS.map(({ id }) => id),
    tracks,
    unmappedEventIds,
  };
}
