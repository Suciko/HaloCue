# Handoff: AA preview event runtime

## Scope

The 1.1 scene preview now treats the descriptor event list as the source of
truth for interactive playback:

- `enter` events inherit the catalog character's display and local preview
  metadata when a different character enters an existing slot;
- `background` events can replace the active background without reloading the
  page;
- The formal preview has no AUTO button or timer-driven playback. Users advance
  events manually so the canvas remains unobstructed and the product does not
  inherit an unnecessary AA interaction affordance.

Deterministic video rendering must consume the normalized event timeline
directly and must not depend on browser timers or user input.

## Verification

```text
python -m pytest -q tests/test_aa_runtime_contract.py tests/test_ba_scene_preview.py tests/test_ba_scene_preview_ui.py
node --check apps/desktop-client/scene-preview/aa-runtime.js
node --check apps/desktop-client/scene-preview/preview.js
git diff --check
```

Result: `10 passed` and both JavaScript syntax checks passed.

The browser regression covers a mid-scene slot replacement and a background
transition. The checked-in fixture uses synthetic resources only; local AA
resources remain resolved through the allowlisted preview endpoint.

## Next slice

Define a deterministic render timeline shared by browser preview and offline
video export. The render path should use explicit durations and frame/sample
times, while the AUTO control remains outside that contract.
