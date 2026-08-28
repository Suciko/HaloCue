export type EditorMode = "simple" | "professional";
export type InspectorTab = "character" | "dialogue" | "environment";
export type EditorSelection = {
  selectedChapterId: string;
  selectedSceneId: string;
  selectedCueId: string;
  selectedEventId: string | null;
  selectedEventIds: string[];
  eventSelectionAnchorId: string | null;
};
export type EditorTransactionResult = {
  status: "committed" | "no-op";
  revision: number;
};
export type EditorAutosaveState = {
  status: "saved" | "pending" | "failed";
  savedRevision: number;
  pendingRevision: number | null;
  error: string | null;
};
export type QuickEffectKind =
  | "halocue.ba:background-pan"
  | "halocue.ba:screen-shake"
  | "halocue.ba:screen-text"
  | "halocue.ba:hit-effect";

export type StageMedia = {
  kind: "portrait" | "spine" | "spine-frame";
  preview_uri?: string;
  bundle_key?: string;
  animation?: string;
  anchor_x?: number;
  anchor_y?: number;
  scale?: number;
  offset_x?: number;
  offset_y?: number;
};

export type Character = {
  character_id: string;
  name: string;
  dialogue_name?: string;
  club_name?: string;
  avatar_key?: string;
  resource_id?: string;
  capability_id?: string;
  stage_media?: StageMedia;
  [key: string]: unknown;
};

export type CapabilityStateKind = "expression" | "motion" | "emoticon" | "transition";

export type CapabilityAdapterValue = string | number | boolean | null;

export type CapabilityState = {
  state_id: string;
  label: string;
  adapter_state?: Record<string, CapabilityAdapterValue>;
};

export type CharacterCapabilities = {
  schema_version: "character-capabilities/1.0";
  capability_id: string;
  character_id: string;
  expression: CapabilityState[];
  motion: CapabilityState[];
  emoticon: CapabilityState[];
  transition: CapabilityState[];
  extensions?: Record<string, unknown>;
};

export type Resource = {
  resource_id: string;
  role: string;
  logical_key: string;
  preview_uri?: string;
  aa_key?: string;
  focus_x?: number;
  focus_y?: number;
  [key: string]: unknown;
};

export type CueEvent = {
  event_id: string;
  kind: string;
  character_id?: string;
  resource_id?: string;
  slot?: number;
  text?: string;
  display_name?: string;
  duration_ms?: number;
  wait_for_completion?: boolean;
  expression_id?: string;
  motion_id?: string;
  emoticon_id?: string;
  focus?: boolean;
  [key: string]: unknown;
};

export type Cue = {
  cue_id: string;
  title?: string;
  events: CueEvent[];
  [key: string]: unknown;
};

export type Scene = {
  scene_id: string;
  title?: string;
  cues: Cue[];
  [key: string]: unknown;
};

export type Chapter = {
  chapter_id: string;
  title?: string;
  scenes: Scene[];
  [key: string]: unknown;
};

export type HaloCueProject = {
  schema_version: "halocue-project/1.1";
  project_id: string;
  title?: string;
  characters: Character[];
  resources: Resource[];
  chapters: Chapter[];
  [key: string]: unknown;
};

export type SceneDescriptor = {
  schema_version: "scene-descriptor/1.0";
  scene_id: string;
  location_label?: string;
  presentation: Record<string, unknown>;
  background: Record<string, unknown> | null;
  initial_background: Record<string, unknown> | null;
  actors: Array<Record<string, unknown>>;
  initial_actors: Array<Record<string, unknown>>;
  events: CueEvent[];
};

export type RenderTimelineEvent = {
  event_id: string;
  kind: string;
  start_frame: number;
  end_frame: number;
  duration_frames: number;
  duration_ms: number;
  wait_for_completion: boolean;
  event: CueEvent;
};

export type RenderTimeline = {
  schema_version: "render-timeline/1.2";
  frame_rate: number;
  scene_id: string | null;
  events: RenderTimelineEvent[];
  total_frames: number;
};

export type PerformanceExecutionMode = "play" | "sample" | "skip" | "reduced-motion";

export type StageShakeOperation = {
  operation_id: string;
  source_event_id: string;
  kind: "shake";
  target: { kind: "stage"; target_id: "stage/global" };
  channel: "geometry.offset";
  value_space: "relative-to-baseline";
  start_frame: number;
  end_frame: number;
  amplitude_x_px: number;
  amplitude_y_px: number;
  frequency_hz: number;
};

export type CharacterTweenChannel =
  | "presentation.opacity"
  | "layout.offset-y"
  | "presentation.scale";

export type CharacterTweenOperation = {
  operation_id: string;
  source_event_id: string;
  kind: "numeric-tween";
  target: { kind: "character"; character_id: string; slot: number };
  channel: CharacterTweenChannel;
  value_space: "absolute" | "relative-to-baseline" | "factor-from-baseline";
  start_frame: number;
  end_frame: number;
  from: number;
  to: number;
  easing: "ease-out-cubic";
};

export type CharacterKeyframeChannel =
  | "presentation.opacity"
  | "layout.offset-y"
  | "presentation.scale"
  | "presentation.rotation";

export type CharacterKeyframeOperation = {
  operation_id: string;
  source_event_id: string;
  kind: "numeric-keyframes";
  target: { kind: "character"; character_id: string; slot: number };
  channel: CharacterKeyframeChannel;
  value_space: "absolute" | "relative-to-baseline" | "factor-from-baseline";
  start_frame: number;
  end_frame: number;
  keyframes: Array<{ offset: number; value: number }>;
  easing: "ease-in-out-strong" | "ease-out-emphasized";
};

export type ScenePerformanceOperation =
  | StageShakeOperation
  | CharacterTweenOperation
  | CharacterKeyframeOperation;

export type PerformanceSourceMapEntry = {
  source_event_id: string;
  operation_ids: string[];
  primary_operation_id: string;
};

export type ScenePerformancePlan = {
  schema_version: "scene-performance/1.4";
  frame_rate: number;
  scene_id: string | null;
  total_frames: number;
  operations: ScenePerformanceOperation[];
  source_map: PerformanceSourceMapEntry[];
};

export type PreviewIntentResolution =
  | "selected-event"
  | "cue-terminal"
  | "prior-renderable"
  | "scene-start"
  | "explicit-frame";

export type ScenePreviewIntent = {
  schema_version: "preview-intent/1.0" | "preview-intent/1.1";
  scene_id: string;
  cue_id: string;
  selection_kind: "cue" | "event" | "playhead";
  selected_event_id: string | null;
  target: {
    event_id: string;
    frame: number;
    alignment: "start" | "end" | "exact";
    resolution: PreviewIntentResolution;
  };
};

export type ScenePerformanceSample = {
  schema_version: "scene-performance-sample/1.0";
  frame: number;
  mode: PerformanceExecutionMode;
  active_operation_ids: string[];
  stage: { offset_x_px: number; offset_y_px: number };
  characters: Array<{
    character_id: string;
    slot: number;
    opacity: number | null;
    offset_y_px: number;
    rotation_deg: number;
    scale: number;
  }>;
};

export type EvaluationDiagnostic = {
  code: string;
  severity: "info" | "warning" | "error";
  path: string;
  message: string;
};

export type SceneEvaluation = {
  schema_version: "scene-evaluation/1.5";
  scene_id: string;
  descriptor: SceneDescriptor;
  timeline: RenderTimeline;
  performance: ScenePerformancePlan;
  diagnostics: EvaluationDiagnostic[];
};
