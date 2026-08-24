# Synthetic AA scene preview

This is the first runnable presentation slice for the BA editor stream. It is
an independently written browser adapter for `scene-descriptor/1.0`, not a
copy of AA or Studio code.

The preview demonstrates:

- six stable character slots with deterministic horizontal positions;
- enter/exit events and active-speaker highlighting;
- dialogue progression from the descriptor event list; and
- selectable HarmonyOS Sans Medium, Noto Sans, and Nowar Rounded CSS font
  stacks.

The checked-in descriptor uses only synthetic logical resource IDs. Real
user-owned or authorized resources belong in a future local resource manifest;
they are not loaded from this directory.

For a local smoke check, serve this directory with any static HTTP server and
open `index.html`. The page fetches `example.scene-descriptor.json` and exposes
`window.HaloCueScenePreview.mount(descriptor)` for a host client.
