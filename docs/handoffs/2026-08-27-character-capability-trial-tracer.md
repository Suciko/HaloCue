# Character capability trial tracer handoff

- Kind: handoff
- Scope: release 1.1, `contexts/ba-editor`, Issue #24, PR #27
- Status: implemented
- Observed at: 2026-08-27
- Owner: HaloCue maintainers
- Source branch: `feature/1.1-ba-editor-from-1.0`
- Implementation commit: `91fd4c0`
- PR: <https://github.com/Suciko/HaloCue/pull/27>

## Outcome

The simple character inspector now treats expression, motion, and emoticon as
browsable semantic capabilities instead of immediate-commit select fields.
Each picker:

- reads stable state IDs and labels from `character-capabilities/1.0`;
- marks the authored state independently from a temporary trial state;
- starts realtime trial on pointer hover or keyboard focus;
- confirms the current candidate only on click;
- cancels on Escape, focus/pointer exit, mode/tab/slot/Cue/Scene changes, another
  command, or any new transaction; and
- reports trial, confirmation, and cancellation through a polite live region.

Unknown authored IDs are prepended to the registered choices, remain visible,
and carry an explicit `能力目录未注册` diagnostic. They are disabled for trial
instead of being silently converted to a default state. Registered choices keep
their renderer-neutral state IDs; physical resources and adapter names remain
outside project data.

## Transaction boundary

Editor Transactions now declare an interruption policy:

- `commit` remains the default for text, numeric, resize, and gesture edits;
- `cancel` is used for non-committing capability trials.

An interrupted cancel-policy transaction restores its exact project and
selection base, dirty flag, and diagnostics, then increments only the working
preview revision. It creates no authoring revision, history entry, future entry,
or autosave request. Explicit confirmation still uses `commitTransaction`, so a
supported capability becomes one durable edit and one Undo step.

`previewCharacterState` and `updateCharacterState` share one patch operation.
Inherited character state is authored as one local enter/state override only
when the projected value actually changes; confirming the already-authored
state remains a no-op.

## Changed paths

- `apps/desktop-client/scene-editor/src/capabilities.ts`
- `apps/desktop-client/scene-editor/src/capabilities.test.ts`
- `apps/desktop-client/scene-editor/src/projectStore.ts`
- `apps/desktop-client/scene-editor/src/projectRepository.test.ts`
- `apps/desktop-client/scene-editor/src/capabilityTrialUi.test.tsx`
- `apps/desktop-client/scene-editor/src/App.tsx`
- `apps/desktop-client/scene-editor/src/styles.css`

No canonical project, capability, animation, preview, renderer, migration,
resource, or cross-context contract changed.

## Verification

From `apps/desktop-client/scene-editor`:

```text
npm run test
22 test files passed; 122 tests passed.

npm run build
TypeScript no-emit and Vite production build passed; 1605 modules transformed.
The existing unresolved preview-font build warning remains unchanged.
```

Registry tests distinguish registered and unregistered options while preserving
the existing compatibility list. Repository/Store tests prove working preview,
cancel-on-interrupt restoration, zero history/revision/autosave writes during
trial, one explicit commit, and one-step Undo. Complete-App tests exercise
pointer trial/cancel, click confirmation, authored/trial markers, and unknown
state diagnostics.

A browser check showed compact expression, motion, and emoticon capability
cards in the simple character inspector. Keyboard focus on `微笑` displayed
`试演中 · 单击确认`; Escape restored authored `认真`. Clicking `点头` selected it,
enabled Undo, and announced `动作已设为 点头`; one Undo restored authored `待机`.

## Known boundary and next action

This slice establishes safe authoring trials, but it does not prove every
capability's intermediate animation through the deterministic Scene Performance
path. Expression resolves through the capability adapter, while `motion/nod`
and emoticon pop still depend on browser-runtime CSS classes for visible motion.
Deterministic capture disables CSS animation, so realtime and export can still
disagree about intermediate frames.

The next bounded animation slice should normalize `motion/nod` through the
versioned Scene Performance contract. The same authored state must produce
seek-safe play/sample/skip/reduced-motion operations, browser execution, Python
parity, and headless intermediate-frame evidence. The capability trial should
then preview that compiled operation rather than a CSS-only pulse. Emoticon pop
can follow through the same target/channel/lifecycle seam after nod is proven.
