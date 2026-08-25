# HaloCueProject model

`project_model.py` contains the first `halocue-project/1.0` canonical model
slice. It is deliberately plain JSON data and remains independent of React,
Tauri, PixiJS, Unity, Studio, AA private formats, and local resource bytes.

The slice supports:

- chapters, scenes, ordered events, characters, and logical resource IDs;
- stable-ID and reference validation with structured diagnostic codes;
- validated JSON deserialization for persistence and round-trip tests; and
- a deterministic `scene-descriptor/1.0` AA presentation adapter with five
  character slots.

This is not yet the complete project model. Variables, proposals, revisions,
MMT cues, and StudioProject v2 export remain later versioned slices. Cross-
context wire contracts belong in `packages/contracts/` and must land through
the shared contracts stream before consumers depend on them.
