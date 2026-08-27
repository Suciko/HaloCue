import { sceneEventRegistry, type SceneEventDefinition } from "./sceneEventRegistry";
import type { CueEvent, HaloCueProject } from "./types";

export type EventIconKey = "dialogue" | "background" | "actor" | "wait" | "effect";

export type EventEditorField = {
  key: string;
  label: string;
  control: "character" | "slot" | "motion" | "boolean" | "text" | "background" | "number";
  hint?: string;
  multiline?: boolean;
  min?: number;
  max?: number;
  step?: number;
  allowNarrator?: boolean;
};

export type EventEditorContext = {
  eventId: string;
  selectedSlot: number;
  selectedCharacterId?: string | null;
  project: HaloCueProject;
};

export type EventEditorDefinition = {
  kind: string;
  label: string;
  timelineSupported: boolean;
  icon: EventIconKey;
  fields: readonly EventEditorField[];
  create: (context: EventEditorContext) => CueEvent;
  summary: (event: CueEvent) => string;
};

const field = (definition: EventEditorField): EventEditorField => Object.freeze(definition);

const fields = {
  dialogue: Object.freeze([
    field({ key: "character_id", label: "角色逻辑键", control: "character", hint: "#0 为旁白或画外音", allowNarrator: true }),
    field({ key: "text", label: "对白文本", control: "text", multiline: true }),
  ]),
  enter: Object.freeze([
    field({ key: "slot", label: "舞台栏位", control: "slot", min: 1, max: 5, step: 1 }),
    field({ key: "character_id", label: "角色逻辑键", control: "character" }),
  ]),
  exit: Object.freeze([
    field({ key: "slot", label: "舞台栏位", control: "slot", min: 1, max: 5, step: 1 }),
  ]),
  characterMotion: Object.freeze([
    field({ key: "slot", label: "目标栏位", control: "slot", min: 1, max: 5, step: 1 }),
    field({ key: "character_id", label: "角色逻辑键", control: "character" }),
    field({ key: "motion_id", label: "动作能力", control: "motion" }),
    field({
      key: "wait_for_completion",
      label: "等待动作完成",
      control: "boolean",
      hint: "关闭后，下一事件会与动作同时开始",
    }),
  ]),
  background: Object.freeze([
    field({ key: "resource_id", label: "资源逻辑键", control: "background" }),
  ]),
  backgroundPan: Object.freeze([
    field({ key: "pan_x", label: "水平移动", control: "number", min: -1, max: 1, step: 0.01 }),
    field({ key: "pan_y", label: "垂直移动", control: "number", min: -1, max: 1, step: 0.01 }),
    field({
      key: "wait_for_completion",
      label: "等待镜头完成",
      control: "boolean",
      hint: "关闭后，下一事件会与镜头移动同时开始",
    }),
  ]),
  screenShake: Object.freeze([
    field({ key: "intensity", label: "震动强度", control: "number", min: 0, max: 1, step: 0.05 }),
    field({
      key: "wait_for_completion",
      label: "等待震动完成",
      control: "boolean",
      hint: "关闭后，下一事件会与画面震动同时开始",
    }),
  ]),
  screenText: Object.freeze([
    field({ key: "text", label: "屏幕文字", control: "text" }),
  ]),
  hitEffect: Object.freeze([
    field({ key: "slot", label: "目标栏位", control: "slot", min: 1, max: 5, step: 1 }),
    field({ key: "intensity", label: "效果强度", control: "number", min: 0, max: 1, step: 0.05 }),
  ]),
} as const;

function textSummary(event: CueEvent): string {
  if (event.kind === "character-motion") {
    return `#${event.slot || "?"} · ${event.motion_id || "未选择动作"}`;
  }
  const value = event.text || event.character_id || event.resource_id || event.kind;
  return typeof value === "string" ? value : String(value);
}

function registered(
  kind: string,
  icon: EventIconKey,
  editorFields: readonly EventEditorField[],
  create: EventEditorDefinition["create"],
): EventEditorDefinition {
  const manifest = sceneEventRegistry.definition(kind);
  if (!manifest) throw new Error(`event editor catalog references unknown kind ${kind}`);
  return Object.freeze({
    kind,
    label: manifest.editor_label,
    timelineSupported: manifest.timeline_supported,
    icon,
    fields: editorFields,
    create,
    summary: textSummary,
  });
}

const CATALOG: Record<string, EventEditorDefinition> = {
  background: registered("background", "background", fields.background, ({ eventId, project }) => ({
    event_id: eventId,
    kind: "background",
    ...(project.resources.find((resource) => resource.role === "background")?.resource_id
      ? { resource_id: project.resources.find((resource) => resource.role === "background")?.resource_id }
      : {}),
  })),
  dialogue: registered("dialogue", "dialogue", fields.dialogue, ({ eventId }) => ({
    event_id: eventId,
    kind: "dialogue",
    text: "",
  })),
  enter: registered("enter", "actor", fields.enter, ({ eventId, selectedSlot, project }) => ({
    event_id: eventId,
    kind: "enter",
    slot: selectedSlot,
    ...(project.characters[0]?.character_id ? { character_id: project.characters[0].character_id } : {}),
  })),
  exit: registered("exit", "actor", fields.exit, ({ eventId, selectedSlot }) => ({
    event_id: eventId,
    kind: "exit",
    slot: selectedSlot,
  })),
  "character-motion": registered(
    "character-motion",
    "actor",
    fields.characterMotion,
    ({ eventId, selectedSlot, selectedCharacterId, project }) => ({
      event_id: eventId,
      kind: "character-motion",
      slot: selectedSlot,
      ...(selectedCharacterId || project.characters[0]?.character_id
        ? { character_id: selectedCharacterId || project.characters[0]?.character_id }
        : {}),
      motion_id: "motion/nod",
      wait_for_completion: true,
    }),
  ),
  wait: registered("wait", "wait", [], ({ eventId }) => ({ event_id: eventId, kind: "wait" })),
  "halocue.ba:background-pan": registered("halocue.ba:background-pan", "effect", fields.backgroundPan, ({ eventId }) => ({
    event_id: eventId,
    kind: "halocue.ba:background-pan",
    pan_x: 0.035,
    pan_y: 0,
    wait_for_completion: true,
  })),
  "halocue.ba:screen-shake": registered("halocue.ba:screen-shake", "effect", fields.screenShake, ({ eventId }) => ({
    event_id: eventId,
    kind: "halocue.ba:screen-shake",
    intensity: 0.35,
    wait_for_completion: true,
  })),
  "halocue.ba:screen-text": registered("halocue.ba:screen-text", "effect", fields.screenText, ({ eventId }) => ({
    event_id: eventId,
    kind: "halocue.ba:screen-text",
    text: "屏幕文字",
  })),
  "halocue.ba:hit-effect": registered("halocue.ba:hit-effect", "effect", fields.hitEffect, ({ eventId, selectedSlot }) => ({
    event_id: eventId,
    kind: "halocue.ba:hit-effect",
    slot: selectedSlot,
    intensity: 0.5,
  })),
};

function genericDefinition(manifest: SceneEventDefinition): EventEditorDefinition {
  return Object.freeze({
    kind: manifest.kind,
    label: manifest.editor_label,
    timelineSupported: manifest.timeline_supported,
    icon: "effect",
    fields: [],
    create: ({ eventId }) => ({ event_id: eventId, kind: manifest.kind }),
    summary: textSummary,
  });
}

export function eventEditorDefinition(kind: string): EventEditorDefinition | undefined {
  const manifest = sceneEventRegistry.definition(kind);
  if (!manifest) return undefined;
  return CATALOG[kind] || genericDefinition(manifest);
}

export function eventEditorDefinitions(): readonly EventEditorDefinition[] {
  return Object.freeze(sceneEventRegistry.definitions().map((manifest) => (
    eventEditorDefinition(manifest.kind) as EventEditorDefinition
  )));
}

export function eventLabel(kind: string): string | undefined {
  return eventEditorDefinition(kind)?.label;
}

export function eventSummary(event: CueEvent): string {
  return eventEditorDefinition(event.kind)?.summary(event) || textSummary(event);
}

export function createEditorEvent(kind: string, context: EventEditorContext): CueEvent {
  const definition = eventEditorDefinition(kind);
  if (!definition || !sceneEventRegistry.isTimelineSupported(kind)) {
    throw new RangeError(`unsupported scene event kind ${kind}`);
  }
  return definition.create(context);
}
