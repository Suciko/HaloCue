import rawManifest from "../../../../packages/contracts/scene-events/1.2.json";

export type SceneEventDefinition = {
  kind: string;
  descriptor_renderable: boolean;
  timeline_supported: boolean;
  visual_only: boolean;
  supports_non_blocking: boolean;
  duration_policy: "fixed" | "dialogue-aa-v1";
  default_duration_ms: number | null;
  simple_action: string | null;
  editor_label: string;
};

export type SceneEventDurationInput = {
  kind: string;
  duration_ms?: unknown;
  text?: unknown;
};

type SceneEventManifest = {
  schema_version: "scene-events/1.2";
  events: SceneEventDefinition[];
};

export type SceneEventRegistry = {
  definition: (kind: unknown) => SceneEventDefinition | undefined;
  definitions: () => readonly SceneEventDefinition[];
  isTimelineSupported: (kind: unknown) => boolean;
  isDescriptorRenderable: (kind: unknown) => boolean;
  isVisualOnly: (kind: unknown) => boolean;
  supportsNonBlocking: (kind: unknown) => boolean;
  durationMs: (event: SceneEventDurationInput) => number;
};

const TYPEWRITER_GRAPHEME_MS = 32;
const TYPEWRITER_PUNCTUATION_PAUSE_MS = 96;
const TYPEWRITER_NEWLINE_PAUSE_MS = 192;
const DIALOGUE_HOLD_MS = 650;
const PUNCTUATION = new Set(Array.from("，。！？；：、,.!?;:"));

function validateManifest(value: unknown): SceneEventManifest {
  if (!value || typeof value !== "object") throw new Error("scene event manifest must be an object");
  const manifest = value as Partial<SceneEventManifest>;
  if (
    manifest.schema_version !== "scene-events/1.2"
    || !Array.isArray(manifest.events)
    || manifest.events.length === 0
  ) {
    throw new Error("unsupported scene event manifest schema");
  }
  const seen = new Set<string>();
  const events = manifest.events.map((event, index) => {
    if (!event || typeof event !== "object" || typeof event.kind !== "string" || !event.kind.trim()) {
      throw new Error(`scene event definition ${index} must have a non-empty kind`);
    }
    const kind = event.kind.trim();
    if (seen.has(kind)) throw new Error(`duplicate scene event kind ${kind}`);
    seen.add(kind);
    if (
      typeof event.descriptor_renderable !== "boolean"
      || typeof event.timeline_supported !== "boolean"
      || typeof event.visual_only !== "boolean"
      || typeof event.supports_non_blocking !== "boolean"
      || typeof event.editor_label !== "string"
      || !event.editor_label.trim()
      || (event.simple_action !== null && typeof event.simple_action !== "string")
    ) {
      throw new Error(`scene event definition ${kind} has invalid metadata`);
    }
    if (event.duration_policy === "fixed") {
      if (!Number.isInteger(event.default_duration_ms) || (event.default_duration_ms ?? 0) <= 0) {
        throw new Error(`fixed scene event ${kind} must have a positive default duration`);
      }
    } else if (event.duration_policy === "dialogue-aa-v1") {
      if (event.default_duration_ms !== null) throw new Error(`dialogue event ${kind} cannot have a fixed duration`);
    } else {
      throw new Error(`scene event ${kind} has an unknown duration policy`);
    }
    return Object.freeze({ ...event, kind });
  });
  return { schema_version: manifest.schema_version, events };
}

function dialogueDurationMs(text: unknown): number {
  let duration = DIALOGUE_HOLD_MS;
  for (const grapheme of Array.from(String(text ?? ""))) {
    duration += TYPEWRITER_GRAPHEME_MS;
    if (grapheme === "\n") duration += TYPEWRITER_NEWLINE_PAUSE_MS;
    else if (PUNCTUATION.has(grapheme)) duration += TYPEWRITER_PUNCTUATION_PAUSE_MS;
  }
  return duration;
}

export function createSceneEventRegistry(value: unknown = rawManifest): SceneEventRegistry {
  const manifest = validateManifest(value);
  const definitions = Object.freeze(manifest.events.slice());
  const byKind = new Map(definitions.map((event) => [event.kind, event]));
  const definition = (kind: unknown) => typeof kind === "string" ? byKind.get(kind) : undefined;
  return {
    definition,
    definitions: () => definitions,
    isTimelineSupported: (kind) => Boolean(definition(kind)?.timeline_supported),
    isDescriptorRenderable: (kind) => Boolean(definition(kind)?.descriptor_renderable),
    isVisualOnly: (kind) => Boolean(definition(kind)?.visual_only),
    supportsNonBlocking: (kind) => Boolean(definition(kind)?.supports_non_blocking),
    durationMs: (event) => {
      const definitionValue = definition(event.kind);
      if (!definitionValue?.timeline_supported) {
        throw new RangeError(`unsupported render event kind ${String(event.kind)}`);
      }
      const explicit = event.duration_ms;
      if (explicit !== undefined && explicit !== null) {
        if (typeof explicit !== "number" || !Number.isFinite(explicit) || explicit <= 0) {
          throw new RangeError("event duration_ms must be a finite positive number");
        }
        return Math.max(1, Math.ceil(explicit));
      }
      if (definitionValue.duration_policy === "dialogue-aa-v1") return dialogueDurationMs(event.text);
      return definitionValue.default_duration_ms as number;
    },
  };
}

export const sceneEventRegistry = createSceneEventRegistry();
export const sceneEventDefinitions = sceneEventRegistry.definitions;
export const definition = sceneEventRegistry.definition;
export const isTimelineSupported = sceneEventRegistry.isTimelineSupported;
export const isDescriptorRenderable = sceneEventRegistry.isDescriptorRenderable;
export const isVisualOnly = sceneEventRegistry.isVisualOnly;
export const supportsNonBlocking = sceneEventRegistry.supportsNonBlocking;
export const durationMs = sceneEventRegistry.durationMs;
