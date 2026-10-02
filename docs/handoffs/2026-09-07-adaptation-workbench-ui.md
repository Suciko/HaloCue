# Ordinary prose adaptation UI —02-007 /07-011, slice C

Baseline1923719; local `codex/1.0-autonomous-hardening-ui`. No main merge/push/release,
1.1 edits, standard director prompt/rule/teacher/Sel changes or real provider/AA calls.
This is the ordinary prose UI connection, not complete cost/input/model-quality work.

## Shipping behavior

TXT/DOCX chosen through the existing ordinary import control now opens a dedicated
source→plan→candidate dialog. AAP retains its original engineering preview/attachment
path. The same import dialog offers “继续原文改编” for saved plans/tasks/candidates.
No source save, file selection or plan confirmation automatically invokes a model.

The controller consumes existing source preview/apply, adaptation plan, durable Agent
run, proposal acceptance and legacy promotion endpoints. It uses applied source IDs,
not transient preview chapter IDs. Update selection is ordered by source chapter order,
not checkbox-click insertion order. The logical call cap is visibly not a full token/
monetary ledger. Current simulation/model disclosure and expected-provider guard prevent
executing against a model silently changed since the user saw the generation button.

New adoption shows the server-pinned create/replace scene target and quoted source
references; old pending proposals use an explicit confirmation button with server-
resolved target projection, not a guessed work display-order default. Old accepted
artifacts have explicit chapter selection/promotion. Accepted results navigate to the
normal scene editor. Cancel/retry use existing durable run APIs, and reloading/reopening
reads server truth instead of enqueueing a second request.

The current workbench consolidates brief/direction editing into creative conversation;
old renderBrief definitions are not a reliable guide to the shipped surface. The
prerequisite action navigates to that actual conversation and prefills a bounded
request without sending it. Authors still discuss/organize/accept formal direction
and satisfy normal review/release gates. The UI does not fabricate those artifacts.

## UI isolation and design

One small bridge in app.js connects the focused new controller; no framework/library,
font fetch or second editable work model. Existing unsaved-manuscript navigation guards
run before entering or leaving into the scene editor. Deferred source reads check
import-flow identity, captured work and open dialog before applying/opening anything.
Controller epochs fence late work/poll responses; starting a mutation invalidates
polls already in flight, not only the next timer. Mutation controls are disabled while
busy; close/Escape remains available. Unsaved mapping/budget form state does not leak
into a different work on reopen. Paths, filenames, candidate and quote text are escaped.

Scoped stylesheet follows the existing paper/ink/green editorial tokens. Desktop is a
spacious two-column dialog; mobile puts the candidate and model/scope disclosure first,
with summary below. Step navigation uses usable focus targets rather than tiny default
buttons. Canonical text sits on a quiet paper panel. Screenshots inspected at1440x1000
and375x850;320px overflow assertion is also included. No heavy animations/dependencies.

## RED and review evidence

- New controller tests initially missing-file RED; syntax/fixture mistakes were corrected
  before accepting any results. An isolated test accidentally returned an unresolved
  promise from page.evaluate and hung; its exact owned pytest process was inspected,
  stopped and rerun after fixing the harness (no duplicate broad run was started).
- Entry routing initially failed the new TXT/DOCX control contract; shipping bridge
  now chooses source flow only for prose and retains AAP.
- Expected provider mismatch at enqueue initially accepted: RED then reject before job
  creation, including displayed simulation→real changes.
- Review exposed entry-file close/work switch race, checkbox update ordering and legacy
  target guessing. Concrete REDs reproduced each; fixed flow fence, source-order IDs,
  and read-only backend resolved_target projection. Missing target yields no invented
  destination. Older candidate bytes remain immutable.
- Review exposed an in-flight terminal polling reload restoring pre-acceptance UI after
  a successful mutation. Deterministic RED holds four old snapshots, accepts then
  releases them. Advancing epoch at action start keeps accepted scene state intact.
- Unsaved character mapping persisted into another work: RED then reset draft fields
  on open. Busy source controls and no-close-reopen late state have DOM regressions.
- Scoped re-review found no remaining concrete blocker; this is not a whole-codebase
  audit or proof that every future provider/output shape is correct.

## Browser vertical evidence and limits

The integrated browser test loads shipping HTML/JS/CSS, opens the real import menu,
selects TXT and DOCX, previews/saves source, establishes/confirms a plan, requests a
synthetic durable model, reviews target/text, reloads/reopens, accepts and navigates
to the actual scene editor. It then uses ordinary backend review/memory skip/continuity/
release review/freeze APIs and the actual Production HTTP handoff, checking dialogue
and upstream release identity. Gate artifacts are not patched into the database.

A separate fresh-work browser case verifies AAP preview remains in the original
flow, prose creates source/empty work with zero Agent runs, and prerequisite navigation
prefills the real creative conversation without model calls. Direction/review gates
in the complete vertical trace are explicit synthetic fixture/API author actions—not
claimed as fully click-driven release UI acceptance or real AA playback.

Initial integration harness errors: clicking a control inside closed details required
opening the real attachment menu; Playwright string wait_for_function conflicted with
CSP, replaced by DOM waits (no CSP weakening); assumed briefForm was superseded by
creative conversation, so the test/action was corrected to the actual surface.

User guide added at docs/manual/原文改编.md, linked from manual index/continuous guide,
with entrypoint scope, source save/no-model boundary, real-model sending, logical-call
budget limits, cancel/retry/reopen, target and legacy promotion, and prerequisites.
Help endpoint/desktop packaging consistency remains tracked separately—not implied
fixed by a Markdown guide or a new writing-service component.

Earlier focused evidence:9DOMpass10.59s, then12DOMpass14.07s;51UI/dispatch/adoption
pass77.06s. BrowserTXT/DOCX/freshwork3passed22.97s. Counts overlap and predate final
small test additions. Final focused/commit/immutable broad evidence follows below.


## Source commit / final focused checks

`d4e7cfa164991c8705cda47ac07fab24cf5db2fc` contains the scoped UI, optional
expected-provider admission guard, canonical target projection and new tests. Final
focused command (before the additional320px/Escape assertions, which are included in
the committed broad suite):

```text
python -X utf8 -m pytest services/halocue/writing/tests/test_adaptation_workbench_ui.py services/halocue/writing/tests/test_settings_controller_browser.py services/halocue/writing/tests/test_import_adoption.py services/halocue/writing/tests/test_story_import.py services/halocue/writing/tests/test_aap_import.py services/halocue/writing/tests/test_adaptation_dispatch.py services/halocue/writing/tests/test_adaptation_scene_adoption.py services/halocue/integrated/tests/test_adaptation_workbench_browser.py -q
```

**63 passed71.01s**. JS syntax checks, changed Python Ruff checks, CSS parsing65top-level
rules and Git diff check passed. The initially assumed missing CSS variables were
found in existing tokens.css; final stylesheet reuses those canonical tokens instead
of redefining fonts/surface aliases. Main inspected desktop and375px screenshots after
visual fixes;320px overflow and native Escape closure are regression assertions.

Final reviewer accepted all reported P2 closures by code inspection; no independent
broad run claimed. The unchanged-source broad suite is running againstd4e7cfa. During
that wait, three outside-repository synthetic probes reproduced the next usage issue
(stale previous usage after truncation/timeout and dropped unknown semantics), without
changing tracked source. Next bounded plan: provider-usage-failure-provenance.


## Accepted final immutable-source regression

**d4e7cfa164991c8705cda47ac07fab24cf5db2fc** remained unchanged throughout, verified by HEAD
and tracked non-document hashes. **1865 passed in921.62s**, exit0; wrapper923.02s.
This includes both TXT/DOCX shipping-browser traces, first-work/AAP boundary and320px/
Escape assertions. Counts above overlap with this run; do not add them together.

```text
python -X utf8 -m pytest services/halocue/writing/tests services/halocue/production/tests services/halocue/integrated/tests tests/test_direction_profiles.py tests/test_conservative_annotation.py tests/test_annotation_memory.py tests/test_annotation_agent.py tests/test_balanced_direction_prompt.py tests/test_terminal_directive_diagnostics.py tests/test_compiler_face_ids.py tests/test_script_commands.py tests/test_diagnostics.py tests/test_document_golden.py tests/test_official_style_direction_e2e.py tests/test_face_evidence.py tests/test_face_variant_scope.py tests/test_semantic_face_allowlist.py tests/test_semantic_face_catalog.py tests/test_annotation_constraints.py tests/test_annotation_protocol.py tests/test_reaction_placement.py tests/test_reaction_integrity.py tests/test_annotation_speaker_order.py tests/test_listener_policy_diagnostics.py tests/test_director_policy.py -q
```

Maintainer-local evidence: `<WORKSPACE>/output/autonomous-20260907/verified-regression-d4e7cfa.log`
and adjacent JSON command/SHA/stability record; inspected UI screenshots are
`adaptation-desktop.png` and `adaptation-mobile.png` beside them. These are synthetic
fixtures, not user manuscripts or paid-model output. Repository aa_config.json remains
absent. Main stays58d1128; repair branch is local, unmerged and unpushed.

02-007 is fixed in the implemented1.0 source/plan/durable candidate/canonical-scene/
ordinary release-Production pathway, with explicit UI and API acceptance boundaries.
07-011 now has a real prose workflow and matching guide, not a tutorial inferred from
unused APIs. Packaged entry/help consistency, physical/unknown usage, input bounds,
background knowledge authorization and real literary/playback acceptance remain open.
The overall autonomous goal is still active; next bounded work is the reproduced
provider-usage failure provenance issue, not a claim that all backend findings closed.
