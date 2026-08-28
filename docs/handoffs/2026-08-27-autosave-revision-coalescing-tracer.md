# Autosave revision coalescing tracer handoff

Date: 2026-08-27

## Outcome

Logical editor commit and durable draft persistence are now separate revision
boundaries. A command first validates and serializes its complete candidate,
then atomically publishes project, canonical selection, history, dirty state,
diagnostics, and revision. The accepted revision is queued for autosave rather
than writing storage inside every command.

Autosave exposes explicit state:

- `savedRevision` is the latest revision confirmed by the repository;
- `pendingRevision` is the latest complete revision waiting or retrying;
- `status` is `saved`, `pending`, or `failed`; and
- `error` preserves the last storage failure for the UI.

## Scheduling and recovery

Committed revisions enter a 450 ms latest-only window. A newer commit cancels
the older timer, so a burst of typing or several immediate commands writes only
the latest full project. Preview compilation uses its own 72 ms generation and
never shares autosave revision identity.

Candidate validation failure still publishes nothing. Once a valid transaction
has been published, a storage failure does not roll it back or corrupt history;
the editor shows “自动保存失败”, retains the complete snapshot, and offers a
retry action. Retry persists the same pending revision. Local storage keeps its
existing pending/current two-key recovery protocol.

Explicit project export and browser unload flush pending autosave work before
continuing. Export still reads the latest store project and remains available
if local draft persistence fails.

## Verification

Tests cover latest-only burst persistence, synchronous flush, failed-save
retry, Store-level revision coalescing, validation atomicity for edit/undo/redo
and gesture commit, and complete-state retention after background persistence
failure. The full frontend and focused cross-runtime suites are the release
boundary for this tracer. Verification completed with 71 scene-editor tests,
35 focused Python/model/browser regression tests, the production TypeScript
build, and the whitespace check.

## Remaining work

The next mature-interaction slices should apply gesture transactions to text
composition, numeric scrubbing, and future timeline handles. Autosave may later
gain timestamped recovery snapshots or desktop filesystem persistence, but
those are separate repository adapters rather than reasons to weaken the
current transaction and revision contracts.
