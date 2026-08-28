import { isDescriptorRenderable, supportsNonBlocking } from "./sceneEventRegistry";
import type { HaloCueProject } from "./types";

export const LEGACY_PROJECT_SCHEMA_VERSION = "halocue-project/1.0" as const;
export const PROJECT_SCHEMA_VERSION = "halocue-project/1.1" as const;

export type ProjectDiagnostic = {
  code: string;
  severity: "info" | "warning" | "error";
  path: string;
  message: string;
};

export type ProjectCodecResult = {
  project: HaloCueProject | null;
  diagnostics: ProjectDiagnostic[];
  migrated: boolean;
};

const CUE_ID_NAMESPACE = "5f24a298-2c02-4ec0-a4c9-b09078060c26";
const STAGE_MEDIA_KINDS = new Set(["portrait", "spine", "spine-frame"]);

function clone<T>(value: T): T {
  return structuredClone(value);
}

function diagnostic(
  code: string,
  path: string,
  message: string,
  severity: ProjectDiagnostic["severity"] = "error",
): ProjectDiagnostic {
  return { code, severity, path, message };
}

function utf8(value: string): Uint8Array {
  return new TextEncoder().encode(value);
}

function uuidBytes(value: string): Uint8Array {
  const hex = value.replaceAll("-", "");
  const bytes = new Uint8Array(16);
  for (let index = 0; index < bytes.length; index += 1) {
    bytes[index] = Number.parseInt(hex.slice(index * 2, index * 2 + 2), 16);
  }
  return bytes;
}

// Synchronous SHA-1 is intentionally local so browser file import can preserve
// the Python model's UUID5 migration without making the repository async.
function sha1(input: Uint8Array): Uint8Array {
  const bitLength = input.length * 8;
  const paddedLength = Math.ceil((input.length + 9) / 64) * 64;
  const bytes = new Uint8Array(paddedLength);
  bytes.set(input);
  bytes[input.length] = 0x80;
  const view = new DataView(bytes.buffer);
  view.setUint32(paddedLength - 4, bitLength >>> 0, false);
  view.setUint32(paddedLength - 8, Math.floor(bitLength / 0x100000000), false);
  let h0 = 0x67452301;
  let h1 = 0xefcdab89;
  let h2 = 0x98badcfe;
  let h3 = 0x10325476;
  let h4 = 0xc3d2e1f0;
  const words = new Uint32Array(80);

  for (let offset = 0; offset < bytes.length; offset += 64) {
    for (let index = 0; index < 16; index += 1) words[index] = view.getUint32(offset + index * 4, false);
    for (let index = 16; index < 80; index += 1) {
      const value = words[index - 3] ^ words[index - 8] ^ words[index - 14] ^ words[index - 16];
      words[index] = (value << 1) | (value >>> 31);
    }
    let a = h0;
    let b = h1;
    let c = h2;
    let d = h3;
    let e = h4;
    for (let index = 0; index < 80; index += 1) {
      let f: number;
      let k: number;
      if (index < 20) {
        f = (b & c) | ((~b) & d);
        k = 0x5a827999;
      } else if (index < 40) {
        f = b ^ c ^ d;
        k = 0x6ed9eba1;
      } else if (index < 60) {
        f = (b & c) | (b & d) | (c & d);
        k = 0x8f1bbcdc;
      } else {
        f = b ^ c ^ d;
        k = 0xca62c1d6;
      }
      const rotate = (a << 5) | (a >>> 27);
      const next = (rotate + f + e + k + words[index]) >>> 0;
      e = d;
      d = c;
      c = (b << 30) | (b >>> 2);
      b = a;
      a = next;
    }
    h0 = (h0 + a) >>> 0;
    h1 = (h1 + b) >>> 0;
    h2 = (h2 + c) >>> 0;
    h3 = (h3 + d) >>> 0;
    h4 = (h4 + e) >>> 0;
  }

  const result = new Uint8Array(20);
  const output = new DataView(result.buffer);
  [h0, h1, h2, h3, h4].forEach((word, index) => output.setUint32(index * 4, word, false));
  return result;
}

export function migratedCueId(source: string): string {
  const input = new Uint8Array(16 + utf8(source).length);
  input.set(uuidBytes(CUE_ID_NAMESPACE));
  input.set(utf8(source), 16);
  const hash = sha1(input);
  hash[6] = (hash[6] & 0x0f) | 0x50;
  hash[8] = (hash[8] & 0x3f) | 0x80;
  return `cue/${Array.from(hash.slice(0, 16), (byte) => byte.toString(16).padStart(2, "0")).join("")}`;
}

export function migrateProject(value: unknown): unknown {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("project must be a JSON object");
  }
  const source = value as Record<string, unknown>;
  const version = source.schema_version;
  if (version === PROJECT_SCHEMA_VERSION) return clone(source);
  if (version !== LEGACY_PROJECT_SCHEMA_VERSION) {
    throw new Error(`unsupported project schema ${String(version)}; expected ${PROJECT_SCHEMA_VERSION} or ${LEGACY_PROJECT_SCHEMA_VERSION}`);
  }

  const migrated = clone(source) as Record<string, unknown>;
  migrated.schema_version = PROJECT_SCHEMA_VERSION;
  if (Array.isArray(migrated.chapters)) {
    migrated.chapters.forEach((chapter) => {
      if (!chapter || typeof chapter !== "object" || Array.isArray(chapter)) return;
      const chapterRecord = chapter as Record<string, unknown>;
      if (!Array.isArray(chapterRecord.scenes)) return;
      chapterRecord.scenes.forEach((scene) => {
        if (!scene || typeof scene !== "object" || Array.isArray(scene)) return;
        const sceneRecord = scene as Record<string, unknown>;
        const legacyEvents = sceneRecord.events;
        if (!Array.isArray(legacyEvents)) {
          if (legacyEvents !== undefined) sceneRecord.cues = legacyEvents;
          return;
        }
        sceneRecord.cues = legacyEvents.map((event, index) => {
          const eventRecord = event && typeof event === "object" && !Array.isArray(event)
            ? event as Record<string, unknown>
            : event;
          const eventId = eventRecord && typeof eventRecord.event_id === "string" && eventRecord.event_id.length > 0
            ? eventRecord.event_id
            : `event-${index}`;
          return {
            cue_id: migratedCueId(eventId),
            ...(eventRecord && typeof eventRecord.kind === "string" ? { title: eventRecord.kind } : {}),
            events: [event],
          };
        });
        delete sceneRecord.events;
      });
    });
  }
  return migrated;
}

type EntityRecord = { entity: Record<string, unknown>; path: string; kind: string };

function records(project: Record<string, unknown>): EntityRecord[] {
  const result: EntityRecord[] = [];
  const add = (value: unknown, path: string, kind: string) => {
    if (value && typeof value === "object" && !Array.isArray(value)) {
      result.push({ entity: value as Record<string, unknown>, path, kind });
    }
  };
  if (Array.isArray(project.characters)) project.characters.forEach((item, index) => add(item, `characters[${index}]`, "character"));
  if (Array.isArray(project.resources)) project.resources.forEach((item, index) => add(item, `resources[${index}]`, "resource"));
  if (!Array.isArray(project.chapters)) return result;
  project.chapters.forEach((chapter, chapterIndex) => {
    add(chapter, `chapters[${chapterIndex}]`, "chapter");
    if (!chapter || typeof chapter !== "object" || Array.isArray(chapter)) return;
    const scenes = (chapter as Record<string, unknown>).scenes;
    if (!Array.isArray(scenes)) return;
    scenes.forEach((scene, sceneIndex) => {
      const scenePath = `chapters[${chapterIndex}].scenes[${sceneIndex}]`;
      add(scene, scenePath, "scene");
      if (!scene || typeof scene !== "object" || Array.isArray(scene)) return;
      const cues = (scene as Record<string, unknown>).cues;
      if (!Array.isArray(cues)) return;
      cues.forEach((cue, cueIndex) => {
        const cuePath = `${scenePath}.cues[${cueIndex}]`;
        add(cue, cuePath, "cue");
        if (!cue || typeof cue !== "object" || Array.isArray(cue)) return;
        const events = (cue as Record<string, unknown>).events;
        if (!Array.isArray(events)) return;
        events.forEach((event, eventIndex) => add(event, `${cuePath}.events[${eventIndex}]`, "event"));
      });
    });
  });
  return result;
}

function entityId(record: EntityRecord): unknown {
  return record.entity[`${record.kind}_id`];
}

export function diagnoseProject(value: unknown): ProjectDiagnostic[] {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return [diagnostic("project.invalid_shape", "$", "project must be a JSON object")];
  }
  let migrated: unknown;
  try {
    migrated = migrateProject(value);
  } catch {
    return [diagnostic("project.unknown_version", "schema_version", `expected ${PROJECT_SCHEMA_VERSION} or ${LEGACY_PROJECT_SCHEMA_VERSION}`)];
  }
  const project = migrated as Record<string, unknown>;
  const diagnostics: ProjectDiagnostic[] = [];
  if (typeof project.project_id !== "string" || !project.project_id.trim()) {
    diagnostics.push(diagnostic("project.missing_id", "project_id", "project_id is required"));
  }
  for (const key of ["characters", "resources", "chapters"] as const) {
    if (!Array.isArray(project[key])) diagnostics.push(diagnostic("project.invalid_shape", key, `${key} must be an array`));
  }

  const addInvalidItems = (value: unknown, path: string, kind: string) => {
    if (!Array.isArray(value)) return;
    value.forEach((item, index) => {
      if (!item || typeof item !== "object" || Array.isArray(item)) {
        diagnostics.push(diagnostic("project.invalid_entity", `${path}[${index}]`, `${kind} must be a JSON object`));
      }
    });
  };
  addInvalidItems(project.characters, "characters", "character");
  addInvalidItems(project.resources, "resources", "resource");
  addInvalidItems(project.chapters, "chapters", "chapter");
  if (Array.isArray(project.chapters)) project.chapters.forEach((chapter, chapterIndex) => {
    if (!chapter || typeof chapter !== "object" || Array.isArray(chapter)) return;
    const chapterRecord = chapter as Record<string, unknown>;
    addInvalidItems(chapterRecord.scenes, `chapters[${chapterIndex}].scenes`, "scene");
    if (!Array.isArray(chapterRecord.scenes)) return;
    chapterRecord.scenes.forEach((scene, sceneIndex) => {
      if (!scene || typeof scene !== "object" || Array.isArray(scene)) return;
      const sceneRecord = scene as Record<string, unknown>;
      addInvalidItems(sceneRecord.cues, `chapters[${chapterIndex}].scenes[${sceneIndex}].cues`, "cue");
      if (!Array.isArray(sceneRecord.cues)) return;
      sceneRecord.cues.forEach((cue, cueIndex) => {
        if (!cue || typeof cue !== "object" || Array.isArray(cue)) return;
        addInvalidItems((cue as Record<string, unknown>).events, `chapters[${chapterIndex}].scenes[${sceneIndex}].cues[${cueIndex}].events`, "event");
      });
    });
  });

  const entities = records(project);
  const byId = new Map<string, string>();
  for (const record of entities) {
    const id = entityId(record);
    if (typeof id !== "string" || !id.trim()) {
      diagnostics.push(diagnostic("project.missing_id", record.path, `${record.kind} must have a non-empty stable ID`));
    } else if (byId.has(id)) {
      diagnostics.push(diagnostic("project.duplicate_id", record.path, `stable ID ${id} is already used by ${byId.get(id)}`));
    } else {
      byId.set(id, record.path);
    }
  }
  const resourceIds = new Set(entities.filter((record) => record.kind === "resource").map((record) => entityId(record)).filter((id): id is string => typeof id === "string"));
  const characterIds = new Set(entities.filter((record) => record.kind === "character").map((record) => entityId(record)).filter((id): id is string => typeof id === "string"));

  for (const record of entities) {
    const entity = record.entity;
    const resourceId = entity.resource_id;
    if (resourceId !== undefined && resourceId !== null && !resourceIds.has(resourceId as string)) {
      diagnostics.push(diagnostic("project.unresolved_resource", `${record.path}.resource_id`, `resource ${String(resourceId)} is not declared`));
    }
    const characterId = entity.character_id;
    if (characterId !== undefined && characterId !== null && !characterIds.has(characterId as string)) {
      diagnostics.push(diagnostic("project.unresolved_character", `${record.path}.character_id`, `character ${String(characterId)} is not declared`));
    }
    if (record.kind === "character" && entity.stage_media !== undefined) {
      const media = entity.stage_media;
      if (!media || typeof media !== "object" || Array.isArray(media)) {
        diagnostics.push(diagnostic("project.invalid_stage_media", `${record.path}.stage_media`, "stage_media must be an object"));
      } else {
        const stageMedia = media as Record<string, unknown>;
        if (!STAGE_MEDIA_KINDS.has(stageMedia.kind as string)) {
          diagnostics.push(diagnostic("project.unknown_stage_media_kind", `${record.path}.stage_media.kind`, "stage_media kind must be portrait, spine, or spine-frame"));
        }
        const hasPreview = typeof stageMedia.preview_uri === "string" && stageMedia.preview_uri.trim().length > 0;
        const hasSpineBundle = stageMedia.kind === "spine"
          && typeof stageMedia.bundle_key === "string"
          && stageMedia.bundle_key.trim().length > 0;
        if (!hasPreview && !hasSpineBundle) {
          diagnostics.push(diagnostic("project.missing_stage_media_preview", `${record.path}.stage_media.preview_uri`, "stage_media preview_uri is required"));
        }
      }
    }
    if (record.kind === "event") {
      const eventKind = entity.kind;
      if (!isDescriptorRenderable(eventKind)) {
        const namespaced = typeof eventKind === "string" && eventKind.includes(":");
        diagnostics.push(diagnostic("project.unknown_event_kind", `${record.path}.kind`, `unsupported event kind ${String(eventKind)}`, namespaced ? "warning" : "error"));
      }
      if ((eventKind === "enter" || eventKind === "exit") && (!Number.isInteger(entity.slot) || Number(entity.slot) < 1 || Number(entity.slot) > 5)) {
        diagnostics.push(diagnostic("project.invalid_slot", `${record.path}.slot`, "slot must be an integer from 1 to 5"));
      }
      if (entity.duration_ms !== undefined) {
        const duration = entity.duration_ms;
        if (typeof duration !== "number" || !Number.isFinite(duration) || duration <= 0) {
          diagnostics.push(diagnostic("project.invalid_duration", `${record.path}.duration_ms`, "duration_ms must be a finite positive number"));
        }
      }
      if (entity.wait_for_completion !== undefined && typeof entity.wait_for_completion !== "boolean") {
        diagnostics.push(diagnostic(
          "project.invalid_wait_for_completion",
          `${record.path}.wait_for_completion`,
          "wait_for_completion must be a boolean",
        ));
      } else if (entity.wait_for_completion === false && !supportsNonBlocking(eventKind)) {
        diagnostics.push(diagnostic(
          "project.unsupported_non_blocking_event",
          `${record.path}.wait_for_completion`,
          `event kind ${String(eventKind)} does not support non-blocking timing`,
        ));
      }
    }
  }
  for (const record of entities.filter((item) => item.kind === "scene")) {
    if (!Array.isArray(record.entity.cues)) diagnostics.push(diagnostic("project.invalid_cues", `${record.path}.cues`, "scene cues must be an array"));
  }
  return diagnostics;
}

export function inspectProject(value: unknown): ProjectCodecResult {
  const diagnostics = diagnoseProject(value);
  const errors = diagnostics.filter((item) => item.severity === "error");
  if (errors.length) return { project: null, diagnostics, migrated: false };
  const migrated = (() => {
    try { return migrateProject(value) as HaloCueProject; } catch { return null; }
  })();
  return {
    project: migrated ? clone(migrated) : null,
    diagnostics,
    migrated: Boolean(migrated && (value as { schema_version?: unknown })?.schema_version === LEGACY_PROJECT_SCHEMA_VERSION),
  };
}

export function parseProject(value: unknown): HaloCueProject {
  const result = inspectProject(value);
  const errors = result.diagnostics.filter((item) => item.severity === "error");
  if (!result.project || errors.length) {
    const summary = errors.map((item) => `${item.code} at ${item.path}`).join("; ");
    const versionHint = errors.some((item) => item.code === "project.unknown_version")
      ? "; expected halocue-project/1.1 or halocue-project/1.0"
      : "";
    throw new Error(`invalid HaloCueProject: ${summary || "unsupported project schema"}${versionHint}`);
  }
  return clone(result.project);
}

export function serializeProject(project: unknown): string {
  return JSON.stringify(parseProject(project), null, 2);
}
