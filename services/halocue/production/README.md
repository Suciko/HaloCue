# HaloCue 1.0 Production Backend

This directory is the isolated HaloCue 1.0 backend for converting an existing
script into a reviewable AzureArchive production draft, then compiling and
installing it after explicit gates pass.

It does not contain the writing backend. The integration boundary is a frozen
`ScriptRelease` submitted to the production API.

## Current vertical slice

- Create and persist a `ProductionRun` from inline script text.
- Scan script structure and speakers with the 0.9.3 document parser.
- Create a real 0.9.3-compatible `PerformanceDraft` in the 1.0 data directory.
- Query production runs, work items, gates, cards, and diagnostics.
- Inspect an AzureArchive executable, install directory, or data workspace with
  the 0.9.3 read-only discovery module, then explicitly adopt the detected workspace.
- Search characters, backgrounds, and sounds from the exported AA resource
  index without returning physical file paths.
- Update one speaker's cast binding with optimistic version checks.
- Edit, insert, move, and delete review cards while preserving stable card IDs.
- Resolve background requests in place and repair or explicitly remove invalid
  sound directives.
- Approve review cards and validate the compile gate.
- Create real immutable build snapshots and run the existing compiler when
  the resource index is configured.
- Install a completed build only when an AA workspace is configured.
- Run the browser workbench from the same service: source import, per-speaker
  mapping, card review/editing, background and sound resolution, real job
  polling, compile gating, install target preflight, and model settings are
  all backed by `/api/v1` rather than simulated client state.
- Keep AI direction model settings owned by 1.0. Public configuration and the
  secret are separate; a Windows-entered key is protected with current-user
  DPAPI, environment-variable secrets are supported, and no API response
  returns a secret.

The 0.9 compatibility modules are loaded from the repository root through the
explicit `HALOCUE_LEGACY_ROOT` boundary (or the repository default). Runtime
data defaults to the repository `.halocue/production` user-data directory.
No AA resource bytes or runtime data are committed here.

The optional `render` dependency exposes the 1.1 deterministic frame and video
adapters in `halocue_production.scene_frame_renderer` and
`halocue_production.scene_video_renderer`. They accept an already validated
`scene-descriptor/1.0`, `render-timeline/1.0`, and `scene-performance/1.0`, connect only to a localhost
preview, and capture atomic 16:9 PNGs. A complete sequence reuses one Chromium
page, records a resumable `render-sequence/1.1` manifest, and can be encoded as
a silent H.264/yuv420p MP4 through FFmpeg. Repository entry points are
`tools/render_scene_frame.py` and `tools/render_scene_video.py`; durable
background export jobs and audio muxing remain later service slices.

## Run

```powershell
cd services/halocue/production
$env:PYTHONPATH = (Resolve-Path .\src).Path
python -m halocue_production.server --port 8892
```

Windows users can also run `启动1.0转换后端.cmd` directly.

Optional environment variables:

```text
HALOCUE_DATA_DIR       Persistent 1.0 state. Defaults to ./data
HALOCUE_LEGACY_ROOT    Read-only 0.9.3 Python modules
HALOCUE_RESOURCE_INDEX Resource index used by compilation
HALOCUE_AA_DATA        AA data workspace used by installation
```

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8892/api/v1/health
```

Open the production workbench at:

```text
http://127.0.0.1:8892/
```

The repository's optional `http.server` preview on port 8891 can render the
same UI files for layout work. It is intentionally allowed to call only the
local 8892 API origin; regular use should open the same-origin 8892 URL above.

## Browser workflow

1. Paste an existing script and create a frozen `ScriptRelease`.
2. Resolve each detected speaker as an AA portrait, a voice-only role, a
   narrator, or deliberately unmapped. Portrait selection is per speaker;
   its Spine, portrait, and faces are not global settings.
3. For format-only tasks, enter review directly. For AI-direction tasks, the
   real background job runs only after a 1.0 model is configured and mapping
   diagnostics have passed.
4. Review cards one at a time, select frozen-index backgrounds or sounds in
   place, and approve them. Every mutation carries `expected_draft_version`.
5. Compile only after the API compile gate passes. A successful compile exposes
   an installation target preflight; installation remains an explicit write to
   the configured AA workspace.

Create a production run:

```powershell
$body = @{
  project = "第一章"
  generation_mode = "format_only"
  source = @{ kind = "inline"; text = "## 场景 01`n爱丽丝: 你好`n" }
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Method Post -ContentType application/json `
  -Body $body http://127.0.0.1:8892/api/v1/production-runs
```

## API contract

All endpoints are under `/api/v1`. Errors use stable codes:

```json
{"ok": false, "error": {"code": "review_pending", "message": "...", "details": {}}}
```

The service binds to `127.0.0.1` by default and sends restrictive local-app
security headers. Source text is accepted only in request bodies; arbitrary
client filesystem paths are not accepted by this first slice.

### Settings and capabilities

```text
GET  /api/v1/health
GET  /api/v1/capabilities
GET  /api/v1/settings/aa-workspace
POST /api/v1/settings/aa-workspace
```

The settings request is `{"path":"E:\\AzureArchive\\...\\data"}`. A valid
workspace must contain `projects`, `saves`, `overrides`, and `settings`.
The selected path is persisted only in `08-HaloCue-1.0/data/settings.json`.

### Production runs

```text
GET  /api/v1/production-runs
POST /api/v1/production-runs
GET  /api/v1/production-runs/{run_id}
POST /api/v1/production-runs/{run_id}/cast-bindings
POST /api/v1/production-runs/{run_id}/review/approve
POST /api/v1/production-runs/{run_id}/validate
POST /api/v1/production-runs/{run_id}/compile
POST /api/v1/production-runs/{run_id}/install
GET  /api/v1/jobs/{job_id}
```

### Review cards

```text
PATCH  /api/v1/production-runs/{run_id}/cards/{card_id}
POST   /api/v1/production-runs/{run_id}/cards
POST   /api/v1/production-runs/{run_id}/cards/move
DELETE /api/v1/production-runs/{run_id}/cards/{card_id}
POST   /api/v1/production-runs/{run_id}/cards/{card_id}/background-resolution
POST   /api/v1/production-runs/{run_id}/cards/{card_id}/sound-resolution
```

Every mutating draft request requires `expected_draft_version`. A stale
request returns HTTP 409 with `revision_conflict`. Background request cards
must be resolved through a dedicated workflow and cannot be deleted as a way
to bypass the compile gate.

Background resolution accepts either
`{"action":"select","background_key":"BG_..."}` or `{"action":"black"}`.
Sound resolution accepts either
`{"action":"select","sound_key":"SE_..."}` or `{"action":"remove"}`.
Every payload also requires `expected_draft_version`. Selected resources must
exist in the frozen resource index.

### Resource catalog

```text
GET /api/v1/resources/characters?q=alice&offset=0&limit=80
GET /api/v1/resources/characters/{identifier}
GET /api/v1/resources/backgrounds?q=classroom&offset=0&limit=80
GET /api/v1/resources/sounds?q=door&offset=0&limit=80
```

Results are paged and contain stable AA identifiers and display metadata. They
do not return local source or installation paths. Draft diagnostics and the
compile gate use the same frozen resource index, so an unregistered `@bg` or
`@se` directive cannot pass compilation merely because the UI missed it.

### Install preparation

```text
GET  /api/v1/production-runs/{run_id}/install-options
POST /api/v1/production-runs/{run_id}/install-check
```

These routes are available only for the run's latest completed build. They
return suggested categories and target conflict state without exposing AA
workspace paths. `install-check` accepts `category`, `story_name`, and an
optional `build_id`; it does not write to AA.

## Generation modes

`format_only` preserves the submitted script and performs deterministic
conversion. `ai_direction` uses the model Provider and credentials owned by
HaloCue 1.0; when the Provider is not configured the UI keeps the mode
selectable and takes the user to the model settings instead of silently
disabling the choice.

## Ownership boundary

The future writing service owns ideas, outlines, prose, and revisions until it
publishes an immutable `ScriptRelease`. This service owns everything after
that handoff: structure inspection, cast mapping, performance draft review,
deterministic compilation, and explicit installation into AA.

The production API verifies the upstream release content hash, preserves its
identity separately from the production-local frozen release, and returns the
existing run when the same upstream release is submitted again. The complete
compatibility contract is documented in [WRITING_HANDOFF_CONTRACT.md](WRITING_HANDOFF_CONTRACT.md).
## Deterministic scene video export

`tools/render_scene_video.py` reuses one Chromium page to render a numbered PNG
sequence, records a resumable `render-sequence/1.1` manifest, and encodes a
silent H.264/yuv420p MP4 through FFmpeg. Preview, individual frames, sequences,
and video all consume the same `SceneDescriptor`, `RenderTimeline`, and
`ScenePerformance` plan.

```powershell
python tools/render_scene_video.py descriptor.json output.mp4 --renderer realtime
```
