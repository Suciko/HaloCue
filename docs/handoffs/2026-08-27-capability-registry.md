# 2026-08-27 CharacterCapability registry

## Scope

This slice deepens the character capability module behind a stable registry
seam. It keeps the simple editor low-cost and contextual while allowing the
professional workspace and local resource adapters to grow independently.

## Changes

- Added typed `character-capabilities/1.0` state records for expression,
  motion, emoticon, and transition options.
- Added `CapabilityRegistry` and `MapCapabilityRegistry` with validation,
  stable ID lookup, character/capability matching, cloning, and default states.
- Descriptor and scene evaluation now accept an injected registry, so a future
  local manifest adapter can be selected at the composition root without
  changing either editor mode.
- Registry parsing enforces the capability contract's stable IDs, non-empty
  labels, namespaced adapter keys, and primitive adapter values.
- Replaced hard-coded simple-mode selects with registry-backed options. An
  unknown authored state stays visible as `未注册` instead of being discarded.
- Updated descriptor evaluation to resolve expression animation through the
  registry and added capability IDs to the demo characters.
- Kept physical Spine names and local paths in adapter values only; no private
  resource bytes or production bundles were added.
- Added a renderer-side `capability-runtime.js` adapter. Stable `motion/*` and
  `emoticon/*` IDs now become independent actor DOM/CSS layers, with
  `data-motion` and `data-emoticon` state exposed for regression checks.
- Wired the four common quick effects in the simple Environment panel to typed
  namespaced events: background pan, screen shake, screen text, and hit effect.
  They share the same descriptor/timeline path as dialogue and stage events;
  unknown professional events remain namespaced and diagnostic-bearing.

## Verification

- Capability registry tests cover injected adapter resolution, fallback states,
  unknown-state preservation, malformed records, and duplicate IDs.
- Existing editor, scene evaluation, and descriptor tests remain covered.
- `18 passed`: scene-editor Vitest suite.
- `6 passed`: scene evaluation and editor contract Python tests.
- `npm run build`: TypeScript check and Vite production build passed.
- Browser smoke against the running editor/preview services passed; the
  registry-backed option lists and `data-timeline-source="supplied"` were
  observed with no page errors.
- `2167 passed, 14 skipped`: full Python suite with the quick-effect event
  contract and browser regression.
- Browser regression confirms motion, emoticon, and screen-text layers remain
  independent of the dialogue panel in static capture mode; realtime uses the
  same state path.

## Follow-up

1. Add a local manifest adapter that reads authorized capability records.
2. Replace CSS motion fallbacks with independent Spine animation tracks where
   the authorized runtime exposes them, keeping the current adapter contract.
3. Add capability preview trials and diagnostics for missing adapter values.

## Publication

- Branch: `feature/1.1-ba-editor-from-1.0`
- PR: https://github.com/Suciko/HaloCue/pull/27
- Commits: `c73b9bb feat(1.1): add character capability registry seam`,
  `f52bf08 refactor(1.1): validate capability adapter records`
