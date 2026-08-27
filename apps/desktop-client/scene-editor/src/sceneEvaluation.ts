import { buildDescriptor } from "./descriptor";
import type { CapabilityRegistry } from "./capabilities";
import { buildRenderTimeline, DEFAULT_FRAME_RATE } from "./renderTimeline";
import { buildScenePerformance } from "./scenePerformance";
import { sceneById } from "./cueStateProjection";
import { diagnoseProject } from "./projectCodec";
import type { EvaluationDiagnostic, HaloCueProject, SceneEvaluation } from "./types";
import { isDescriptorRenderable } from "./sceneEventRegistry";

function diagnosticsForAdvancedEvents(
  project: HaloCueProject,
  sceneId?: string,
): EvaluationDiagnostic[] {
  const scene = sceneById(project, sceneId);
  const diagnostics: EvaluationDiagnostic[] = [];
  scene.cues.forEach((cue, cueIndex) => {
    cue.events.forEach((event, eventIndex) => {
      if (!event.kind.includes(":") || isDescriptorRenderable(event.kind)) return;
      diagnostics.push({
        code: "scene.advanced_event_omitted",
        severity: "warning",
        path: `scene:${scene.scene_id}.cues[${cueIndex}].events[${eventIndex}]`,
        message: `专业演出 ${event.kind} 会保留在项目中，但当前 AA 预览不直接渲染。`,
      });
    });
  });
  return diagnostics;
}

function diagnosticsForCharacterMotionTargets(
  descriptor: SceneEvaluation["descriptor"],
): EvaluationDiagnostic[] {
  const slots = new Map<number, string>();
  for (const actor of descriptor.initial_actors || []) {
    if (
      actor.state === "visible"
      && typeof actor.slot === "number"
      && Number.isInteger(actor.slot)
      && typeof actor.character_id === "string"
      && actor.character_id
    ) {
      slots.set(actor.slot, actor.character_id);
    }
  }
  const diagnostics: EvaluationDiagnostic[] = [];
  descriptor.events.forEach((event) => {
    const slot = Number(event.slot);
    if (event.kind === "enter" && Number.isInteger(slot) && event.character_id) {
      slots.set(slot, event.character_id);
      return;
    }
    if (event.kind === "exit" && Number.isInteger(slot)) {
      slots.delete(slot);
      return;
    }
    if (event.kind !== "character-motion") return;
    const occupied = Number.isInteger(slot) ? slots.get(slot) : undefined;
    if (slot >= 1 && slot <= 5 && occupied && (!event.character_id || event.character_id === occupied)) {
      return;
    }
    diagnostics.push({
      code: "scene.character_motion_target_unavailable",
      severity: "error",
      path: `event:${event.event_id}`,
      message: `角色动作 ${event.event_id} 必须位于目标角色入场之后、退场之前。`,
    });
  });
  return diagnostics;
}

export function evaluateScene(
  project: HaloCueProject,
  selectedCueId: string,
  options: { capabilityRegistry?: CapabilityRegistry; sceneId?: string } = {},
): SceneEvaluation {
  const descriptor = buildDescriptor(project, selectedCueId, options);
  const frameRate = Number(descriptor.presentation.frame_rate) || DEFAULT_FRAME_RATE;
  const projectDiagnostics = diagnoseProject(project)
    // Advanced namespaced events have a dedicated presentation warning below.
    .filter((diagnostic) => diagnostic.code !== "project.unknown_event_kind");
  const timeline = buildRenderTimeline(descriptor, frameRate);
  return {
    schema_version: "scene-evaluation/1.4",
    scene_id: descriptor.scene_id,
    descriptor,
    timeline,
    performance: buildScenePerformance(descriptor, timeline),
    diagnostics: [
      ...projectDiagnostics,
      ...diagnosticsForAdvancedEvents(project, descriptor.scene_id),
      ...diagnosticsForCharacterMotionTargets(descriptor),
    ],
  };
}
