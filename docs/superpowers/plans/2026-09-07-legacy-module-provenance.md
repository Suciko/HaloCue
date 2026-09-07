# Legacy module provenance —01-008 implementation plan

> Next bounded slice; not implemented by the runtime-path/idle-poll commits.

**Goal:** Never report selected checkout B's version while executing cached modules
from A, and never silently mix two compatibility implementations in one process.

**Observed code:** `Legacy093Adapter.__init__` derives `legacy_version` from
`settings.legacy_root` before `_load_modules` inserts that root into sys.path and calls
`importlib.import_module`. Imports honor existing sys.modules entries regardless of
the new search root. The data-root isolation fixtures intentionally use synthetic
legacy directories while sharing repository code; that legitimate separation must
remain available and must not be mislabeled as execution of the synthetic directory.

**Options:**
1. Namespaced loading/subprocess isolation: supports multiple code roots but is a large
   compatibility migration because root modules import one another by global names.
2. Evict/reload sys.modules: reject as unsafe for existing adapter references/threads.
3. Recommended bounded correction: report actual imported module provenance and fail
   closed on an explicitly selected competing code checkout rather than silently
   reusing another root. Preserve data-only roots as data selection, not code identity.

**Files to inspect/change:** production `legacy_adapter.py` and narrow helper if
needed; `test_legacy_version_detection.py` plus new subprocess module-origin tests;
other dynamic loaders (`spine_rendering.py`, resource previews and model settings)
only if needed to prevent a contradictory code-root promise. Do not merely patch
version strings while continuing mismatched requested code execution.

- [x] Reproduce A then B in a clean child Python process with synthetic compatibility
      modules and markers; assert mismatch is denied or isolated, never mislabeled.
- [x] Determine exact existing explicit-code vs data-only-root semantics from callers
      and runtime packaging. Pin one actual module family; account for frozen origins.
- [x] Derive reported version from actual code origin, retain selected data-root
      provenance separately, and provide an actionable restart/config error for a
      conflicting explicit code selection. Do not reveal secrets in diagnostics.
- [x] Test A→A reuse; A→B conflict; B first; data-only roots use shared actual code;
      partial/mixed module sets; preserve original adapter after rejected second root.
- [x] Confirm transitive module imports and optional teacher/Spine loaders cannot bypass
      the origin check. Do not invalidate modules while workers are running.
- [x] Run production/integrated/compiler/prompt/teacher/Sel checks with synthetic data.
- [x] Scoped review, immutable-source broad regression, bounded ledger/handoff update.

No standard-prompt changes, real asset reads/writes, paid calls, main merge/push or
1.1 worktree edits. A local provenance guard is not full multi-checkout isolation;
state that limitation explicitly rather than claiming the larger architecture solved.


## Implementation progress

Source9cbcfa8 implements the review's single-process single-implementation boundary,
shared guards for core and lazy production imports, code/data provenance, and actual
code-directory marker parsing. Sixteen new isolated origin cases plus two additional
version cases cover the planned source behavior; runtime/origin/version37 focused
checks pass. Scoped review accepted after optional-Spine and linked-file fixes.
Frozen tests are simulations only; packaged artifact validation remains outside this
synthetic evidence. Full immutable-source regression is in flight; see the handoff.

Accepted7f05887: 1810 unchanged-source regression tests passed621.53s; installation layout correction and shipped family manifest reviewed. This completes the bounded review recommendation only; see explicit frozen/non-sandbox boundaries in handoff.
