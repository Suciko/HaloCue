# Prose adaptation workbench —slice C implementation plan

> Next slice after canonical adoption broad verification. Follow frontend-design and
> TDD; user has authorized autonomous execution without intermediate design prompts.

**Goal:** The existing ordinary prose import entry reaches the actual source/plan/job/
proposal/scene pipeline. Reopening restores real server state. AAP keeps its separate
attachment/import workflow. Backend-only progress must not be presented as shipped UI.

## Design direction

Continue the current paper/ink/green editorial workbench—not a new theme or dashboard.
Use one roomy import/adaptation dialog with a compact progress rail (原文 / 计划 / 候选),
source scope in a quiet left summary, chapter/job rows in the main area, and one clear
primary next action. Mobile collapses columns and keeps actions usable; scroll is
within the dialog and paths/text wrap. Use existing fonts/tokens, honest status copy,
semantic labels, keyboard focus, Escape/close and reduced-motion defaults. Technical
IDs/hashes go in optional details. No decorative progress that implies model work.

## Ownership / files

- Add a focused `web/adaptation-workbench.js` controller, loaded as a local deferred
  script after app.js. Existing app.js import events call into it for TXT/DOCX only;
  preserve AAP routing and old controls. Keep one state owner for this workflow.
- Scoped CSS in existing stylesheet or one new self-hosted stylesheet; no network font,
  frontend dependency or app-wide rewrite. Use the existing api()/esc()/render/nav
  contracts via explicit small bridge; avoid copying the entire global work state.
- New real-DOM tests and one browser+loopback service vertical test. Read existing
  browser fixtures and static file serving before choosing scripts/fixtures.

## Real API facts that the UI must respect

- /imports/story:preview can inspect a file without a work. /works/{w}/source:preview
  and source:update require a work and base_version_id of the current source or null.
  Preview/apply generate different fresh IDs for new source versions/chapters; do not
  reuse transient preview chapter IDs for plan selection. Use the applied source IDs.
- Source modes are append or update-selected-chapters, not a fictional replace-all.
  Update requires selected old chapter IDs matching the incoming chapter count. Show
  server changes/diff before apply; stale previews require refresh and reconfirmation.
- Source save stores original input only, not formal scene text and not model output.
  Importing/selecting a file must never trigger a provider call by itself.
- Create adaptation → confirm plan_digest → optional local coverage (HTTP200, no model)
  → chapters/{id}/candidate:generate (HTTP202 with job/agent_run_id). The user explicitly
  requests generation after reviewing scope/mapping and current simulation/model mode.
- Existing get_work returns agent_runs with scope_id/policy/status/proposal; use those
  IDs to recover a reopened chapter's job state. GET agent-runs/{id} supplies progress/
  terminal result; cancel and retry use the existing endpoints. Do not assume pending
  job IDs exist only in sessionStorage. Reopen must not enqueue again.
- Candidate.target is a server-pinned default/mapped scene. Show target chapter and
  create/replace clearly. Current API does not accept arbitrary scene redirection;
  do not offer a dropdown that silently changes target after generation.
- Accept proposal with current expected work version creates a normal scene revision.
  Old pending candidates require explicit target confirmation; old accepted artifacts
  use manuscript:promote with expected_revision_id and explicit owned target chapter.
- Missing target in old job snapshots is nonretryable; offer fresh generation, not an
  endless retry button. Input/model drift and budget exhaustion need accurate actions.
- Normal review/freeze still requires brief and story direction. A new-work wizard
  should explicitly help the author establish those prerequisites or navigate to the
  existing controls; never fabricate the artifacts or bypass the gates. Any model
  blueprint generation remains a separate disclosed author action.

## Implementation / acceptance sequence

- [ ] RED: ordinary TXT/DOCX import currently calls attachment/manual-chat flow; test
      new choice/default source workflow and unchanged AAP behavior.
- [ ] Inspect/display preview, explicit source apply with correct base/digest, stable
      saved chapter selection, unfinished/provided-scope labels and bounded call budget.
- [ ] Create/confirm real plan; display current provider/simulation boundary; model
      call happens only after explicit per-chapter generation action.
- [ ] Poll real run status; disable duplicate submission; cancellation/retry/error
      branches; close/reopen/page reload restore from server state.
- [ ] Show candidate text, quote refs, deviations/open threads and target placement;
      explicit acceptance navigates to normal scene editor. Legacy promotion reachable.
- [ ] Do not overwrite unsaved scene edits or switch work based on late responses.
      Fence in-flight UI responses by work/selection revision; escape filenames/content.
- [ ] Ordinary brief/direction/readiness controls remain discoverable. Show next-step
      review/release navigation only when its actual prerequisites are available.
- [ ] Visual QA at desktop and narrow viewport plus keyboard/focus/close behavior;
      one rendered screenshot per meaningful size, not only source-string assertions.
- [ ] Browser+synthetic APIs prove import→save source→confirm plan→queued fake model→
      review→adopt→ordinary scene→normal review/freeze→Production handoff. No real paid
      provider, user assets or actual AA execution. Preserve all source/proposal IDs.
- [ ] Focused existing import/settings/Agent/teacher/Sel/UI suites, scoped review, then
      immutable-source broad regression and truthful user docs/help updates.

No main merge/push/release or1.1 edits. Global physical usage/cost accounting, input
bounds and background knowledge authorization remain separate unresolved findings.
