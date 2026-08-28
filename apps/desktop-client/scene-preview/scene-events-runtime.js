(function (global) {
  "use strict";

  // Browser Adapter for packages/contracts/scene-events/1.2.json. Keep this
  // generated-shaped data-only file free of renderer or DOM behavior.
  const manifest = {
    schema_version: "scene-events/1.2",
    events: [
      { kind: "background", descriptor_renderable: true, timeline_supported: true, visual_only: true, supports_non_blocking: false, duration_policy: "fixed", default_duration_ms: 500, simple_action: null, editor_label: "背景" },
      { kind: "dialogue", descriptor_renderable: true, timeline_supported: true, visual_only: false, supports_non_blocking: false, duration_policy: "dialogue-aa-v1", default_duration_ms: null, simple_action: null, editor_label: "对白" },
      { kind: "enter", descriptor_renderable: true, timeline_supported: true, visual_only: false, supports_non_blocking: false, duration_policy: "fixed", default_duration_ms: 500, simple_action: null, editor_label: "角色入场" },
      { kind: "exit", descriptor_renderable: true, timeline_supported: true, visual_only: false, supports_non_blocking: false, duration_policy: "fixed", default_duration_ms: 500, simple_action: null, editor_label: "角色退场" },
      { kind: "character-motion", descriptor_renderable: true, timeline_supported: true, visual_only: true, supports_non_blocking: true, duration_policy: "fixed", default_duration_ms: 500, simple_action: null, editor_label: "角色动作" },
      { kind: "wait", descriptor_renderable: true, timeline_supported: true, visual_only: true, supports_non_blocking: false, duration_policy: "fixed", default_duration_ms: 1000, simple_action: null, editor_label: "等待" },
      { kind: "halocue.ba:background-pan", descriptor_renderable: true, timeline_supported: true, visual_only: true, supports_non_blocking: true, duration_policy: "fixed", default_duration_ms: 900, simple_action: "background-pan", editor_label: "背景移动" },
      { kind: "halocue.ba:screen-shake", descriptor_renderable: true, timeline_supported: true, visual_only: true, supports_non_blocking: true, duration_policy: "fixed", default_duration_ms: 360, simple_action: "screen-shake", editor_label: "画面震动" },
      { kind: "halocue.ba:screen-text", descriptor_renderable: true, timeline_supported: true, visual_only: true, supports_non_blocking: true, duration_policy: "fixed", default_duration_ms: 1800, simple_action: "screen-text", editor_label: "屏幕文字" },
      { kind: "halocue.ba:hit-effect", descriptor_renderable: true, timeline_supported: true, visual_only: true, supports_non_blocking: false, duration_policy: "fixed", default_duration_ms: 420, simple_action: "hit-effect", editor_label: "中弹效果" },
    ],
  };
  const definitions = Object.freeze(manifest.events.map((event) => Object.freeze({ ...event })));
  const byKind = new Map(definitions.map((event) => [event.kind, event]));
  const punctuation = new Set(Array.from("，。！？；：、,.!?;:"));
  const typewriterGraphemeMs = 32;
  const typewriterPunctuationPauseMs = 96;
  const typewriterNewlinePauseMs = 192;
  const dialogueHoldMs = 650;

  function definition(kind) {
    return typeof kind === "string" ? byKind.get(kind) : undefined;
  }

  function dialogueDurationMs(text) {
    let duration = dialogueHoldMs;
    for (const grapheme of Array.from(String(text ?? ""))) {
      duration += typewriterGraphemeMs;
      if (grapheme === "\n") duration += typewriterNewlinePauseMs;
      else if (punctuation.has(grapheme)) duration += typewriterPunctuationPauseMs;
    }
    return duration;
  }

  const registry = {
    schema_version: manifest.schema_version,
    manifest: Object.freeze({
      schema_version: manifest.schema_version,
      events: definitions,
    }),
    definition,
    definitions: () => definitions,
    isTimelineSupported: (kind) => Boolean(definition(kind)?.timeline_supported),
    isDescriptorRenderable: (kind) => Boolean(definition(kind)?.descriptor_renderable),
    isVisualOnly: (kind) => Boolean(definition(kind)?.visual_only),
    supportsNonBlocking: (kind) => Boolean(definition(kind)?.supports_non_blocking),
    durationMs(event) {
      const item = definition(event?.kind);
      if (!item?.timeline_supported) {
        throw new RangeError(`unsupported render event kind ${String(event?.kind)}`);
      }
      const explicit = event?.duration_ms;
      if (explicit !== undefined && explicit !== null) {
        if (!Number.isFinite(explicit) || explicit <= 0) {
          throw new RangeError("event duration_ms must be a finite positive number");
        }
        return Math.max(1, Math.ceil(explicit));
      }
      if (item.duration_policy === "dialogue-aa-v1") return dialogueDurationMs(event?.text);
      return item.default_duration_ms;
    },
  };

  global.HaloCueSceneEventRegistry = Object.freeze(registry);
}(window));
