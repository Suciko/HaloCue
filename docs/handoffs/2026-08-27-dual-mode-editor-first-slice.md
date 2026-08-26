# 2026-08-27 HaloCue 1.1 dual-mode editor first slice

## Scope

This phase slice implements the first demonstrable part of the accepted
HaloCue 1.1 direction on branch `feature/1.1-ba-editor-from-1.0`. It advances
the simple BA authoring workflow in #11, validated rendering work in #14, and
the reviewed editor integration in #24. It does not complete or close any of
those issues.

The product decision is that quick editing is a low-operation-cost workspace
over one canonical project, not an AA UI clone or merely a professional UI
with fields hidden. It keeps Studio-style project and editing semantics while
using contextual disclosure, direct manipulation, and useful defaults to
reduce operations. AA remains secondary evidence for BA-specific concepts such
as five stage slots and Cue-sized script beats. Its weak navigation and dense
single-screen layout are not product requirements. Studio 1.11 remains
architecture and behavior evidence under ADR-0005; no recovered source,
production bundle, UI resource, or proprietary asset was copied.

## Contracts and model

- Added `halocue-project/1.1` with Cue-owned ordered events and deterministic
  migration from `halocue-project/1.0`.
- Added `character-capabilities/1.0` for stable expression, motion, emoticon,
  and transition states. Local adapters resolve logical animation names.
- Namespaced advanced events survive deserialize/save/mode changes and produce
  a warning; the current AA descriptor projection omits unsupported events.
- Added `render-sequence/1.0`, binding resumable PNG frames to descriptor and
  timeline hashes.

## Editor

- Added `apps/desktop-client/scene-editor`, built with React, TypeScript,
  Zustand, Vite, and Lucide icons.
- Quick mode provides project and scene navigation, deterministic realtime preview,
  five visible draggable slots, Cue insertion/copy/delete/reorder, and
  contextual character/dialogue/environment tabs.
- Quick mode keeps Cue navigation and ordering in one contextual strip below
  the preview; the left rail does not duplicate the Cue list. Professional mode
  retains the full project/Cue tree for event-oriented work.
- Professional mode expands the same Cue into ordered events, exact IDs,
  logical resource keys, durations, advanced fields, and a timeline.
- The project store supports local recovery drafts, undo/redo, import/export,
  stable IDs, and non-destructive mode switching.
- The editor embeds the existing same-origin scene preview. A 140 ms refresh
  coalesces text edits; it does not maintain a second renderer.
- Stable expression state IDs resolve through a local capability adapter and
  update realtime Spine. Missing avatar thumbnails fall back to initials.

## Video

- `SceneRenderSession` reuses one Chromium context/page and loaded resource
  graph for a complete sequence.
- Frame capture remains in `scene_frame_renderer`; resumable sequence and
  FFmpeg concerns live in `scene_video_renderer` so each module has one owner.
- `render_scene_sequence` writes atomic `frame-000000.png` files and a
  per-frame resumable manifest. Matching frames are SHA-256 verified; different
  inputs cannot reuse the directory.
- `encode_silent_mp4` detects or accepts FFmpeg and writes atomic H.264,
  CRF 18, yuv420p, faststart, no-audio MP4 output.
- `tools/render_scene_video.py` is the current developer CLI.

## Verification

- `2161 passed, 14 skipped`: complete Python suite after fixing pytest module
  collection isolation, Windows gateway CRLF normalization, and the saved AA
  executable config path used by the story picker.
- `41 passed`: combined browser modules for scene preview, frame rendering,
  asset workbench, and responsive story picker in one pytest process.
- `4 passed`: editor store tests for mode preservation, advanced fields, five
  slots, and capability resolution.
- `npm run build`: TypeScript no-emit check and Vite production build passed.
- Python compile checks passed for the touched runtime, model, sequence
  renderer, CLI, services, and tests. The repository-wide Ruff command still
  reports 12 pre-existing style findings in `webui.py` (E401/F401/E701/E702);
  no new lint category was introduced by this slice.
- Noto Sans SC static font metadata declares SIL OFL 1.1, matching the license
  text already stored beside the preview fonts.
- Browser QA passed at 1440x900 and 800x900: no horizontal page overflow,
  quick mode has no duplicated Cue tree, professional mode restores the full
  Cue tree, preview/dialogue edits synchronize, advanced `intensity: 0.35`
  survives mode switching, and expression `expression/smile` resolves to
  Spine `03`. Narrow mode scrolls the inspector below the preview without
  clipping.
- A four-frame reused-page sequence resumed with 4/4 frames reused and encoded
  successfully through the detected FFmpeg.

The browser modules now run together in one pytest invocation; browser fixtures
are module-scoped to keep independent Playwright sync runtimes isolated.

## Local run

- Editor: `http://127.0.0.1:5173/scene-editor/`
- Resource/preview service: `http://127.0.0.1:8898/scene-preview/index.html`
- Vite proxies `/scene-preview` and `/api/resources` to port 8898.

The running server uses maintainer-local authorized resources. Those paths and
bytes are not contracts and must not be committed.

## Publication

- Implementation commit: `eb1023c`
- Target-branch synchronization merge: `41b4cd1`
- Follow-up maintenance is uncommitted on this branch and will be published as
  the next focused commit after final checks.
- Pull request: https://github.com/Suciko/HaloCue/pull/27
- Issues: partial progress on #11, #14, and #24; none are closed by this slice.

## Next bounded slice

1. Move the standalone file import/export and recovery draft behind the Tauri
   project repository with atomic writes and a visible recovery decision.
2. Replace the demo capability map with locally generated
   `character-capabilities/1.0` records and add non-committing hover/preview
   trials for expression, motion, and emoticon resources.
3. Implement working quick-effect events (shake, camera, screen text, hit,
   menu visibility) through versioned descriptor/timeline support.
4. Add cancellable durable export jobs, progress UI, audio timeline/muxing, and
   a user-data export destination.
5. Add chapter/scene creation and choice branches after the linear Cue workflow
   is stable.
