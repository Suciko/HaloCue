# Compatibility module provenance —01-008

Baseline `845ee61`; source commit `9cbcfa830954b71b69c3acd7262ee0a3674fbe83`
on local `codex/1.0-autonomous-hardening-ui`. No main merge/push, release, 1.1 edits,
paid provider or real AA/Spine execution. Standard prompt/rules and teacher/Sel
semantics remain unchanged.

## Decision and behavior

The original review recommends a single implementation per process, not hot eviction
of sys.modules or a multi-checkout rewrite. A shared production loader now pins one
canonical compatibility code root under an import lock. It preflights direct module
availability and cached origins, validates loaded origins after import, and rejects
competing explicit code roots or same-name modules from another implementation.
An import failure does not unpin the process: transitive imports may already exist.
Errors explain that the process must be closed and restarted with one selected tree.

`legacy_root` still owns selected local catalog/config/preview data. A directory with
compatibility entrypoint files is an explicit code checkout; a data-only directory
uses the bundled implementation and is never inserted on sys.path. Capability
metadata exposes actual `code_root`, selected `data_root`, and a version read from
the actual code directory's marker rather than the selected data directory's marker.
Quoted current pyproject versions and bundled `VERSION = ...` markers now parse
correctly; this is directory-marker provenance, not a content hash or authenticity
claim for every loaded byte.

Adapter core, lazy teacher/reply/compile/install imports, direction-provider transport
and Spine helpers share this check. Missing optional Spine analysis reports preview
unavailable without failing unrelated capabilities. That exception is restricted to
the missing `spine_face_analysis` module; origin/conflicting-root failures remain
visible. No model connection test or binary invocation was used for verification.

## Boundaries

- This is provenance validation, not an import sandbox. A newly imported transitive
  module can execute import-time code before post-import rejection. The selected and
  bundled source-name sets catch missing-source fallback and cached family pollution;
  they are not a malicious-Python-code isolation boundary.
- Canonical directory aliases are supported by root resolution. An individual source
  link into another checkout is rejected rather than labelled as code from this tree.
  Linked-file coverage simulates Path.resolve and requires no Windows link privilege.
- Origin normalization is bounded/memoized for pinned code. Changing module.__file__
  is still rechecked; filesystem edits/link retargeting require restart. No hot reload,
  content-hash attestation or cache invalidation machinery is promised.
- Frozen coverage simulates a shallow helper path and cached module origin under
  `_MEIPASS`. No packaged artifact was built/run and no comprehensive frozen importer
  or archived transitive-module validation claim is made.
- Earlier test-isolation incident/catalog caveats remain in the runtime-path handoff.
  This slice does not reinterpret that old evidence. Repository aa_config.json stays
  absent and tests use temporary catalogs/configuration.

## Reproduction and focused evidence (overlapping totals)

- Eight isolated-child-interpreter origin tests failed on the baseline: A→B silently
  reuses A, missing provenance metadata, host direct/transitive pollution, incomplete
  checkout fallback, originless module, data-only version confusion, and lazy Spine.
  The initial data-only probe lacked the repository import path; corrected and rerun
  before implementation. Accepted baseline RED: **8 failed, 2.07s**.
- Additional RED checks caught quoted/current version parsing and lazy model transport.
- Frozen shallow default evaluation raised IndexError and missing transitive source
  imported the bundled alternate: **2 failed, 1 passed** before correction.
- Repeated filesystem normalization caused the existing 17 runtime-path tests to take
  **16.40s**; a bounded-operation test observed **111 Path.resolve calls** for a repeated
  lazy import. Memoized normalization retains per-call origin comparison and changed
  __file__ rejection. No general application speedup percentage is claimed.
- Linked-source-file RED demonstrated falsely accepting the resolved expected link;
  canonical-root lexical expected paths fix this. Optional Spine missing-module RED
  drove the narrowly scoped unavailable-state compatibility fix.
- Final focused command:

```text
python -X utf8 -m pytest services/halocue/production/tests/test_legacy_module_origins.py services/halocue/production/tests/test_legacy_version_detection.py services/halocue/production/tests/test_runtime_paths.py -q
```

**37 passed, 5.94s**. Earlier production + integrated suites: **338 passed, 141.68s**,
but that run spanned evolving source and is not the final immutable gate. Changed
Python files pass Ruff check; new helper/new tests/Spine source pass format check;
Git diff check passes. Large existing adapter/provider files were not reformatted.

Scoped reviewer found the optional-Spine regression; its missing-module and conflict
preservation tests now pass. Final static re-review found no remaining actionable
finding, including linked-file provenance and pinned normalization caching. Static
review is not an independent full test run.

The broad suite is now running on the fixed source commit above; final evidence will
be appended after it returns. The autonomous repair goal remains active.


## First accepted immutable-source regression and follow-up layout correction

`9cbcfa830954b71b69c3acd7262ee0a3674fbe83`: **1806 passed in 605.36s**,
exit0, unchanged HEAD/tracked non-document hashes. Wrapper606.52s; exact command and
record are maintainer-local `verified-regression-9cbcfa8.{log,json}`. Counts overlap.

During that run, a draft outside the repository demonstrated a remaining installation
layout edge: a nonfrozen shallow installed service package with a valid explicit
checkout still evaluated parents[5] while building the family name set. This raised
IndexError before loading valid selected code. The external RED probe is preserved
in `module-origin-installed-red.log`; repository source stayed fixed during the run.

Follow-up uses cached discovery of an actual colocated bundled implementation, not
an assumed parent depth. Explicit complete checkouts no longer require bundled code;
a data-only root without any bundled implementation gets an actionable configuration
error instead of guessing an unrelated sys.path root. Two added layout cases plus
origin/version/runtime tests: **39 passed, 4.63s**. Final follow-up review/regression
record will be appended below; the1806 result alone does not verify this later change.


## Installed-layout scoped review closure

Commit `7f05887a4dd0333ac0ad3f3e319adaf969e49f72` corrects the remaining
layout edge. Review then identified that absence of bundled source enumeration must
not drop known transitive names. A combined shallow-install/missing-annotation_memory
probe failed, then a shipped first-party-name manifest fixed the gap. The manifest
contains module names only, not copied implementation; a source-completeness test
requires every root Python module to be listed (historical names may remain).

Final runtime/origin/version focused suite: **41 passed, 4.53s**. Ruff checks and
Git diff checks pass. Read-only reviewer accepted the installed-layout and persistent
family checks; no remaining scoped finding. Fixed-source broad regression is running
on7f05887; no further source edits while it runs. All prior counts overlap.


## Accepted final immutable-source regression

**7f05887a4dd0333ac0ad3f3e319adaf969e49f72** stayed unchanged throughout (HEAD plus tracked
non-document file hashes). **1810 passed in 621.53s**, exit0; wrapper622.90s.
This includes all writing/production/integrated tests and selected root prompt,
compiler, reaction, teacher/selection and policy compatibility coverage. Overlapping
focused/earlier totals must not be added together.

```text
python -X utf8 -m pytest services/halocue/writing/tests services/halocue/production/tests services/halocue/integrated/tests tests/test_direction_profiles.py tests/test_conservative_annotation.py tests/test_annotation_memory.py tests/test_annotation_agent.py tests/test_balanced_direction_prompt.py tests/test_terminal_directive_diagnostics.py tests/test_compiler_face_ids.py tests/test_script_commands.py tests/test_diagnostics.py tests/test_document_golden.py tests/test_official_style_direction_e2e.py tests/test_face_evidence.py tests/test_face_variant_scope.py tests/test_semantic_face_allowlist.py tests/test_semantic_face_catalog.py tests/test_annotation_constraints.py tests/test_annotation_protocol.py tests/test_reaction_placement.py tests/test_reaction_integrity.py tests/test_annotation_speaker_order.py tests/test_listener_policy_diagnostics.py tests/test_director_policy.py -q
```

Maintainer-local evidence: `<WORKSPACE>/output/autonomous-20260907/verified-regression-7f05887.log`
and adjacent JSON command/SHA/stability record. Previous9cbcfa8 evidence remains for
its own earlier commit. No AA config file was created in the repository by these
runs. Main remains58d1128; changes are local, unmerged and unpushed.

01-008 is fixed in this single-implementation scope, not multi-version process
isolation. Packaged execution, actual AA playback and literary/provider quality are
not proved by this suite. The overall autonomous goal remains active. Next planned
work: `docs/superpowers/plans/2026-09-07-adaptation-durable-authoring.md` covers the
full original-prose→durable candidate→explicit scene adoption→production flow; a
queued endpoint alone is explicitly insufficient to close that user-facing gap.
