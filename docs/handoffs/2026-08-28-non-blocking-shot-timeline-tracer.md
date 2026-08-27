# Handoff: non-blocking animation and Shot Timeline tracer

- Issue: [#24](https://github.com/Suciko/HaloCue/issues/24)
- Branch: `feature/1.1-ba-editor-from-1.0`
- Scope: `scene-events/1.2` through the first Professional Shot Timeline workspace
- Status: implementation complete, awaiting maintainer review

## Delivered

The canonical ordered Cue event list now projects into a `shot-timeline/1.0`
view without creating a second project model. The projection has stable event
IDs, deterministic frame ranges, five semantic tracks (`Camera`, `Stage`,
`Character`, `Dialogue / Overlay`, and `Effect / Timing`), normalized wait
semantics, and an explicit list of authored events that the render timeline
cannot map yet.

Professional mode now has an editor-state-only tab switch between `脚本` and
`镜头时间轴`. The Shot Timeline view keeps the live preview and contextual
inspector in the same task workspace. Selecting a clip selects its source event
and seeks the preview to its start frame; clicking a ruler or lane seeks an
exact frame; keyboard arrows, Home, and End work on the ruler. Non-blocking
character motion is rendered on its own track at the same horizontal frame as a
following dialogue event and is marked with the parallel color treatment.

The narrow layout keeps the application shell within the viewport, stacks the
preview, timeline, and inspector vertically, and leaves only the timeline's
internal canvas horizontally scrollable. Track labels retain their full value
through a title attribute when the narrow label column ellipsizes.

## Evidence and clean-room boundary

Public first-party references reviewed:

- [Studio editor overview](https://docs.avg-engine.com/images/manual/overview/editor/editor-overview.png)
- [Studio stage-animation timeline](https://docs.avg-engine.com/images/manual/writing/blocks/stage-animation/timeline-overview.webp)
- [Studio narrative map](https://docs.avg-engine.com/images/manual/overview/narrative-map/narrative-map-overview.webp)
- [Studio build workspace](https://docs.avg-engine.com/images/manual/overview/build/build-overview.png)
- [Studio blocks overview](https://docs.avg-engine.com/manual/writing/blocks-overview)
- [Studio camera block](https://docs.avg-engine.com/manual/writing/blocks/camera/)
- [Studio update-character block](https://docs.avg-engine.com/manual/writing/blocks/update-character)

The maintainer-local LetsGal Studio 1.11 snapshot was consulted read-only for
behavior evidence only. The four files matched the hashes already recorded in
`docs/research-inputs.sha256`:

- `sdk/types/schema.ts`: stable story IDs and open `StoryBlock` fields;
- `sdk/types/block-schema.ts`: semantic inspector fields including boolean,
  position, asset, character, scene, fragment, and variable selectors;
- `sdk/save-schema.ts`: extension-owned persistence declared separately from
  runtime block data;
- `default-shell/src/manifest.ts`: namespace-qualified extension identity,
  SDK version negotiation, and builtin capability.

No recovered implementation body, source map, bundle, font, image, audio,
model, or other application asset entered the repository or runtime closure.
The conclusions above are independently implemented through HaloCue contracts,
tests, and projections.

## Verification

- `npm test` in `apps/desktop-client/scene-editor`: **25 files, 137 tests passed**.
- `npm run build`: passed. Vite still reports the known runtime font URL as an
  unresolved external asset, which is expected for the local preview service.
- `git diff --check`: passed.
- Playwright desktop (1280x900): verified tab switching, clip selection,
  parallel motion plus dialogue overlap, aligned playhead, and internal ruler
  scrolling.
- Playwright narrow (390x844): verified no body overflow, shell width within
  viewport, internal timeline scroll (`649px` content in a `375px` viewport),
  reachable inspector, and readable controls.
- The embedded preview returned proxy errors because the optional local
  renderer on `127.0.0.1:8898` was not running; the timeline DOM and controls
  remained healthy.

## Next tracer bullet

Implement the Studio-style selected-object linkage as a focused follow-up:
preserve a single selection source across Script and Shot Timeline views, expose
the selected event's frame range in the preview toolbar, and make preview
refresh/seek state explicit without entering project history. Keep this as
editor state and add model/store/browser tests before considering richer clip
editing or audio tracks.
