# AA scene preview

This is the first runnable presentation slice for the BA editor stream. It is
an independently written browser adapter for `scene-descriptor/1.0`, not a
copy of AA or Studio code.

The default fixture demonstrates the contract with synthetic assets. For a
machine with an AA installation and a generated local preview index, load
`local-aa.scene-descriptor.json` from the host client. Its background and five
slot metadata point at the allowlisted `/api/resources/preview` endpoint, so
the browser can use locally indexed AA previews without copying game resources
into this repository. Avatar responses are catalog thumbnails only; they are
not stage media.

The preview demonstrates:

- five stable AA foreground character slots with deterministic horizontal positions;
- enter/exit events and active-speaker highlighting;
- dialogue progression from the descriptor event list; and
- explicit `stage_media` entries for `portrait` and `spine-frame` raster
  renders; unsupported or missing stage media leaves the slot empty instead
  of scaling an avatar thumbnail into a character;
- background `focus_x`/`focus_y` anchors applied inside a cover-cropped 16:9
  frame; and
- a clean canvas with scene information only; editor actions and export
  controls stay outside the video frame; and
- selectable HarmonyOS Sans Medium, Noto Sans, and Nowar Rounded CSS font
  stacks.

The checked-in default descriptor uses synthetic logical resource IDs. Real
user-owned or authorized resources are resolved through `aa_preview_resolver.py`
and a local user-data manifest; absolute Windows paths and extracted game
resources are never exposed to browser code.

For a local smoke check, serve this directory with any static HTTP server and
open `index.html`. The page fetches `example.scene-descriptor.json` and exposes
`window.HaloCueScenePreview.mount(descriptor)` for a host client. A host may
keep the legacy actor `preview_uri`/`preview_source` fields during migration;
the adapter ignores those fields for stage rendering and only reads
`actor.stage_media.preview_uri` when its kind is explicitly supported.
