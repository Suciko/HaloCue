# Teacher presentation handoff

- Kind: handoff
- Status: implementation and automated validation complete; awaiting PR review
- Observed: 2026-09-06
- Scope: HaloCue 1.0 production and AA compatibility
- Issue: https://github.com/Suciko/HaloCue/issues/36
- Branch: `codex/1.0-teacher-sel`
- Base: `codex/1.0-teacher-identity` at `4fd4bbf143a384cb6e0fb2101c2c039a01c9faf3`
- Dependency: PR #35 remains open; deliver a stacked PR, never merge shared branches.
- Source of truth: product direction, backend context, ADR-0001/0004/0006,
  remote collaboration protocol, Issue #36 and preceding teacher identity handoff.

## Scope

Allow the user to present explicitly bound teacher lines as ordinary slot-zero
dialogue or a single clickable Sel answer, keeping a linear story and identical
source text. No automatic multi-option choices, new story branches, paid model
calls, private AA resources, document imports or editor redesign.

## Contract

The existing teacher mapping request gains optional `presentation`, an object
with `schema_version: "teacher-presentation/1.0"` and `mode: "slot_zero"` or
`"sel_single"`. It is stored independently as `draft.cast.teacher_presentation`.
Omission preserves the saved presentation (or slot-zero for an older task).
Identity remains `teacher-identity/1.0`; source names, teacher ID and source/card
identities do not change. Changes require review and invalidate older jobs/builds.

Capabilities add `teacher_presentation: {state, schema_version, default_mode,
modes}`; modes are `slot_zero` and `sel_single`. The old teacher-identity
capability's `presentation: slot_zero` remains the identity default.
Sel preview frames retain original `card_id`, `text` and `speaker` but set
`presentation: teacher_selection` and include `teacher_reply: {reply_id,
continuation_id, text, source_card_id}`. The click changes preview navigation
only, never draft state. A terminal reply marks preview completion.

Compile snapshots additionally freeze `teacher-reply-plan/1.0` when Sel is
selected. Each ordered line references its stable source card, text hash,
character identity and deterministic reply/continuation UUIDs. Position pairs
records during deterministic compilation but is never their identity. The plan
pins source and compiled-text hashes; CG retargeting validates unchanged line
order/text/character bindings. Slot-zero builds do not need this plan.

## Agreed Test Boundaries

Continue the preceding slice's mapping API/read/restart, DraftStore state/CAS,
compiler and BuildBundle input/output, explicit isolated installation and real
browser controls. Verify unknown versions, old-client omission, no-op reuse,
first/last/consecutive replies, CG, stable source-derived IDs and late results.
Native export must be backed by format evidence; unresolved native semantics
must be recorded as capability limits rather than assumed.

## Baseline

Unchanged `4fd4bbf`: production full suite plus teacher identity/store/export and
script commands: 331 passed (97.72 seconds). Existing complete root baseline:
1589 passed, one release-workflow assertion failure, 26 missing-Chromium setup
errors, ten skips, five private-AA exclusions. Writing 641 and integrated 13
passed in the preceding delivery. Tests use Edge for production browser cases.

## Implementation

- `teacher_presentation.py` adds versioned `slot_zero` / `sel_single` selection,
  strict validation and deterministic reply/continuation UUIDs.
- `teacher_identity.py` and `draft_store.py` persist presentation with the
  existing teacher transaction. Omission preserves old behavior; changes keep
  the teacher ID but invalidate review/build claims.
- `teacher_reply_plan.py` freezes source card IDs, text hashes and bindings.
  Unsafe or empty answer text is blocked. `build_bundle.py` carries the plan in
  immutable snapshots.
- `aa_teacher_selection.py` projects selected lines to native-shaped
  `SelectionNodeData` with one outgoing edge and sixteen text slots;
  `script2aap.py` validates and applies it, while `verify.py` checks shape,
  targets, identity uniqueness and cycles. Ordinary slot-zero output is kept.
- `legacy_adapter.py` and production service expose capabilities, diagnostics,
  read-only reply preview, CG retargeting and stable errors. AAP import reports
  SelectionNodeData rather than silently dropping it.
- The production workbench adds explicit presentation radios, capability-aware
  fallback, shared-alias confirmation, CAS retention and a read-only answer
  button. Clicking it never writes a draft.
- `docs/compatibility/aa-single-selection.md` records AA field/RVA evidence and
  the native-playback boundary. No private AA bytes or decompiled source were
  copied.

## Validation

Focused identity/presentation/reply/export/production/writing tests: **251
passed**. This includes 12 Edge browser tests for controls, restart,
unsupported capability, CAS, consecutive/terminal replies, CG/background and
HTML escaping. `node --check app.js`, new-file Ruff formatting and `git diff
--check` pass. Delivery tests cover release -> teacher -> Sel -> review ->
BuildBundle -> explicit isolated install and switching back to slot 0.

The complete root baseline still contains one pre-existing release-workflow
assertion and 26 missing-Chromium setup errors. Native AA playback, audio and
multi-choice branching remain manual or future scope. A single answer is
linear; this delivery does not invent alternate story branches or change
writing text.

## Delivery

Code commits:

- `2bf090b`: versioned presentation/reply contracts, deterministic Sel graph
  projection, compiler/validator and writing import warning.
- `b62a817`: production capabilities, mapping persistence, preview, service
  integration and browser controls/tests.
- `2c096c2`: README, evidence and this handoff.

PR: https://github.com/Suciko/HaloCue/pull/37 (base
`codex/1.0-teacher-identity`, head `codex/1.0-teacher-sel`). The remote branch
tip is `2c096c2ff6a74bd9c52aa0331ead686c94d37bfc`, verified against local Git
objects. GitHub Git Data upload was used after Git HTTPS reset the connection;
no force update or shared-branch merge occurred.

Final focused run: **251 passed**; production full suite **224 passed**; writing
and integrated suites **655 passed**. `node --check app.js`, new-file Ruff
formatting and `git diff --check` pass. Root baseline limitations remain one
pre-existing release-workflow assertion and 26 missing-Chromium setup errors.

Do not merge #35 or this branch automatically; review in dependency order.
