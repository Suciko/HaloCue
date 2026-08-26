import { buildDescriptor } from "./descriptor";
import type { CapabilityRegistry } from "./capabilities";
import { buildRenderTimeline, DEFAULT_FRAME_RATE } from "./renderTimeline";
import { firstScene } from "./projectStore";
import type { EvaluationDiagnostic, HaloCueProject, SceneEvaluation } from "./types";

function diagnosticsForAdvancedEvents(project: HaloCueProject): EvaluationDiagnostic[] {
  const scene = firstScene(project);
  const diagnostics: EvaluationDiagnostic[] = [];
  scene.cues.forEach((cue, cueIndex) => {
    cue.events.forEach((event, eventIndex) => {
      if (!event.kind.includes(":")) return;
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
  return {
    schema_version: "scene-evaluation/1.0",
    scene_id: descriptor.scene_id,
    descriptor,
    timeline: buildRenderTimeline(descriptor, frameRate),
    diagnostics: diagnosticsForAdvancedEvents(project),
  };
}
