# Discussion prefix stability and manuscript freshness — 2026-09-24

## Scope
User asked to continue after identifying three authoring workflows and the need for careful cache handling. This slice inspects the existing discussion provider pipeline, improves deterministic prompt layout, and verifies saved-manuscript freshness. It is not a response cache, import implementation, or measured remote cache-hit claim. Existing dirty provider changes remain untouched.

## Findings
- Discussion service reads current scene revision and confirmed artifacts for each new turn, and captures the input snapshot. This path should not be replaced with cached stale context.
- Provider previously serialized work_context in construction order: summary, attachments and retrieved document chunks preceded scene materials. Scene current_manuscript also preceded confirmed materials. Updates early in the serialization prevented the remaining confirmed-material text from staying in a common request prefix.
- Summary-trust guidance first appeared only after a summary existed; tool followup appended an extra system instruction. Both changed system text during otherwise related turns.
- Usage code already distinguishes reported hit/miss, unsupported and unknown and normalizes provider counters; no fake hit estimator is introduced.

## Changes
- New discussion_prompt.py produces a deterministic JSON-key layout: stable work/scope/material content first, current manuscript and revision references retained, then dynamic contract/summary/retrieval/history suffixes. All keys/values, unknown fields, list order and source citations preserved. No mutation or local persistence of prompt data.
- Discussion system prompt always includes summary trust boundaries and conditional tool-followup instructions. Native tool messages/results and authorization remain unchanged.
- No TTL, provider cache-control fields, token prices, usage schema or backend authoring semantics changed. Anthropic's existing system-block cache annotation remains; this change does not newly annotate user-context blocks.

## Tests
New test_discussion_prompt_cache_layout.py: 11 passed. Lossless roundtrip and deterministic key ordering; stable confirmed-material prefix across summary/retrieval/attachment/current-revision/workflow updates; work/scene changes retained; captured OpenAI-compatible and Anthropic HTTP request bodies with fake transport; missing usage remains unknown/not_reported; tool-followup system consistency. Service test saves r1, discusses, saves different r2, discusses again: next provider context/task scope/snapshot contain r2 and new text, not r1 manuscript, while confirmed materials remain stable and no proposal is auto-created.

Regression command:
python -m pytest services/halocue/writing/tests/test_provider_tool_calling.py services/halocue/writing/tests/test_provider_capabilities.py services/halocue/writing/tests/test_scene_conversation_harness.py services/halocue/writing/tests/test_physical_request_ledger.py services/halocue/writing/tests/test_usage_failure_provenance.py services/halocue/writing/tests/test_usage_ui.py -q
Result: 85 passed.

New files formatted with Ruff; Ruff check passed. Python compilation and git diff --check for provider passed. No real provider credential/network calls, user data writes, runtime restart, commit, package, deploy or full-repository suite. Tests use disposable synthetic workspaces and intercepted/local HTTP.

## Remaining audit
Actual remote cache-hit rates and latency require provider-reported telemetry from authorized real runs; unchanged prefixes alone are not proof of a hit. Imported-document retrieval fields are preserved/tested but the end-to-end import workflow is not changed in this slice. Saved manual text is current; unsaved editor text still requires explicit save before asking Agent, as in the existing UI. No automatic generation or acceptance added.