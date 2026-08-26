export type EditorMode = "simple" | "professional";
export type InspectorTab = "character" | "dialogue" | "environment";

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
