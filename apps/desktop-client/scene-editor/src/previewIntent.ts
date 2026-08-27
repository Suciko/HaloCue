import { sceneById } from "./cueStateProjection";
import type {
  HaloCueProject,
  RenderTimelineEvent,
  SceneEvaluation,
  ScenePreviewIntent,
} from "./types";

export const PREVIEW_INTENT_SCHEMA_VERSION = "preview-intent/1.0" as const;

function terminalIntent(
  sceneId: string,
  cueId: string,
  item: RenderTimelineEvent,
  resolution: "cue-terminal" | "prior-renderable",
): ScenePreviewIntent {
  return {
    schema_version: PREVIEW_INTENT_SCHEMA_VERSION,
    scene_id: sceneId,
    cue_id: cueId,
    selection_kind: "cue",
    selected_event_id: null,
    target: {
      event_id: item.event_id,
      frame: item.end_frame - 1,
      alignment: "end",
      resolution,
    },
  };
}

export function buildPreviewIntent(
  project: HaloCueProject,
  evaluation: SceneEvaluation,
  selection: {
    cueId: string;
    kind: "cue" | "event";
    eventId?: string | null;
  },
): ScenePreviewIntent {
  const scene = sceneById(project, evaluation.scene_id);
  const cueIndex = scene.cues.findIndex((cue) => cue.cue_id === selection.cueId);
  if (cueIndex < 0) throw new Error(`场景中不存在 Cue ${selection.cueId}`);
  if (evaluation.descriptor.scene_id !== scene.scene_id) {
    throw new Error("预览意图与场景求值结果不一致");
  }
  const timeline = evaluation.timeline;
  const terminal = timeline.events.at(-1);
  if (!terminal) throw new Error("预览时间线没有可定位事件");
  const cue = scene.cues[cueIndex];

  if (selection.kind === "cue" || !selection.eventId) {
    const cueEventIds = new Set(cue.events.map((event) => event.event_id));
    const cueTerminal = [...timeline.events].reverse()
      .find((item) => cueEventIds.has(item.event_id));
    return terminalIntent(
      scene.scene_id,
      cue.cue_id,
      cueTerminal || terminal,
      cueTerminal ? "cue-terminal" : "prior-renderable",
    );
  }

  const selectedIndex = cue.events.findIndex((event) => event.event_id === selection.eventId);
  if (selectedIndex < 0) {
    throw new Error(`Cue ${cue.cue_id} 中不存在事件 ${selection.eventId}`);
  }
  const exact = timeline.events.find((item) => item.event_id === selection.eventId);
  if (exact) {
    return {
      schema_version: PREVIEW_INTENT_SCHEMA_VERSION,
      scene_id: scene.scene_id,
      cue_id: cue.cue_id,
      selection_kind: "event",
      selected_event_id: selection.eventId,
      target: {
        event_id: exact.event_id,
        frame: exact.start_frame,
        alignment: "start",
        resolution: "selected-event",
      },
    };
  }

  const orderedBeforeSelection = [
    ...scene.cues.slice(0, cueIndex).flatMap((item) => item.events),
    ...cue.events.slice(0, selectedIndex),
  ];
  const timelineByEventId = new Map(timeline.events.map((item) => [item.event_id, item]));
  const prior = [...orderedBeforeSelection]
    .reverse()
    .map((event) => timelineByEventId.get(event.event_id))
    .find((item): item is RenderTimelineEvent => Boolean(item));
  const target = prior || timeline.events[0];
  return {
    schema_version: PREVIEW_INTENT_SCHEMA_VERSION,
    scene_id: scene.scene_id,
    cue_id: cue.cue_id,
    selection_kind: "event",
    selected_event_id: selection.eventId,
    target: {
      event_id: target.event_id,
      frame: prior ? target.end_frame - 1 : target.start_frame,
      alignment: prior ? "end" : "start",
      resolution: prior ? "prior-renderable" : "scene-start",
    },
  };
}
