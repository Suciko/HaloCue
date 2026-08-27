# HaloCueProject model

`project_model.py` contains the cue-based `halocue-project/1.1` canonical model
slice plus the deterministic `1.0 -> 1.1` migration. It is deliberately plain
JSON data and remains independent of React,
Tauri, PixiJS, Unity, Studio, AA private formats, and local resource bytes.

The slice supports:

- chapters, scenes, ordered Cues/events, characters, and logical resource IDs;
- preservation of namespaced advanced events while simple presentation
  adapters project only the event kinds they understand;
- stable-ID and reference validation with structured diagnostic codes;
- validated JSON deserialization for persistence and round-trip tests; and
- a deterministic `scene-descriptor/1.0` AA presentation adapter with five
  character slots. Character stage media is explicit: `portrait`,
  `spine-frame`, and authorized realtime `spine` media may be rendered in the
  formal canvas; AA avatar keys
  remain catalog metadata and are never used as full-body fallbacks. Background
  resources may carry normalized `focus_x`/`focus_y` anchors for cover-cropped
  16:9 presentation.

`render_timeline.py` projects a scene descriptor into the independent
`render-timeline/1.2` contract. It uses explicit end-exclusive frame ranges and
stable default durations so browser preview and offline video exporters can
share timing without depending on AUTO playback or wall-clock callbacks.
Registry-supported character motion may set `wait_for_completion` to false;
the following event then starts at the same sequential cursor and `total_frames`
is the maximum end frame.

`scene_performance.py` compiles supported authored effects into the independent
`scene-performance/1.4` animation plan and samples exact frames under play,
sample, skip, and reduced-motion execution modes. It currently supports a
deterministic stage shake and composable character opacity, vertical-offset,
scale, and keyframed rotation contributions with stable source mapping.
Same-character state updates no longer recompile as entrances; `motion/nod`
uses seek-safe offset/rotation keyframes, while `motion/appear` uses factor
opacity/scale and additive offset keyframes shared by preview and export.

`scene_evaluation.py` binds the descriptor, timeline, and performance plan into
the `scene-evaluation/1.5` intermediate result consumed by offline adapters. It
also reports namespaced events that remain in the canonical project but are
not yet rendered by the AA presentation adapter, plus explicit character motion
placed outside the target character's occupied range.

This is not yet the complete project model. Variables, proposals, revisions,
MMT cues, and StudioProject v2 export remain later versioned slices. Cross-
context wire contracts belong in `packages/contracts/` and must land through
the shared contracts stream before consumers depend on them.
