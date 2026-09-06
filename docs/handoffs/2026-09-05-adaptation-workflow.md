# HaloCue 1.0 adaptation handoff

- Branch: `feature/1.0-adaptation-workflow`
- Issues: [#29](https://github.com/Suciko/HaloCue/issues/29) model activation; [#30](https://github.com/Suciko/HaloCue/issues/30) source snapshots and adaptation checkpoints.
- Source workflow: TXT/DOCX preview uses final DOCX body, stable source chapter/paragraph IDs, immutable source versions, explicit append/update mode, selected-chapter diff, duplicate detection, unfinished state, and ordered windows for 99k/100k/500k-character fixtures.
- Adaptation workflow: create a source-bound `adaptations` task, inspect `adaptation-plan/1.0`, approve the plan, run checkpointed coverage analysis, then generate a non-formal `adaptation-chapter/1.0` candidate with source references and the `adaptation/1.0` prompt contract. Candidate generation never writes formal scene revisions.
- Provider workflow: OpenAI/Anthropic completion envelopes require a normal termination reason; truncation, refusal, pause, missing fields and invalid tool termination are rejected. Candidate credentials are endpoint/protocol-bound, environment-backed keys stay in the environment, public config switches atomically, and old runtime tasks keep their pinned digest.

## Collaborator smoke test

```powershell
cd 01-repo/HaloCue
E:/Miniconda3/python.exe -X utf8 -m pytest services/halocue/writing/tests/test_adaptation_sources.py services/halocue/writing/tests/test_adaptation_workflow.py services/halocue/writing/tests/test_adaptation_prompt_contract.py -q
E:/Miniconda3/python.exe -X utf8 -m pytest services/halocue/writing/tests/test_provider_response_contract.py services/halocue/writing/tests/test_model_candidate_binding.py -q
E:/Miniconda3/python.exe -X utf8 -m pytest services/halocue/production/tests/test_settings_direction.py services/halocue/production/tests/test_http_api.py -q
```

Use the local writing service API:

1. `POST /api/v1/works`.
2. `POST /api/v1/works/{work_id}/source:preview`, then repeat with `preview_digest` at `source:update`.
3. `POST /api/v1/works/{work_id}/adaptations` with `source_version_id`, optional `chapter_ids`, `max_calls`.
4. `GET /api/v1/works/{work_id}/adaptations/{adaptation_id}` and approve with `POST .../plan:approve` using `plan_digest`.
5. `POST .../adaptations/{adaptation_id}/run`, then `POST .../chapters/{source_chapter_id}/candidate:generate`.

The collaborator still needs to review candidate text and decide formal adoption. Real-provider literary quality, cost, and production handoff remain an acceptance step requiring the collaborator's model credentials and budget.

## Known follow-up

- Adaptation chapter candidates now enter the existing Proposal/Revision transaction. `POST /works/{work_id}/proposals/{proposal_id}/accept` with `expected_version` creates an `adaptation-manuscript/1.0` revision after checking the source version and source digest. The stored candidate remains source-bound and records `formal: true` only after acceptance.
- UI source/plan/chapter review cards are not a new editor rebuild in this slice; the HTTP contracts are ready for the existing quiet workbench.
- Existing dirty files from the prior session were present before this branch. Review the focused diff before merging.

## Remote model smoke test

After the relay was repaired, `http://59.110.165.151:3000/v1` completed a real `gemini-3.8-flash` adaptation smoke test. The run covered connection testing, an ongoing two-chapter source import, plan approval, checkpointed analysis, chapter candidate generation, source references, open-thread preservation, Proposal creation, and formal Revision acceptance. The candidate contained 2 source references, 0 declared deviations, and 2 unresolved threads; it did not invent an ending. The accepted chapter was marked `formal: true` and retained its source-version binding. The key was used only through a temporary process environment and was not written to the repository or this handoff.

The adaptation collection endpoint now returns the work-scoped history at `GET /api/v1/works/{work_id}/adaptations`, newest first. The existing `?id=` lookup behavior remains available. This gives the web client a stable list without requiring task IDs up front.
