# Handoff: preview lifecycle status tracer

- Issue: [#24](https://github.com/Suciko/HaloCue/issues/24)
- Branch: `feature/1.1-ba-editor-from-1.0`
- Scope: explicit preview synchronization, ready, and failure feedback
- Status: implementation complete and pushed

## Delivery

The preview toolbar now exposes a polite live status beside the selected range
and transport controls:

- `同步中` before the current preview controller mounts;
- `已就绪` after a current controller is mounted;
- `预览失败` when mounting or applying the intent throws.

Failure detail remains available in the status title and the existing viewport
error message. Bounded and full playback remain disabled until the controller
is ready. The lifecycle is React/editor state only and does not change project
data, revision, history, autosave, or timeline contracts.

## Studio evidence and boundary

Public first-party sources reviewed:

- [Studio editor overview](https://docs.avg-engine.com/images/manual/overview/editor/editor-overview.png)
- [Studio Stage Animation timeline](https://docs.avg-engine.com/images/manual/writing/blocks/stage-animation/timeline-overview.webp)
- [Studio editor manual](https://docs.avg-engine.com/manual/overview/editor)
- [Studio debugging manual](https://docs.avg-engine.com/manual/overview/debugging)

Studio's public editor keeps a `LIVE` preview state, transport, selected
authoring object, and inspector in the same task surface. HaloCue adopts the
observable state relationship with its own status vocabulary and controller
contract. No decompiled source, source map, application bundle, private asset,
font, model, or local Studio/AA resource entered the repository.

## TDD and verification

- Red: the toolbar had no status node or lifecycle text.
- Green: a single derived status maps existing `ready` and `error` state to
  synchronization, ready, and failure feedback.
- Focused: `npm test -- --run src/previewToolbarUi.test.tsx` -> **4 tests passed**.
- Related: preview toolbar, compilation, and capability trial tests ->
  **12 tests passed**.
- Full editor: `npm test -- --run` -> **30 files, 161 tests passed**.
- Build: `npm run build` -> passed with the known external preview-font URL
  warning.
- Browser desktop (1280x900): status, selected range, and transport fit in the
  preview toolbar; `bodyScrollWidth=1280`, `bodyClientWidth=1280`. Screenshot:
  `output/playwright/preview-status-desktop.png`.
- Browser narrow (390x844): status remains visible and the page does not gain
  horizontal body overflow; `bodyScrollWidth=390`, `bodyClientWidth=390`.
  Screenshot: `output/playwright/preview-status-narrow.png`.
- `git diff --check` passed before commit.

The optional renderer on `127.0.0.1:8898` was stopped during visual checks, so
the browser showed the real `同步中` state. Deterministic component tests drove
the mounted-controller and thrown-error paths.

## Commit and push

- Code commit: `d53cfd1 feat(1.1): surface preview lifecycle status`
- Pushed to `origin/feature/1.1-ba-editor-from-1.0`

## Next bounded slice

Unify the selected Simple Cue's title and derived frame range into one polite,
atomic selection context. Reuse the current Cue/timeline projection and keep
the Inspector tabs, project revision, and history unchanged. Do not expand into
continuous-dialogue modeling or theme migration in that slice.
