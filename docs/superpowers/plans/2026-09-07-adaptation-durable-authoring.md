# Durable adaptation → reviewed scene → production implementation plan

> Next multi-slice work, not implemented by the module-origin batch. Preserve the
> complete user-facing outcome; a queued endpoint alone does not close 02-005/02-007.

**Goal:** An ordinary user can import original prose, confirm source scope/mapping,
request recoverable chapter candidates, review them, and explicitly adopt them into
the ordinary scene manuscript/release pipeline without understanding internal APIs.

## Current evidence and constraints

- `writing/web/app.js` existing import dialog previews/stages TXT/DOCX/AAP and calls
  `handoffImportToAgent`, attaching the file and prefilling a manual chat request.
  It does not call source/adaptation APIs. Preserve AAP's existing separate workflow.
- `adaptation.py::run` currently computes source-only coverage locally; it does not
  perform a model analysis. Do not relabel coverage as semantic understanding or
  invent model calls for it. Its HTTP endpoint currently returns202 after finishing.
- `generate_chapter_candidate` performs the model request synchronously before the
  HTTP202 response. It already pins/checks source and adopted revision, validates
  exact quotes and marks a Proposal. It also already charges a logical attempted
  call after dispatch; do not reimplement the earlier refund correction blindly.
- Accepted proposals create `adaptation_manuscript` revisions, not the scene revisions
  consumed by releases. Existing accepted artifacts/frozen releases must not be
  rewritten or silently promoted as a migration side effect.
- Existing AgentDispatcher, agent runs/work items/attempts, cancel/retry UI and staged
  commit protocols are the durable execution boundary. Do not add raw ad-hoc threads.
- Standard director prompts/teacher/Sel contracts and 1.1 remain unchanged; no paid
  provider, user assets, main merge/push or release during development.

## Slice A — genuine durable chapter generation (02-005)

Files: `writing/src/halocue_writing/adaptation.py`, service workflow dispatch methods,
HTTP adaptation route, focused dispatcher/adaptation/API tests.

- [ ] Blocking synthetic provider test proves HTTP returns a durable job identity
      before provider completion. Job is visible in the ordinary task query after
      restart, not only in adaptation row status.
- [ ] Route chapter generation through the existing lease dispatcher with pinned
      source version/digest, approved plan digest, target/base revision, model config
      identity and logical budget reservation. Deduplicate same active request, allow
      an explicit distinct regeneration with a new execution identity.
- [ ] Fence candidate persistence against cancel, lost lease, source/plan/base changes
      and supersession; late response must never create a pending candidate anyway.
- [ ] Test restart while queued/running, explicit safe retry, timeout/provider failure,
      no double budget charge merely for queue admission and no refund after a real
      logical provider attempt. Preserve charged failure semantics already present.
- [ ] Record physical retries/unknown usage honestly; do not claim unified global
      accounting fixed unless tested against the separate05/06 findings.
- [ ] Keep cheap local coverage distinguishable from model generation; use truthful
      completed-vs-accepted response semantics and test compatibility consumers.

## Slice B — explicit adoption into the canonical 1.0 authoring path (02-007)

Files: adaptation proposal acceptance, scene manuscript/revision helpers and relevant
release/export adapters; focused proposal/source/release/integrated tests.

- [ ] A source-bound candidate remains nonformal and unpublishable until user approval.
- [ ] Show/validate target chapter/scene before adoption. Prefer safe creation of a
      dedicated scene rather than silently overwriting an unrelated existing scene.
      Pin existing target revision/version for any explicitly requested replacement.
- [ ] Adoption atomically creates/updates the normal scene manuscript revision with
      source refs and decision provenance, then schedules existing commit projections.
      Reuse authoritative scene/block parsing; no parallel canonical manuscript type.
- [ ] Prove accepted text survives work reload, normal scene-set freeze, release export
      and synthetic Production handoff with identical intended dialogue/source refs.
- [ ] Cover a second candidate after user edits, duplicate acceptance/concurrency,
      deleted target/source supersession, and old accepted adaptation artifacts.
      Existing old artifacts need an explicit visible promotion action, not auto-publish.

## Slice C — approachable source/adaptation UI and user guidance (02-007/07-011)

Files: existing writing import dialog, a focused controller/module if needed, bounded
HTML/CSS additions and real-DOM plus browser-flow tests. Use frontend-design skill.

- [ ] Prose entry uses preview/apply original source APIs, then chapter range/completion
      scope/character mapping review. Keep unfinished-source boundaries conspicuous.
      AAP import continues through its existing renderer-import path.
- [ ] Plan confirmation → chapter request → progress/cancel/retry → candidate review
      → target-aware explicit adoption → ordinary scene/release navigation all work.
      No automatic provider call merely from selecting/importing a file.
- [ ] Reload/reopen returns to current source, plan, job and proposal state. Do not rely
      on temporary DOM memory for the durable workflow or create duplicate requests.
- [ ] Show insufficient budget/config/input-length/stale-source failures with one clear
      next step. Keep technical IDs/hashes in details, not mandatory user input.
- [ ] Update manual/help only for controls that actually ship, and verify endpoint and
      button paths; no future-feature tutorial presented as existing functionality.

## Gates

TDD each demonstrated defect, independently reviewed bounded commits, focused tests
then fixed-source broad regression. SliceA alone leaves02-007 pending. Final closure
requires one synthetic browser/API-to-frozen-release-to-Production vertical trace,
not only fake state handlers or a collection of separately passing endpoint tests.
Unknown real literary/AA playback quality and provider behavior stay explicit.


## Slice A implementation record

6076ac0 implements durable queued chapter generation and local-coverage HTTP semantics.
Scoped review findings (simulation→real replacement, retry dedup race, recovery sibling
summary) are corrected.22 new cases plus existing broad suite:1832passed717.12s on
unchanged source. Physical usage/input limits remain separate incomplete findings;
no complete accounting claim. SliceB/C remain unimplemented. Detailed next plan:
`2026-09-07-adaptation-scene-adoption.md`. Handoff: durable-dispatch document.


## Slice B implementation record

45d000d connects accepted adaptations to ordinary scene revisions and normal release/
Production handoff. Legacy records remain immutable until explicit promotion.1846
unchanged-source regression tests pass. SliceC ordinary import UI remains pending;
see2026-09-07-adaptation-import-ui.md. This is not full02-007 closure.
