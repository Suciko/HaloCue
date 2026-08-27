import { buildPreviewIntent } from "./previewIntent";
import { evaluateScene } from "./sceneEvaluation";
import type {
  EditorMode,
  HaloCueProject,
  SceneEvaluation,
  ScenePreviewIntent,
} from "./types";

export type PreviewCompilationRequest = {
  project: HaloCueProject;
  mode: EditorMode;
  selectedSceneId: string;
  selectedCueId: string;
  selectedEventId: string | null;
};

export type PreviewCompilation = {
  generation: number;
  request: PreviewCompilationRequest;
  evaluation: SceneEvaluation;
  intent: ScenePreviewIntent;
};

function sameRequest(
  left: PreviewCompilationRequest,
  right: PreviewCompilationRequest,
): boolean {
  return left.project === right.project
    && left.mode === right.mode
    && left.selectedSceneId === right.selectedSceneId
    && left.selectedCueId === right.selectedCueId
    && left.selectedEventId === right.selectedEventId;
}

function sameEvaluationInput(
  compilation: PreviewCompilation,
  request: PreviewCompilationRequest,
): boolean {
  return compilation.request.project === request.project
    && compilation.request.selectedSceneId === request.selectedSceneId
    && compilation.request.selectedCueId === request.selectedCueId;
}

export function compilePreview(
  request: PreviewCompilationRequest,
  generation = 0,
  previous?: PreviewCompilation,
): PreviewCompilation {
  const evaluation = previous && sameEvaluationInput(previous, request)
    ? previous.evaluation
    : evaluateScene(request.project, request.selectedCueId, {
      sceneId: request.selectedSceneId,
    });
  const intent = buildPreviewIntent(request.project, evaluation, {
    cueId: request.selectedCueId,
    kind: request.mode === "professional" ? "event" : "cue",
    eventId: request.mode === "professional" ? request.selectedEventId : null,
  });
  return { generation, request, evaluation, intent };
}

export class PreviewCompilationCoordinator {
  private generation: number;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private pending: PreviewCompilationRequest | null = null;
  private current: PreviewCompilation;

  constructor(
    initial: PreviewCompilation,
    private readonly publish: (compilation: PreviewCompilation) => void,
    private readonly delayMs = 72,
  ) {
    this.current = initial;
    this.generation = initial.generation;
  }

  request(
    request: PreviewCompilationRequest,
    priority: "coalesced" | "immediate" = "coalesced",
  ): number {
    if (this.pending && sameRequest(this.pending, request)) {
      if (priority === "immediate") this.flush();
      return this.generation;
    }
    if (!this.pending && sameRequest(this.current.request, request)) {
      return this.generation;
    }
    this.cancelTimer();
    this.pending = request;
    this.generation += 1;
    if (priority === "immediate") {
      this.flush();
    } else {
      const generation = this.generation;
      this.timer = setTimeout(() => this.compilePending(generation), this.delayMs);
    }
    return this.generation;
  }

  flush(): void {
    if (!this.pending) return;
    this.cancelTimer();
    this.compilePending(this.generation);
  }

  dispose(): void {
    this.cancelTimer();
    this.pending = null;
    this.generation += 1;
  }

  private cancelTimer(): void {
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
  }

  private compilePending(generation: number): void {
    if (generation !== this.generation || !this.pending) return;
    const request = this.pending;
    this.pending = null;
    this.timer = null;
    const compilation = compilePreview(request, generation, this.current);
    if (generation !== this.generation) return;
    this.current = compilation;
    this.publish(compilation);
  }
}
