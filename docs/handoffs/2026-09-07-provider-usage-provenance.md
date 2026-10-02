# Failed-response usage provenance —05-004

Baseline89d0c1a; local `codex/1.0-autonomous-hardening-ui`. No main merge/push/release,
1.1 edits, standard director-prompt/rule/teacher/Sel changes, live model traffic or AA
execution. Existing configured rates are reused; no new pricing table/recommendation.

## Corrected accounting boundary

- Each LLM completion resets thread-local usage before constructing/dispatching the
  request. The current parsed response's usage is captured before completion/refusal/
  truncation validation. Rejected content stays rejected, but reported usage survives.
  Malformed JSON or transport failure cannot inherit a previous successful snapshot.
- Token counts accept bounded nonnegative integers/whole numeric values; bools,
  negative/nonfinite/malformed buckets are invalid, not silently priced. Empty usage
  means not_reported; one missing primary bucket means partial, not a known zero.
  Invalid/partial response usage produces no complete price estimate. Cache absent,
  unsupported and explicitly reported miss/hit remain distinguishable.
- The service normalizer/merger preserves input-total semantics and reported/partial/
  invalid/not_reported/legacy_unknown states. Numeric legacy records keep their known
  counts/subtotal, but cannot be retroactively declared fully reported. Partial costs
  are visibly known subtotals, not a complete-looking bill.
- Existing Agent policy JSON records logical provider observations for conversation,
  scene/rewrite, structure, review, memory/discovery and durable adaptation paths.
  The observation scope writes usage only; it never revives a cancelled run or bypasses
  an artifact/result fence. Usage arriving after cancellation can be retained while the
  candidate is discarded. No new database table or global mutable usage bucket.
- Conversation messages store normalized provider_usage in existing content_json;
  both work reload and presentation events expose its semantics. Older messages use
  normalized legacy columns. Agent totals now expose cost/usage completeness, unknown
  usage run count and `accounting_scope=recorded_logical_calls` while retaining the
  backwards-compatible numeric known subtotal.

## What this does NOT prove

This is not a full physical-request or cross-process billing ledger. Hidden transport
retries, a provider method making multiple internal requests, some direct compatibility
calls, server-crash windows and remote HTTP error usage bodies need the wider05-003/
05-001 work. A cost_status complete_estimate is confined to the recorded observations
and configured rate calculation, not a claim that every billable event is included.
Unavailable usage is not inferred to mean zero use. No hard monetary authorization
budget is introduced here. The separate02-009/05-010 automatic background work issue
remains unresolved. If usage persistence itself fails, the original provider error is
preserved with an audit-failure note; a broken database is not silently claimed fixed.

## Review corrections and tests

- Baseline14 REDs covered stale previous usage, dropped truncated-response usage,
  malformed bucket values, empty/partial response semantics, merge completeness and
  normalized error metadata. Transport/parser/provider-focused50passed1.50s after fix.
- Failure consumers initially RED for conversation/adaptation/cancelled adaptation.
  A first fixture used a nonexistent send_conversation_message name; corrected to the
  actual post_conversation_message. Actual model responses remain synthetic.
- Failed scene candidate, scene review, continuity and release review consumers are
  tested through their persisted runs. Work-review fixtures initially lacked a prompt
  assembler and never reached transport; explicit synthetic assembler fixed the test
  setup instead of bypassing product gates or claiming those earlier attempts passed.
- Reviewer found follow-up snapshot double-add when scope-exit audit persistence
  failed, and a nonexistent unknown call being recorded on cancellation before a
  follow-up. Both reproduced in real service/synthetic-provider tests (2REDs), then
  moved liveness checks before scope entry and accumulation after successful scope exit.
- Adaptation likewise opens its scope only around the actual provider invocation,
  after budget/lease/source preflight, not around a whole method that might stop early.
- Reviewer found the standalone formatter had no active UI caller. New RED tests
  invoked the actual sceneProposalRuntimeMarkup and failed workAgentToolMarkup path;
  both now delegate to status-aware labels. Conversation failure/success technical
  details and scene proposal runtime details show unknown usage/partial cost. Unknown
  cache is not displayed as miss; unsupported cache has its own label.
- A legacy follow-up test expected exact old five-field usage. Updated its exact
  expected dictionary to include the five new provenance fields, preserving all old
  numeric expectations and explicitly identifying that old fixture as legacy_unknown.
  No subset assertion used to hide an incompatible numeric total.
- Earlier202 provider/vertical/adaptation/presentation cases passed141.11s before final
  live-UI wiring.5 UI tests passed0.53s. Final focused/broad evidence is appended below.
  These totals overlap and must not be summed.

Changed Python checks passed; large service retains3 baseline lint issues with zero
new issues. JS syntax/diff checks passed. Scoped reviewer closed its three reported
P2s by caller/source inspection, not an independently rerun broad suite. Overall repair
goal remains active and no real literary/model/packaged/AA playback acceptance implied.


## Committed source and final focused acceptance

Source `e65ae263fdf23cf7a2876eabf275af46b5e2d5f7`. Final focused command:

```text
python -X utf8 -m pytest services/halocue/writing/tests/test_usage_failure_provenance.py services/halocue/writing/tests/test_usage_ui.py services/halocue/writing/tests/test_agent_presentation.py services/halocue/writing/tests/test_agent_production.py -q
```

**78 passed40.41s**. This is after the legacy exact-dictionary test update and live
renderer wiring. New tests include cancellation before any provider invocation,
cancellation before follow-up, scope-exit failure without double-add, failed follow-up
with both observations once, reported/unknown message reload and persistent failed
conversation/scene/review/adaptation usage. UI tests call the actual active renderer
functions (not only the formerly unused formatter); they are Node HTML-output checks,
not a new full-browser screenshot acceptance run.

The unchanged-source broad run is currently active one65ae26. While waiting, a separate
outside-repository synthetic transport probe observed two urlopen attempts (timeout
then success) but only final response usage in the snapshot. Evidence is
`<WORKSPACE>/output/autonomous-20260907/physical-attempt-observation.json`. This confirms
the next05-003 boundary remains open; no real network call occurred. The next plan is
`docs/superpowers/plans/2026-09-07-physical-request-usage-ledger.md`.


## First immutable-source broad run and contract-test corrections

`e65ae263fdf23cf7a2876eabf275af46b5e2d5f7` stayed unchanged; **4failed,
1893passed923.62s**, wrapper925.02s. Three failures were provider-pinning tests expecting
exact old five-field usage dictionaries; all five numeric values matched, while new
legacy/provenance fields caused equality failure. Tests now explicitly expect the
normalized ten-field legacy contract, including message projection; raw provider
fixture data remains unchanged. An intermediate edit missed the message dictionary's
key set and failed once, then was corrected—not treated as product success.

The fourth failure was the existing browser prerequisite test reading an already
visible background textarea immediately after closing the dialog, before the async
navigation fetch applied its prefill. It now waits for the actual expected value with
Playwright's retrying assertion, not just visibility. No product prefill/CSP behavior
was changed or hidden, and the test still requires zero automatic Agent runs.
The failed broad evidence is retained; a fresh fixed-source run follows after the
focused corrections pass.


## Accepted final immutable-source regression

Follow-up test commit **f5ba3ea806e2986047d7265e1825e83042a548a5** stayed unchanged throughout
(HEAD and tracked non-document hashes). **1897 passed in947.13s**, exit0; wrapper948.50s.
The focused provider-pinning and browser corrections passed9tests27.88s beforehand.
The earlier4-failure broad run remains evidence for its own commit, not a green result.
All counts overlap and must not be added together.

```text
python -X utf8 -m pytest services/halocue/writing/tests services/halocue/production/tests services/halocue/integrated/tests tests/test_direction_profiles.py tests/test_conservative_annotation.py tests/test_annotation_memory.py tests/test_annotation_agent.py tests/test_balanced_direction_prompt.py tests/test_terminal_directive_diagnostics.py tests/test_compiler_face_ids.py tests/test_script_commands.py tests/test_diagnostics.py tests/test_document_golden.py tests/test_official_style_direction_e2e.py tests/test_face_evidence.py tests/test_face_variant_scope.py tests/test_semantic_face_allowlist.py tests/test_semantic_face_catalog.py tests/test_annotation_constraints.py tests/test_annotation_protocol.py tests/test_reaction_placement.py tests/test_reaction_integrity.py tests/test_annotation_speaker_order.py tests/test_listener_policy_diagnostics.py tests/test_director_policy.py -q
```

Maintainer-local evidence: `<WORKSPACE>/output/autonomous-20260907/verified-regression-f5ba3ea.log`
and adjacent JSON command/SHA/stability record. Main remains58d1128; no merge/push/
release or1.1 worktree edit. Repository aa_config.json remains absent; scratch/tmp
content preserved. Standard prompt/teacher/Sel compatibility is covered by the selected
root suites, not an absolute claim that shared source has zero downstream impact.

05-004 is fixed in the implemented logical-response provenance/consumer/UI scope.
05-003 remains open for complete physical-request accounting, as the two-attempt
synthetic probe demonstrates.05-001 has improved durable adaptation usage inclusion,
but direct compatibility/internal calls and physical retries are not retroactively
invented. The overall autonomous goal remains active; no real provider literary,
packaged-runtime or AA/Spine playback acceptance is claimed.
