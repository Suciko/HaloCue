# Scene performance character-tween tracer handoff

Date: 2026-08-27

## Outcome

Character enter/exit no longer depends on a CSS-only timeline path. One authored
event now compiles into three renderer-independent numeric contributions:

- `presentation.opacity` in absolute value space;
- `layout.offset-y` relative to the actor's baseline; and
- `presentation.scale` as a factor from the actor's baseline.

The new current contracts are `scene-performance/1.1` and
`scene-evaluation/1.2`. The earlier `scene-performance/1.0` shake-only contract
remains available as historical evidence, not as the current producer output.

## Execution semantics

- Enter samples opacity `0 -> 1`, vertical offset `24px -> 0`, and scale
  `0.97 -> 1`.
- Exit samples opacity `1 -> 0`, vertical offset `0 -> 12px`, and scale
  `1 -> 0.985`.
- Play and exact-frame sampling share ease-out-cubic interpolation.
- Skip commits every contribution to its final value.
- Reduced motion retains the opacity fade but commits offset and scale to their
  final values immediately.
- Stage shake remains suppressed in skip and reduced-motion modes.

Source mapping is explicitly one-to-many: each enter/exit event owns the three
operation IDs, and one primary operation supports future editor selection and
diagnostics.

## Runtime and export

The TypeScript editor compiler, Python project model, and browser runtime emit
and sample the same plan. The preview composes sampled offset and scale with the
existing actor transform and applies sampled opacity. Headless capture receives
the supplied plan and validates that every operation is represented exactly
once by a valid source event mapping.

The live click-to-advance compatibility path still retains its older transient
CSS behavior. Deterministic timeline playback, seek, sample, and export now use
the performance plan; removing the compatibility path belongs in the future
Preview Session slice.

## Verification

- Scene editor: 10 test files, 48 tests passed.
- Python model, contract, preview, and headless renderer integration: 60 tests
  passed, including deterministic exported enter frames.
- Scene editor TypeScript and production build passed.
- Ruff, browser JavaScript syntax checks, and `git diff --check` passed.

## Next slice

Deepen the Preview Session Module with a monotonic generation/token boundary so
late callbacks from a previous scene or seek cannot mutate the newly selected
scene. Keep that work separate from the later Editor Transaction Module.
