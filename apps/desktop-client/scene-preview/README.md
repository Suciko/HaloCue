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
- camera-correct AA slot projection (the character camera spans 2960 authored
  units while dialogue typography keeps the 2560x1440 design grid);
- enter/exit events and active-speaker highlighting;
- dialogue progression from the descriptor event list; and
- explicit `stage_media` entries for `portrait`, `spine`, and `spine-frame`;
  `spine` entries load the authorized local `.skel/.atlas/texture` bundle into
  a browser WebGL canvas and keep the deterministic `spine-frame` PNG route as
  a fallback; unsupported or missing stage media leaves the slot empty instead
  of scaling an avatar thumbnail into a character;
- background `focus_x`/`focus_y` anchors applied inside a cover-cropped 16:9
  frame; and
- a clean canvas with scene information only; editor actions and export
  controls stay outside the video frame; and
- selectable HarmonyOS Sans Medium, Noto Sans, and Nowar Rounded CSS font
  stacks.

The export-safe URL renders the editor tray fully transparent. Append
`?editor=1` while authoring to reveal the AUTO/MENU switches; the descriptor
still decides whether either button appears inside the video frame.

The preview controller consumes the deterministic `render-timeline/1.0` and
`scene-performance/1.1` contracts. `window.HaloCueScenePreview.controller`
exposes `seekFrame`,
`seekEvent`, `seekReference`, `play`, `pause`, and `dispose`. These methods keep
the browser preview on the same end-exclusive frame ranges used by the Python
offline timeline adapter. The default page remains a live realtime preview.

Useful deterministic URLs:

- `?descriptor=official-p69&reference=1` seeks and freezes the descriptor's
  recorded reference frame with realtime Spine canvases;
- add `&renderer=static` for the matching raster fallback comparison;
- `?frame=35` seeks an explicit timeline frame; and
- `?play=1` starts deterministic timeline playback.

`?capture=1&frame=N` is the headless export surface. It disables wall-clock CSS
transitions and transient entrance/location timers before the stage is sampled.
An export host may inject `window.HALO_CUE_RENDER_TIMELINE`; the preview accepts
it only when its canonical JSON content exactly matches the timeline derived
from the injected `scene-descriptor/1.0` payload. The matching
`window.HALO_CUE_SCENE_PERFORMANCE` plan is validated the same way. Deterministic
stage shake is applied as sampled geometry rather than a CSS keyframe, so its
intermediate frames survive capture with browser animations disabled.
Character enter/exit is sampled from the same plan as opacity, vertical-offset,
and scale contributions. Skip commits their final state; reduced motion keeps
the opacity fade while committing positional and scale motion immediately.

The repository CLI builds the Python timeline and performance plan, injects all
three contracts into the
localhost preview, waits for fonts/backgrounds/realtime Spine canvases, and
atomically writes one 16:9 PNG:

```powershell
python tools/render_scene_frame.py `
  apps/desktop-client/scene-preview/official-p69.scene-descriptor.json `
  C:\path\outside\the\repository\p69-frame-35.png `
  --reference --renderer realtime
```

The output JSON records the resolved frame, event ID, frame rate, dimensions,
renderer, timeline/performance schemas, and SHA-256. The CLI only connects to a localhost
preview URL; authorized AA bytes continue to flow through the existing local
resource endpoints and are never embedded in the source tree.

Realtime Spine players stop ticking while deterministically paused or while
the document is hidden. Only visible actors stay attached, and canvas backing
resolution remains capped for preview performance.

The checked-in default descriptor uses synthetic logical resource IDs. Real
user-owned or authorized resources are resolved through `aa_preview_resolver.py`
and a local user-data manifest; absolute Windows paths and extracted game
resources are never exposed to browser code.

The host client serves the authorized Spine bundle through
`/api/resources/stage/spine/data`. The response contains only in-memory data
URIs, never source filesystem paths. Spine 3.8 and 4.2 runtimes are loaded
lazily from the host's `/js/` allowlist, and each bundle is cached in the
browser for the duration of the preview session.

For a local smoke check, serve this directory with any static HTTP server and
open `index.html`. The page fetches `example.scene-descriptor.json` and exposes
`window.HaloCueScenePreview.mount(descriptor)` for a host client. A host may
keep the legacy actor `preview_uri`/`preview_source` fields during migration;
the adapter ignores those fields for stage rendering and only reads
`actor.stage_media.preview_uri` when its kind is explicitly supported.
