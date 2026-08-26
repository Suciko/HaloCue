# 2026-08-27 Scene Event Registry

## Scope

This maintenance slice deepens the shared scene-event Module behind a stable
Seam. Simple mode remains a low-operation-cost task flow, while professional
mode and the render adapters continue to operate on the same Cue/event data.

## Changes

- Added the versioned `scene-events/1.0` contract and canonical manifest.
  Definitions cover descriptor renderability, timeline support, visual-only
  behavior, default duration policy, quick-action identity, and editor labels.
- Added the TypeScript `sceneEventRegistry` Adapter. Descriptor projection,
  timeline evaluation, advanced-event counting, and editor labels now consume
  its Interface instead of local kind/default tables.
- Added the Python `JsonSceneEventRegistry` Adapter. Project validation,
  descriptor projection, scene evaluation, and offline timeline generation now
  share the manifest and the same explicit-duration/typewriter policy.
- Added the browser `scene-events-runtime.js` Adapter and load it before
  `aa-runtime.js`. Preview visual-only classification and deterministic frame
  duration now use the same registry seam.
- Quick-effect commands retain their effect-specific payload defaults but no
  longer persist duplicated default durations; the timeline resolves them from
  the contract.
- Unknown namespaced professional events remain in the canonical project and
  produce warnings; unknown non-namespaced render events remain rejected.

## Professional authoring follow-up

- Added `sceneEventFactory.ts` as the professional command-menu Interface for
  creating the smallest valid payload for each registry-supported event.
- Added canonical-store commands for adding and deleting events. Deletion keeps
  the nearest surviving event selected and both commands remain undoable through
  the existing repository history.
- Added an actual professional event menu, per-event delete controls, character
  selection for enter events, resolved duration fields, and a selected-Cue event
  track that uses the shared render timeline.
- The simple mode remains the low-operation-cost task flow; these controls are
  exposed only in professional mode and edit the same Cue/event objects.

## Verification

- `26 passed`: scene-editor Vitest suite.
- `28 passed`: focused Python registry/timeline/evaluation/contract tests.
- `11 passed`: browser scene preview UI regression.
- `2178 passed, 14 skipped`: full Python suite.
- `npm run build`: TypeScript check and Vite production build passed. Vite
  retained the existing runtime font warning for the unresolved preview font.
- Playwright browser check: professional event menu opened, a screen-shake event
  was added, the menu closed automatically, the event appeared in the list and
  timeline, and the inspector resolved its 360 ms duration.
- `ruff check` and `git diff --check`: passed for the touched Python/test files.
- Registry tests compare the browser Adapter manifest field-for-field with the
  canonical JSON and assert the render-timeline schema enum stays in parity.

## Known boundary

The browser Adapter is a checked-in data-only projection because the static
preview has no bundler. Its parity test is the guard against drift; a future
preview build step can generate the file directly from the manifest without
changing the Adapter Interface.

## Publication

- Branch: `feature/1.1-ba-editor-from-1.0`
- PR: https://github.com/Suciko/HaloCue/pull/27
- Commits: `918d198 refactor(1.1): centralize scene event registry`; follow-up
  professional authoring commit is recorded after publication.
