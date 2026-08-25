# HaloCueProject model

`project_model.py` contains the first `halocue-project/1.0` canonical model
slice. It is deliberately plain JSON data and remains independent of React,
Tauri, PixiJS, Unity, Studio, AA private formats, and local resource bytes.

The slice supports:

- chapters, scenes, ordered events, characters, and logical resource IDs;
- stable-ID and reference validation with structured diagnostic codes;
- validated JSON deserialization for persistence and round-trip tests; and
- a deterministic `scene-descriptor/1.0` AA presentation adapter with five
  character slots. Character stage media is explicit: only `portrait` and
  `spine-frame` previews may be rendered in the formal canvas; AA avatar keys
  remain catalog metadata and are never used as full-body fallbacks. Background
  resources may carry normalized `focus_x`/`focus_y` anchors for cover-cropped
  16:9 presentation.

`render_timeline.py` projects a scene descriptor into the independent
`render-timeline/1.0` contract. It uses explicit end-exclusive frame ranges and
stable default durations so browser preview and offline video exporters can
share timing without depending on AUTO playback or wall-clock callbacks.

This is not yet the complete project model. Variables, proposals, revisions,
MMT cues, and StudioProject v2 export remain later versioned slices. Cross-
context wire contracts belong in `packages/contracts/` and must land through
the shared contracts stream before consumers depend on them.
