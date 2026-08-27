import { buildDescriptor } from "./descriptor";
import type { CapabilityRegistry } from "./capabilities";
import { buildRenderTimeline, DEFAULT_FRAME_RATE } from "./renderTimeline";
import { buildScenePerformance } from "./scenePerformance";
import { firstScene } from "./cueStateProjection";
import { diagnoseProject } from "./projectCodec";
import type { EvaluationDiagnostic, HaloCueProject, SceneEvaluation } from "./types";
import { isDescriptorRenderable } from "./sceneEventRegistry";

function diagnosticsForAdvancedEvents(project: HaloCueProject): EvaluationDiagnostic[] {
  const scene = firstScene(project);
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

export function evaluateScene(
  project: HaloCueProject,
  selectedCueId: string,
  options: { capabilityRegistry?: CapabilityRegistry } = {},
): SceneEvaluation {
  const descriptor = buildDescriptor(project, selectedCueId, options);
  const frameRate = Number(descriptor.presentation.frame_rate) || DEFAULT_FRAME_RATE;
  const projectDiagnostics = diagnoseProject(project)
    // Advanced namespaced events have a dedicated presentation warning below.
    .filter((diagnostic) => diagnostic.code !== "project.unknown_event_kind");
  const timeline = buildRenderTimeline(descriptor, frameRate);
  return {
    schema_version: "scene-evaluation/1.2",
    scene_id: descriptor.scene_id,
    descriptor,
    timeline,
    performance: buildScenePerformance(descriptor, timeline),
    diagnostics: [
      ...projectDiagnostics,
      ...diagnosticsForAdvancedEvents(project),
    ],
  };
}
