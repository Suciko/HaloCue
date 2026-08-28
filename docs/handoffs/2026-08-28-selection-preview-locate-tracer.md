# Handoff: selected event preview locate tracer

- Issue: [#24](https://github.com/Suciko/HaloCue/issues/24)
- Branch: `feature/1.1-ba-editor-from-1.0`
- Scope: Professional selected-event to preview/playhead linkage
- Status: implementation complete, awaiting maintainer review

## Delivery

The realtime preview toolbar now derives the selected event's deterministic
end-exclusive frame range from the shared render timeline. When the selected
event is renderable it shows `F<start>-<end>` and exposes a `定位` command that
moves the editor playhead back to the event start frame.

This closes the smallest missing part of the Studio-style selection loop:

```text
script row or Shot Timeline clip selection
  -> contextual event inspector
  -> selected event frame range in preview
  -> explicit locate to event start
  -> shared playhead and preview intent
```

The locate command is editor state only. It does not change the project,
revision, history, stable event IDs, or authored timing. Existing explicit
scrubbing still takes priority until the author invokes locate.

## Evidence

The public [Studio editor overview](https://docs.avg-engine.com/images/manual/overview/editor/editor-overview.png)
keeps ordered Blocks, realtime preview, and the selected Block inspector in one
authoring path. The public [Stage Animation timeline](https://docs.avg-engine.com/images/manual/writing/blocks/stage-animation/timeline-overview.webp)
keeps the selected timeline object, playback position, preview, and object
properties visibly connected. HaloCue adopts that observable linkage while
retaining its own `preview-intent`, render-timeline, and editor-state contracts.

No Studio implementation or asset entered the repository.

## Verification

- Red: the new UI test failed because the preview exposed neither a selected
  range nor a locate action.
- Green/refactor: `shotTimelineUi.test.tsx` passes **4 tests**.
- Full editor suite: **25 files, 138 tests passed**.
- Editor build: passed.
- Playwright at 1280x900: selected `character-motion` exposed `F47-62`; after
  scrubbing to `F114`, locate returned preview intent and playhead to `F47`.
- Playwright at 390x844: body width remained equal to the viewport and the
  preview toolbar retained the range, refresh, locate, and playback controls.
- `git diff --check`: passed.

The embedded preview still reports the known local proxy errors while the
optional renderer on `127.0.0.1:8898` is stopped. The editor-side selection and
playhead state were verified independently of that service.

## Next tracer bullet

The next bounded Studio-informed slice should make the Professional inspector's
timing section a real read-only timeline projection: show start, end, duration,
wait/parallel policy, and track assignment from the evaluated timeline instead
of the current `自动` placeholder. Keep authored fields and derived timing
visually distinct and do not introduce absolute start-time editing.
