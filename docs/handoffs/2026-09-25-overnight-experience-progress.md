# Overnight product experience — progress checkpoint (2026-09-25)

## Scope / authority
- Kind: handoff; status: active implementation, NOT complete, not published.
- User explicitly requested an ongoing goal for the product rework plan, detailed UI polish and real official-character reference import.
- Plan: `docs/product-experience-rework-plan.md`. Product positioning and Proposal/Revision/ScriptRelease invariants unchanged.
- Branch: `codex/1.0-release-readiness-20260914`; inherited HEAD `e617f9bf`; 181 dirty entries before goal work. No reset/clean, commit, push, deployment or paid model call.
- No new GitHub Issue/PR created yet. Do not package the inherited dirty worktree into a generic UI commit.
- Previous goal turn was progress: persisted reference import, baseline snapshot, shared chrome/default fixes. This continuation is also progress: grouped references, activity, media UI and recovery plus regression evidence.

## Recovery / live local state
- Before changes, 196 source/test files were copied to a maintainer-local checkpoint outside the repository under `<workspace>/04-user-data/dev-checkpoints/overnight-experience-baseline`. It contains manifest hashes and changed-paths-current.json (refresh if more files change). It excludes new files and integrated tests, so use focused review for those.
- Original port 8765 is a disposable fake writing fixture. Never import durable user material into it. It remains running, untouched.
- Persistent integrated source-checkout runtime is live on port 7179. It uses the desktop's real LocalAppData/HaloCue/integrated/{writing,production} directories, not source .halocue and not the temporary fixture.
- Startup script/config/status are maintainer-local under `<workspace>/04-user-data/HaloCue-UserData/runtime/`; script `start-experience-runtime.py`, config `experience-runtime.json`, status `experience-runtime-status.json`. Uses existing full services and explicit corpus directory. Exec session 83805 originally owns it; verify process/listener before starting another.
- In-app browser referencePreview is tab 12, currently on the actual imported reference library. Marked deliverable. Main user tab is separate. Viewport reset. Extra temporary tabs may already have been cleaned up; do not reuse missing tab 11.
- No runtime package or desktop executable rebuilt. Current code edits are visible in the integrated source runtime; do not claim installed binaries upgraded.

## Actual reference import (completed bounded subtask)
- Found 31 existing maintainer-local BA character JSON profiles in the external ba-writing Skill knowledge/characters directory. These are curated interpretations referencing official story material, NOT publisher-issued character-card files.
- Found original local scenario corpus: 3 JSONL shards, 368032 records. All three file hashes matched the existing extraction manifest. Verified only the manifest relationship, not external authenticity of all claims.
- Ran the shipping parse_import_payload validator. 28 PASS; 3 FAIL: 圣园未花 (insufficient bidirectional sequences), 桐藤渚 and 陆八魔爱露 (missing ooc and sequence coverage). No made-up samples, no weaker validator, source files unchanged.
- Matched individual normalized lines against zh_cn within their declared source group; evidence report retains matched record_uid and misses. This does NOT establish personality-analysis correctness or sequence contiguity. Missing samples remain unverified; no wholesale local_exact upgrade.
- Backed up the actual desktop writing DB via SQLite backup plus artifact directories before import. Imported through WritingService.import_character_card, into a NEW independent work titled BA 原作人物参考库 (ID work-3c40d9c813ae). 28 original profiles preserved along with original/cleaned JSON, source hashes, and validation reports. Imports assert created (not updated); identity-overlap guard present.
- Reopened via another WritingService and later actual integrated UI: 28 cards persist, each retains ba_profile. Work version 29. Prior work work-6076b239df82 remains title 未命名作品/version 2, matching pre-import backup.
- Source-checkpoint files: character-validation.json and character-source-audit.json. Import receipt/backups under `<workspace>/04-user-data/HaloCue-UserData/backups/official-character-import-20260925/`. Do not copy original profiles/corpus into public repo.
- Default supported import marks a card confirmed for use. This means user-authorized imported reference, not verified official truth; source description explicitly distinguishes curated reference and partial line matches. UI now exposes that distinction and raw profile evidence.

## Implemented UI / logic
### Shared chrome
- Added writing/web/app-chrome.js; moved existing nav icon enhancement out of ideation-only agent-workspace.js. One idempotent route hook owns nav icons for every workspace.
- Existing chrome styles in authoring-ui.css promoted from works/writing-only to global; no additional competing full theme file. Removed non-works icon suppression in agent-workspace.css.
- Fixed new custom character default: blank draft uses source_type custom, explicitly imported official draft unchanged.
- Upload starts in current catalog type; syncCustomAssetFields shows/enables only relevant fields, correct extension filter, character identifier required only for character.
- Background counter initially separated running/waiting/fail/history; now counts combined deduplicated work items and conversation runs.

### References
- Four navigation groups: 人物 / 世界与规则 / 剧情记录 / 参考文件; retain all 11 existing view IDs and direct URLs, current group opens automatically; pending review separate.
- Mobile dropdown exposes all the same routes when desktop rail is hidden. Removed duplicate legacy mobile library-nav from view.
- Empty library offers manual new character/import and optional assistant discussion. New-character control routes to characters from overview.
- Missing-corpus warning only appears in official search, not all reference pages. Source-dependent controls remain gated.
- Fixed inherited empty editor grid column: full-width character list until editor opened. Readable two-line role summaries (not merely first self-pronoun voice anchor), neutral badges/avatars and controls, scoped responsive editor/detail styles.
- Added recursive escaped characterReferenceDetailsMarkup to show imported full profile, note, source/validation, speech and examples in disclosures. Labels acknowledge that passing schema is not official fact certification; external_unverified retained. Main formal edit fields remain existing semantics.
- commitRoute resets foreign inspector state only when entering works/writing from a different workspace. Same-workspace context changes preserved; fixes ideation decision panel leaking into manuscript.

### Responsive root
- Discovered live 390px reference page main width ~133px: desktop named-grid tracks remained despite mobile single-column declaration.
- Final mobile root grid rule in redesign.css now applies to every surface, not only writing. Main/areas/rows reset together. Tests cover four surfaces and four persisted collapse combinations.
- Actual reference page after fix: main 390px and no horizontal overflow. Mobile scoped padding restored (legacy important rule originally zeroed it).

### Activity
- Task utility moved below nav spacer and relabeled 活动 (old section=tasks preserved). Main architecture still not fully reorganized; see remaining work.
- writingActivityItems projects work items + unlinked Agent runs, avoids linked duplicates, sorts by actual created_at newest first. Agent waiting-user without a pending proposal is described as awaiting input, not a ready candidate.
- Filters 运行中 / 待处理 / 历史 / 全部, manual refresh, contextual links to source conversation/scene. Completed history not counted as running. Conversation recovery requires an explicit retry/redirect link, not merely a later unrelated success.
- Adds read-only production jobs from existing /production/api/v1/jobs, clearly marked local-machine/cross-work. Links back to associated production project for original supported actions; no new execution/retry endpoint or state machine.
- Source errors retain writing activity; refresh race avoids replacing a newer work version. No automatic model calls.

### Media library
- Role category called 角色素材 to distinguish from narrative character cards.
- Compact type filter buttons; optional folded explanation instead of large colored permanent boundary banner; calmer empty/preview states and consistent typography/theme tokens.
- Builtin preview offered only when preview_available true. Custom character preview labeled package image / not animation. Custom media gains explicit preview button; missing thumbnail handled by delegated error listener, not inline JS.
- 用于制作… opens existing attach flow. Explicit empty required project choice prevents accidental attachment to the first project. Copy-original boundary remains clear.
- Supported formats unchanged. No real file upload or media mutation this turn.

### Production recovery
- production-embed.js now installs a tiny scoped recovery stylesheet BEFORE upstream HTML/CSS can arrive. Failed fetch no longer leaves raw browser-default text/buttons.
- Error page offers retry, return to writing, environment settings; technical error folded. Existing data and permission/Gate paths unchanged.

## Files changed in goal work
Existing source: writing/web/app.js, authoring-ui.css, index.html, agent-workspace.js/css, redesign.css, production-embed.js.
New source: writing/web/app-chrome.js.
New tests: test_shared_chrome_and_library_defaults.py, test_reference_details_ui.py, test_activity_workspace.py, test_asset_library_polish.py, test_production_recovery_surface.py.
Existing tests: test_writing_responsive_shell.py expanded; integrated/tests/test_production_navigation.py scene send selector now excludes cross-form save button introduced in prior UI work.
No backend source modifications in this checkpoint; durable import uses existing supported backend API/service.

## Test evidence
- Shared/default tests initially 12 passed; expanded to 24 passed.
- Scene/detail/entry/shared group: 44 passed.
- Character import suite: 12 passed.
- Activity tests latest: 4 passed (includes actual timestamp order and explicit retry-link semantics).
- Asset polish latest: 5 passed; asset source contract: 3 passed.
- Production recovery + production UI architecture: 28 passed.
- Responsive shell: 16 passed.
- Integrated navigation full first run: 21 passed/2 failures due to ambiguous old send locator matching cross-form save button. Corrected locator to :not([form]); targeted rerun passed. Final full run: 23 passed in 115.16s.
- Combined current feature/safety run: 125 passed in 86.94s:
  python -m pytest services/halocue/writing/tests/test_shared_chrome_and_library_defaults.py services/halocue/writing/tests/test_reference_details_ui.py services/halocue/writing/tests/test_activity_workspace.py services/halocue/writing/tests/test_asset_library_polish.py services/halocue/writing/tests/test_production_recovery_surface.py services/halocue/writing/tests/test_writing_responsive_shell.py services/halocue/writing/tests/test_topbar_manuscript_save.py services/halocue/writing/tests/test_scene_composer_polish.py services/halocue/writing/tests/test_change_review_ui.py services/halocue/writing/tests/test_character_card_import.py services/halocue/writing/tests/test_asset_catalog_ui.py services/halocue/production/tests/test_ui_information_architecture.py -q
  Afterwards activity chronological/retry correction ran 4 passed (the combined run included 3 older activity cases).
- agent_main_surface.test.cjs: 12 passed.
- node --check app.js, app-chrome.js, agent-workspace.js, production-embed.js passed. Ruff new tests passed after format. Scoped git diff --check passed.
- Actual internal-browser evidence: real 28-card library, search and opened full profile, desktop and mobile library layout, activity filters, media empty state and role-specific upload form. No submitted edits, no model send, viewport reset.

## Requirement checkpoint — keep goal ACTIVE
Completed bounded portions: real-source import with persistence/provenance, shared nav icon/header, character defaults, category-following upload, grouped reference navigation, activity projection and filters, mobile root bug, recovery surface.
Still incomplete or insufficiently proven:
1. Full planned navigation (作品 / 创作 with internal views / 制作 / 素材) is NOT implemented; current top-level construct/write/reference routes remain. Activity was demoted only. Need a real project-first entry and shared internal creation navigation, not claim existing chrome equals full information-architecture rewrite.
2. Creation/outline/manuscript empty routes and first-use manual creation need full user journey, not just unit fixtures.
3. Production source-to-frozen-script and missing-Gate checklist UX needs redesign/verification; no changes to Gate policy permitted.
4. Detailed production loaded UI and settings/help presentation still need coherent polish; only failure surface done here.
5. Activity ongoing polling/durable interrupted-job behavior and cross-surface drafts need full integration coverage; current production refresh is manual/initial.
6. Real resource-heavy media preview/performance and full synthetic save -> proposal -> partial adoption -> production handoff need current-tree end-to-end evidence. No actual AA compilation/install tested.
7. Full light/dark five-size matrix and whole release regressions remain, plus cleanup of legacy source-string tests separately from real failures.
8. Source-preserving reuse of imported reference library in another work must be discoverable; existing imports are intentionally independent, not silently injected into every work.
9. Goal completion must use the original objective and plan's required first-night scope; do not mark complete based on partial counts/green checks.

## Next concrete work
Inspect current router/HC_SECTIONS/renderAppLayout/renderWorkspace and implement the project-first navigation slice with old-route aliases and unsaved guards intact. Keep global media separate from work-owned reference facts. Then production handoff/source/missing-input review UX and full integrated journey. Before rerunning real-data setup, check live 7179 listener and persisted receipt; never repeat import into a second work or overwrite existing cards.


## Continued slice — project entry and frozen-source recovery

Implemented after the previous checkpoint, on the same dirty branch (no commit/push):
- Added real `section=projects` entry with a read-only list from existing `/works`, current live work metadata, explicit construct/outline/manuscript/reference destinations, list refresh and honest failure state. Root without a work deep-link now opens projects. `section=works` remains ideation; legacy `?work_id=...` still opens that work's ideation. Projects URL does not pretend to belong to the most recently loaded work.
- Brand returns to projects. Added desktop/mobile project entry; mobile remains five root destinations and puts references in More. Grouped references with creation, production with media. Hidden work-save/model/version/activity badges on the global project list because they misleadingly described one loaded work.
- New local first-work form now actually renders from project/empty-ideation entry; cancel and create were exercised with isolated data. This was a dormant form path, not an AI generation feature. Existing new-work dialog for users with a work remains intact.
- `openProject` handles explicit destinations through existing `loadWork`/router. Keeps manuscript-save guard, preserves same-work work-switch behavior, checks unsaved chapter arrangement before changing works. Exported as router `openWork` for the embedded source handoff; no wire schema changes.
- Compact sidebar spacing corrected after real 820/1280 x 520 regression caught utilities being pushed below the window. Desktop hit areas remain readable; mobile controls remain 44px.
- Production with no frozen source now explains Save manuscript → handle review → freeze release, and links to the selected work's release-review route. It does not freeze, generate, or install on navigation. No gate policy changed.
- Production failed per-work reads no longer masquerade as an empty release library. Partial failures identify unread work count; refresh can recover. Main writing-service failure is no longer labelled standalone mode. Removed user-facing historical implementation label “对齐 0.95 制作链路”.

Files touched in this continuation:
- `services/halocue/writing/web/app.js`, `index.html`, `app-chrome.js`, `redesign.css`, `authoring-ui.css`
- `services/halocue/production/ui/app.js`, `app.css`, `index.html`
- `services/halocue/integrated/tests/test_production_navigation.py` (new integration cases; old first-use-specific test now explicitly visits ideation rather than the new root)
- new `services/halocue/writing/tests/test_project_entry_navigation.py`

Validation checkpoint:
- New project integration: 3 passed; includes five planned sizes x light/dark, long titles, route switching, refresh, local creation/cancel, and no model calls.
- Shared integrated/responsive/chrome run: 64 passed, 2 genuine short-window sidebar failures; compact spacing fixed, targeted short-window + project run 5 passed.
- Production missing-release / failed-read recovery: 2 passed. First failed-read test setup initially intercepted after speculative preload; fixed test to explicitly refresh under injected failure and verify recovery. Production navigation issues were not bypassed.
- New project helper/guard suite: 9 passed; verifies text escaping, current metadata, dirty manuscript guards for every destination, cancelled structure navigation, release handoff.
- New helper test Ruff format/check, JS syntax checks for both app scripts and shared chrome, scoped tracked diff-check passed.
- Combined expanded regression run is pending at checkpoint write; see next appended result before reporting totals.
- Internal browser checked actual project list on persistent runtime, direct reference navigation, actual production empty-source recovery, desktop 820x520 and mobile 390x844 screenshots. No persistent manuscript edits/model calls. Viewport reset. Tab 13 is project-center preview; tab 12 remains the real 28-card reference library. User tab 8 (8765 disposable fixture) was not touched.

Remaining scope is still significant; keep the goal ACTIVE:
1. Project entry is real now, but root navigation still exposes construct/write/reference. Full shared creation subnavigation is not implemented; do not claim finished architecture.
2. End-to-end manual outline/manuscript + proposal partial adoption + release/production remains to be run with synthetic data.
3. Full populated production gate checklist/layout, settings/help polish, and continuous activities remain beyond the new source-empty recovery.
4. Imported curated official-source reference profiles remain in their independent reference work; source-preserving reuse by another work is still not implemented. Do not inject into all works or strip provenance.
5. Broad full-repo release regression and all surfaces x five-size/two-theme matrix remain. This continuation only proves that matrix for projects plus previous scoped responsive suites.

### Final result for the continued slice
- Expanded combined command (the earlier 13 feature/safety suites plus integrated navigation) finished: **154 passed in 231.86s**. Includes the fixed short-window cases and both production recovery cases.
- Additional project helper/guard suite: **9 passed**. Do not add these to the prior 125 result as if it were an independent current run; the 154 supersedes overlapping earlier suites.
- Persistent real source work remains version 29 / 28 cards; original user work remains version 2. No new user work/manuscript was created during browser checks. Test creation used temporary IntegratedRuntime data only.
- Next suggested vertical slice: consolidate creation navigation without removing old routes, then add source-preserving reference reuse through the supported import/export boundary; audit the import contract before choosing that implementation. Follow with populated production gate UX and full synthetic handoff.


## Continued slice — consolidated creation navigation and character reuse

Previous goal turn classification: substantive progress, not a wait/no-progress turn.
This slice remains on the same dirty branch; no commit, push, installation or release.

### Shipped in source and persistent preview
- Consolidated primary rail into Projects / Creation / AA Production / Media,
  with Activity/Feedback/Help/Settings utilities. Removed the former independent
  global writing/reference entries rather than hiding a second redundant nav.
- Added one work-owned creation view switcher: ideation / outline / manuscript /
  references / release review. Desktop has explicit text buttons; <=1200 uses a
  labelled native select. Mobile keeps five global destinations.
- Legacy `section=works|writing|references` URLs still render their genuine
  workspaces. Returning through global Creation remembers the last creation
  view; changing work resets scope safely. Existing navigation/manuscript guards
  handle the new view switcher; a blocked select returns to the actual view.
- Added `POST /api/v1/works/{id}/character-cards:reuse` in the writing context.
  Implementation is isolated in `character_reuse.py` behind the existing service
  operation boundary. See `docs/architecture/character-card-reuse.md`.
- New picker in Characters → Add → From another work. Explicit source work and
  character selection, search, visible target, same-name/alias duplicate hints,
  cancel/Escape, single in-flight submit, source/target version-conflict refresh.
- Reuse creates an independent target card, unverified by default. Preserves
  full profile, sample evidence statuses, validation report, source refs/hash,
  and copied original/cleaned bytes checked against hashes. Source work stays
  unchanged. Name/alias collision, stale source or target, archive, missing or
  mismatched source bytes fail rather than overwrite. Source-work relationship
  IDs do not silently bind to target characters.
- Existing character edit/adoption form was dropping import metadata and
  flattening structured source refs to `[object Object]`. It now retains the
  metadata and structured refs, exposes only text refs as editable text, and
  preserves source data in copy-as-custom form drafts too.
- Actual 28-card picker revealed a fieldset/legacy label CSS overflow missed by
  the initial two-card fixture. Changed to an explicit radiogroup scroll region,
  row-oriented labels, two-line summaries; footer remains outside scroll region.
  Expanded integrated fixture to 12 cards with long descriptions and explicit
  list/footer overflow assertions.

New files:
- `services/halocue/writing/src/halocue_writing/character_reuse.py`
- `services/halocue/writing/web/character-reuse.js`
- `services/halocue/writing/tests/test_character_card_reuse.py`
- `docs/architecture/character-card-reuse.md`
Changed existing slice files: writing service/app endpoints, app.js/index.html/
  authoring-ui.css, integrated test_production_navigation.py.

### Verified results
- Consolidated creation navigation matrix + prior shared/nav/topbar targeted
  regression: 5 passed. New matrix covers all five creation views, all five
  planned sizes, both themes, same-work scope and no navigation POST/model calls.
- Reuse service suite: 9 passed (persistence, provenance/bytes, stale/duplicate/
  archive/missing/hash rejection, relationship IDs).
- Imported card + reuse + detail + project guard group: 33 passed.
- Expanded combined feature/safety suites: **176 passed in 259.11s**. This
  supersedes overlapping earlier combined counts, not 176 additional features.
- Later long-list desktop/mobile reuse → explicit-adoption regression: 2 passed.
- Later source/target concurrent-change UI refresh: 2 passed.
- Cache-prefix/freshness + writing vertical service slices:
  `python -m pytest services/halocue/writing/tests/test_discussion_prompt_cache_layout.py services/halocue/writing/tests/test_vertical_slice.py -q`
  → **104 passed in 64.65s**. Simulated/local tests, not a real provider cache
  hit-rate or pricing measurement and not full browser release-to-production.
- Final integrated navigation + reuse service + project guard run pending below;
  append its result before claiming this slice's final regression.

### Runtime and real data
- Verified old owned exec session 83805 alive, inspected durable state: no
  running generation, both Agent records waiting_user, production jobs empty.
  Stopped that session and restarted its same external runtime launcher with
  explicit port 7179. New live owning exec session: **66999**. Check it before
  any future restart; do not run two integrated runtimes on the same data.
- External launcher config now preserves port 7179. URL remains stable. This
  is source-preview runtime, not a rebuilt installed executable.
- New reuse endpoint is live: invalid empty request returns validation_error
  400 before mutation, not 404. Real data checked after restart: reference work
  v29 with 28 cards, original work v2. No real card was copied/adopted during UI
  QA; all mutations used temporary synthetic integrated-test databases.
- Internal browser tab13 inspected actual 28-card selection and cancelled;
  left at project center. Tab12 remains the existing reference-library page;
  user tab8 (disposable8765) untouched. No active viewport override.

### Requirement checkpoint — keep goal ACTIVE
Completed now: real project-first entry and shared internal creation navigation;
source-preserving reuse of the imported reference work; first-work local create;
source-empty production handoff recovery; previous chrome/library/media slices.
Still required/insufficiently verified:
1. Full synthetic browser journey manual outline → manuscript/save → proposal →
   partial adoption → review/freeze → production handoff; service tests do not
   substitute for this user-facing journey.
2. Activity automatic refresh/late-response handling (currently initial/manual),
   cross-route drafts and recovery need full integration coverage.
3. Populated production missing-input/review checklist and settings/help polish;
   source-empty recovery alone is not complete production UX.
4. All relevant surfaces, not only project/creation entry, in full light/dark and
   five-size matrix; broad current-tree release regression and final scope audit.
5. Real AA install/compile, heavy assets, paid models remain outside unsolicited
   validation. Do not use this as an excuse to skip deterministic synthetic paths.


## Continued slice — scoped live activity refresh and final picker race repair

### Previous run reconciliation
- The previous final integrated/reuse/project run finished **50 passed, 2 failed**:
  one Chromium `ERR_UNSAFE_PORT` from an OS-assigned port 6668 (no safety bypass),
  and one real picker refresh/selection race. The latter is fixed: controls stay
  disabled while either source or target refreshes; old choices cannot be
  selected during the request. Search also clears a choice it hides.
- Targeted conflict/sidebar rerun (exec42583): **6 passed, 28 deselected**.
- Further activity/reuse group after final picker edits (exec26824):
  **12 passed, 53 deselected in 51.47s**. Includes desktop/mobile long-list reuse,
  source/target conflicts, activity projections and real integrated refresh.
- Browser override was reset; tab13 marked for continued handoff. Persistent
  preview runtime remains the existing exec66999 on7179; no restart/import.

### Activity refresh implementation
- New `writing/web/activity-refresh.js` is a small read-only scheduler, consumed
  by app.js. Five-second visible activity-page refresh, slower error retry,
  request timeout, one in-flight read, abort/epoch invalidation on work/route
  changes and tab hiding. No poll outside the activity page.
- Work reads unwrap the writing API envelope and refuse an older work version.
  Same-version task changes still update (job state is not always work-versioned).
- Production failure preserves last successful rows and explicitly labels them
  stale; writing failure does not hide production activity. Reconnect remains
  manual as well. No automatic retry of a job, adoption or model call.
- Only changed results rerender the task surface. Expanded details, focused
  actions and scroll are retained. Applying results defers while a dialog,
  selection, composition, command or pointer interaction is in progress.
- Minimal inline copy explains automatic read refresh without permanent toast
  spam. Browser tab13 visually checked at normal desktop dimensions, dark theme.
- Tests added: node scheduler cases (scope/cancellation/deduplication/timeout/
  backoff), plus integrated desktop/mobile real-router cases verifying running
  → waiting/completed updates, focused expanded details, offline stale records,
  recovery and stopped polling after route exit. Synthetic transport only;
  actual background jobs/model outputs are not fabricated in user data.
- The first integration attempt had 9 passed/2 failed only because it counted
  pre-existing startup feedback-sync POST as an activity mutation; recording
  now starts after startup. Corrected targeted run is recorded above.
- JS syntax: app.js, character-reuse.js, activity-refresh.js passed. Scoped
  tracked git diff-check and Ruff activity test check passed.

### In progress, NOT complete
- New synthetic full browser journey now exercises actual manual chapter/scene,
  manuscript save, conversational rewrite proposal, selective acceptance,
  reviews/freeze and production handoff. Still being debugged/validated; do not
  claim passed until an explicit result is appended.
- Remaining overnight acceptance items from previous checkpoint still apply.


### Browser journey now verified (supersedes in-progress note above)
- The real integrated browser journey passed at **1440/light and390/dark**:
  manual chapter creation → scene creation → hover/touch paragraph insertion →
  three hand-written blocks saved → conversation instruction sent → two-change
  rewrite proposal generated → only first change selected/applied → scene review
  → explicit user memory skip → continuity review → release review → freeze →
  production handoff. **2 passed in20.74s** (exec39198).
- Setup uses service-created confirmed direction and synthetic character cards;
  it does not claim browser testing of initial idea/direction approval or real
  provider quality. No acceptance/review/Gate result is mocked: only provider
  output/rule inputs are synthetic, and all actual formal mutations after setup
  happen through UI/HTTP. It asserts the unchanged original revision before
  acceptance, partial-accept provenance, rejected second change absent, and the
  final production run's upstream release ID.
- Initial test-development failures were selector/order mistakes, not fixes to
  product gates: the new chapter is already selected; desktop paragraph insertion
  is deliberately hover-revealed; proposal requires an initial discussion; scene
  review must complete before the explicit memory decision; the production embed
  also owns a separate toast, so use the writing toast's aria-live scope.
- Full integrated navigation suite: **38 passed in225.53s** (exec45960).
- Shared chrome/activity projection/reuse service/project guard group:
  **47 passed in40.57s** (exec10121).
- Final same-version late-response protection added: activity reads capture the
  current work object; a response cannot regress a separate intervening refresh
  even when durable work.version is unchanged. New adapter tests cover equal/
  higher version interference and active dialogs. Activity suite now **8 passed
  in7.22s**. Version/activity header counters update with the projection too.
- A final targeted activity+journey run after this last guard is underway:
  exec15213; append its result and syntax/lint results before final handoff.
- Durable recheck via7179: reference work v29 /28 character artifacts; original
  work v2 /0 cards; production jobs empty. No real project changed by these tests.
- Browser tab13 now at the real project center, normal viewport, handoff-marked;
  tab12 reference library deliverable-marked. Runtime remains exec66999.

### Remaining goal work (keep ACTIVE)
1. Populated production missing-input/review checklist, settings/help detail
   polish; existing source-empty recovery does not replace these surfaces.
2. Full relevant surface matrix in five planned sizes and both themes. Entry/
   creation matrix and representative activity/journey desktop/mobile tests are
   done, but they are not a full assets/production/dialog matrix.
3. Old-draft import and cross-route unsent text/save-failure recovery browser
   paths beyond the existing guarded-unit/service coverage; inspect existing
   tests before adding duplicates.
4. Broad current-tree release regression and final scope audit; preserve all
   inherited uncommitted changes. No merge/build/install/paid models assumed.


### Final verification for this continuation
- exec15213 completed: targeted real integrated activity + complete journey
  **4 passed,34 deselected in48.34s**, after the final same-version guard.
- `node --check` app.js and activity-refresh.js: passed.
- Ruff integrated navigation + activity workspace tests: passed.
- Scoped tracked `git diff --check`: passed. New controller/CJS files were
  syntax/execution checked separately (untracked files are not in git diff).
- No test session from this continuation remains running. Do not stop the
  persistent preview exec66999. Goal intentionally remains ACTIVE.


## Continued slice — production readiness, complete surface matrix, help accuracy

### Implemented
- Source-empty production includes actual file/manual source shortcuts instead
  of only referring to tabs. Delegated listeners survive async release-list
  rerenders; focus goes to selected source tab. No task/model is created. Initial
  attempted listener binding was caught in inspection and replaced with delegation.
- Production review has one next-action button plus collapsed “交付前检查”. It
  reads actual compile/install gates, explains pending cards, diagnostics, frozen
  index missing/incomplete, compiler/workspace configuration, missing/stale builds.
  Actions only locate a card or open existing environment settings. No gate,
  confirmation, installation or compilation is bypassed. Expanded state survives
  card selection. Exact production source IDs remain internal.
- Settings model pane explains manual use without a real model and distinguishes
  local simulation. Does NOT promise unrestricted freezing without review.
- Help content was materially stale: said partial acceptance did not exist and
  confused writing Proposal/ScriptRelease with production card review. Updated
  core start/writing/revision/review pages, added work-owned references and
  activity sections, updated source/reuse boundaries and actual navigation.
  Both existing packaged static/help and legacy_help bundles remain synchronized.
- Visual screenshots exposed a real dark-mode help defect: white header with
  light text, light iframe inside dark app. Embedded help now observes parent
  theme/appearance, uses its colors/fonts, disconnects the observer on pagehide;
  standalone theme preference unchanged. Help header/iframe use app tokens and
  hidden loading/error/frame states cannot reserve layout. Error copy offers
  user actions, not internal directory names.

### Validation
- Support matrix: activity, assets, populated missing-mapping production and
  actual pending-review production, all five sizes × light/dark. Includes all
  five settings tabs plus help at each size. Uses temporary work/run DBs and
  synthetic text; no real material or paid model. Populated review uses an
  explicit synthetic narrator mapping rather than bypassing stage gates.
- Checklist buttons tested: pending card focus, expanded state retained,
  environment dialog opens, compile stays disabled. Source shortcuts tested
  after release list refresh in both healthy/read-failed recovery paths:
  **2 passed,36 deselected in8.83s**.
- Latest surface matrix after help content and dark fixes: **2 passed in37.55s**
  (exec24124). Each test loops many surfaces/sizes, not merely two screenshots.
  Prior matrix31.85s/33.70s/32.70s runs superseded by this one.
- Screenshots manually inspected: review dark390, settings model dark390 and
  fixed help dark390. Maintainer-local screenshots are temporary under latest
  pytest output; copy needed evidence before pytest cleanup.
- New actual browser safety journey: dirty hand manuscript → blocked navigation
  → cancel guard → unsent assistant instruction → simulated503 save failure →
  retry save → references and return → another work and return. Asserts no
  send/generate requests, exactly two save attempts, other work unchanged, both
  drafts retained. **2 passed,38 deselected in10.45s** (exec66201) desktop/mobile.
  Initial attempts needed native mobile Agent-tab selectors, not hidden desktop
  buttons; production code did not change for those test-selector failures.
- Production information architecture/direction profile plus activity/shared
  chrome group **86 passed in54.62s** before later checklist/help additions.
  Follow-up static production tests28 passed; one later checklist test added.
- Runtime fixture moved from test_production_navigation.py to integrated
  tests/conftest.py so combined root-level collection works. First full-suite
  attempt failed import of the sibling test module; fixed shared fixture, no
  test skip. Ruff touched new tests passed after import cleanup.

### Current running broad regression — DO NOT duplicate
`python -m pytest services/halocue/writing/tests services/halocue/production/tests services/halocue/integrated/tests -q --tb=short`
- Live exec session **36038**. Last observed >81%, several failures shown.
  Poll and inspect final summary; do not claim all green. Initial failure cache
  contains older failures too, so do not treat cache alone as this run result.
- Source/test edits made while this long run was active need final focused
  reruns; Python modules can already be collected before edits.
- Persistent actual preview still exec66999, port7179. No restart needed for
  static sources; actual original work/reference work unchanged at last check.
- Browser projectPreview tab13 currently production source, manual tab (empty;
  no submitted task); referencePreview tab12 retained. No viewport override.

### Remaining before goal completion
1. Triage broad test failures with exact evidence; correct changes in scope,
   separate pre-existing failures instead of deleting assertions or claiming green.
2. Reuse existing integrated old-prose import browser journey; confirm its current
   selectors align with new project-first landing and fix tests/UI as warranted.
3. Final scoped regression, source/data/receipt audit, concise Chinese completion
   report distinguishing real28-card reference import from publisher-issued cards.
4. Goal remains ACTIVE until this is done. No install/publish/paid tests.


## Final overnight acceptance — bounded goal delivered

Authoritative delivery: `docs/product-experience-delivery-2026-09-25.md`.

### Broad regression findings and honest disposition
- Full writing/production/integrated suites finished **1836 passed,18 failed in
  1454.57s**. We did not rerun all1854 after repairs or claim all green.
- Re-ran13 failing writing static assertions against the pre-goal backup sources:
  **12 failed,1 passed**. Logs outside repo under maintainer-local checkpoint
  `overnight-experience-evidence/baseline-static-regression.txt`. The12 failures
  are reproducibly pre-existing source-string expectations. Left them intact,
  not skipped, deleted or satisfied with compatibility-only comments.
- The one changed-resource-version assertion now validates the script resource
  rather than pinning an old cache-buster. Other failures: mobile background
  test needed to expand actual “更多筛选条件”; first-work import test now enters
  Creation from the new project landing; two production tests imported the wrong
  context's `test_http_api` in combined runs, fixed with qualified module imports.
- Mobile manuscript test exposed a real background-render interruption. Added
  scoped active block/field/caret capture and restore, only for same dirty scene.
  New regression confirms another scene does not inherit it. 7 relevant mixed
  tests passed, including both desktop/mobile complete journeys.
- Final broad scoped run: **267 passed,2 failed in474.82s**; both failures were
  the above wrong test-helper imports. After fix, mixed writing/production
  regression **18 passed in9.77s**.

### Later discovered import consistency race (fixed, not test-masked)
- Combined matrix/import runs intermittently ended “waiting to generate” after
  exactly one successful provider call. Instrumented DOM: completed run and
  pre-commit plan were being combined from parallel HTTP reads; no running state
  remained to poll. Not solved by extending timeout or clicking generate again.
- `adaptation-workbench.js.reload` now reads work/run first, then source/plan/
  capabilities. If work observes running it keeps polling; if work observes
  completion, later plan reads include the committed candidate. Existing epoch
  checks still prevent stale polls overwriting user acceptance.
- Added deterministic deferred-response DOM regression and updated late-poll
  test to reflect serial first read. Import/controller group18 passed.
- **Final combined acceptance85 passed in84.07s**, including full support matrix,
  TXT/DOCX and first-work import, adaptation race tests, activity, active-editor
  focus, production source/gate navigation and background matching/picker.
  Log: maintainer-local `overnight-experience-evidence/final-acceptance-after-race-fix.txt`.
- Last scoped Ruff, JS syntax and tracked diff-check passed. All finite test
  sessions from this continuation completed; persistent preview66999 kept live.

### Data, UI and evidence
- Fresh API/receipt audit: reference workv29,28 cards,28 full profiles,28 matching
  source hashes; original workv2 unchanged, no cards added; production jobs empty.
  `final-data-audit.json` outside repo records this without shipping private data.
- Updated21+ baseline tracked comparisons in `changed-paths-current.json` (source
  checkpoint only, not an exhaustive new-file list). No reset/clean/commit/push.
- Selected synthetic screenshots copied outside repo to persistent checkpoint
  evidence folder: populated production checklist light1440/dark390, settings
  model dark390, help light1440/dark390, assets dark390, mapping light390.
- Tab12 actual reference library refreshed to unified nav, v29/28 verified;
  tab13 real project center. Both deliverable-marked, normal viewport. Runtime
  stays7179, exec66999. Old user8765 tab untouched. No package rebuilt.

### Completion boundary
This supersedes earlier keep-ACTIVE notes: required overnight UI/reference scope
and safety verification completed with transparent inherited test debt. Remaining
real-provider cost/cache, native AA compile/install/heavy assets, packaging and
framework-wide rewrite are explicitly unperformed, not fake deliverables.


### 2026-09-25 资料页与错误反馈精修
- `services/halocue/writing/web/authoring-ui.css`：将资料页收敛为“索引 / 编辑工作台”视觉。人物库在无编辑器时使用双列紧凑卡片，打开编辑时切回可滚动列表 + 吸附式详情面板；压缩标题、统计、筛选和添加工具栏的垂直占用；补齐 hover / active / recent 状态、移动端单列回退、编辑表单双列排布。
- `services/halocue/writing/web/app.js`：重做 `toast()` 的 DOM 层次，错误提示现在分为状态图标、标题、可换行正文、报告错误操作和独立关闭按钮；根据错误 / 成功设置 `role` 与 `aria-live`，保留原有反馈上报入口和自动消失行为。
- 视觉检查：持续预览 `http://127.0.0.1:7179` 的真实人物参考库（28 张卡）已看到双列紧凑人物列表；未修改真实导入数据。
- 验证：`node --check services/halocue/writing/web/app.js`；`python -m pytest services/halocue/writing/tests/test_reference_details_ui.py services/halocue/writing/tests/test_shared_chrome_and_library_defaults.py services/halocue/writing/tests/test_ui_polish_layout.py services/halocue/writing/tests/test_manuscript_interaction_ui.py services/halocue/integrated/tests/test_experience_surface_matrix.py -q` → **44 passed**；`python -m pytest services/halocue/writing/tests/test_scene_message_ui.py -q` → **17 passed**。
- 未验证：真实 Provider、AA 原生工程编译、移动浏览器实体设备触控；本轮没有 reset / clean / commit / push。

### 2026-09-25 资料密度与前置反馈续修
- 在隔离集成预览（临时目录、28 张合成人物卡）复查上一轮效果。人物库去掉与侧栏重复的总标题，把“返回资料总览”放在人物库标题旁；桌面搜索与三个筛选共用一行，人物说明不再挤在卡片右侧窄列。1078px 预览中首张卡从约 505px 上移至约 327px；390px 手机预览约 448px，无横向溢出。
- 写作步骤尚未开放时，优先展开现有章节前置说明；其他无现成说明的工作面显示带下一步入口的页面内提示。预期的解锁条件不再触发红色错误 toast；真实操作失败仍保留错误反馈与报告入口。
- 原作语料不可读取时，检索输入与按钮禁用，并在原位置解释恢复后可检索；修复原作检索表单及统计标签在深色模式下仍呈浅色的问题。
- 验证：`node --check` app.js 与 writing-workbench.js、限定文件 `git diff --check` 通过；相关写作/资料 UI 测试 **47 passed**；新增隔离集成回归 `test_reference_feedback_ui.py` **1 passed**。人工检查浅色桌面、深色桌面、390px 手机、人物编辑、前置说明及原作语料不可用状态；浏览器无控制台警告或错误。
- 旧 7179 预览本次起初无法连接。布局与行为检查使用临时端口 7181 的隔离预览，检查后已关闭；正式人物资料与原作品均未修改。
- 最终交付前复核无其他 `halocue_integrated.server` 进程或 7179 监听后，用现有外部启动脚本恢复正式 7179 源码预览（当前 exec session 54335）。正式参考库页面只读确认版本 29 / 28 张卡、无横向溢出；已把该页面留在本轮应用内浏览器供用户查看。未重复导入或保存人物卡。

### 2026-09-25 真实素材与全流程隔离试用
- 独立运行 7181 临时写作/制作数据。用本机既有的露奈与天童凯伊（约会服）Spine 核心文件制作临时 ZIP，逐份校验、登记、预览。隔离项目里又把露奈素材显式复制到制作任务，确认头像可预览，并映射到说话者；旁白保持无立绘。
- 隔离作品从人物卡草稿、确认、构思讨论、方向候选审查、建立场景、手写正文、场景审查、挑选长期记忆、连续性/全篇审查，走到冻结 v1 与交给 AA 制作。曾退回两份错误地建议爱丽丝/凯伊的本地模拟候选；修复 Fake Provider 读取 `character_cards` 上下文后，第三份候选正确关联已确认的露奈卡，再于隔离数据中采纳。未尝试真实模型或 AA 原生编译/安装；当前没有配置 AA 资源索引和安装环境。
- 正式 7179 的跨作品素材库经 UI 连续登记 **2** 份真实角色素材：`露奈`（Nia）和 `天童凯伊（约会服）`（Kei_Date_Outfit）。两张包内头像在 UI 预览正常；凯伊 44 个语义表情组合标为“未渲染”，露奈 1 个表情已验证。素材标签注明约会服变体，未把它当作普通凯伊头像写入参考人物卡。重启后正式素材数仍为 2，参考作品仍为 v29 / 28 张原作卡，生产任务数 0。用户素材保存在既有外部 integrated production 数据目录，没有复制进仓库。
- 实际修复：深色上传弹窗与验证区对比度；空任务时的中性引导及 AA 入口；连续上传后隐藏的提交按钮；表情数量的准确措辞；人物备注被误当社团的字段分离（旧任务直传仍兼容）；正文未满足方向前置时的错误 CTA；本地模拟回复误称已生成候选，提到待核对人物卡时现在要求先确认，不再直接套用示例人物；无回执时的交接提示改为中性核对中。
- 验证：production custom asset library **12 passed**；writing asset polish + release handoff UI + Fake Provider 上下文 **26 passed**；conversation/vertical blueprint 与新增人物前置子集 **8 passed**。Node syntax、Ruff 与限定文件 `git diff --check` 通过。正式 7179 源码预览已重启并留在素材库；没有 reset / clean / commit / push，也未清理仓库原有脏改动。

### 2026-09-25 资料侧栏分类续修
- 用户指出人物库中的“设定与资料”侧栏层级不清。导航改成七个直接入口：总览、人物、世界观、剧情记录、关系图、来源资料、待审建议。关系图不再嵌在人物下，时间线与场景记忆归剧情记录，原作检索归来源资料；底层资料类型、修订和旧 `view` 深链接保持不变。
- 侧栏标题改为“作品资料”，宽度从 308px 收为 244px，给正文区更多空间。世界、剧情、来源的细项改由各自页面内标签切换；人物库仍是人物入口。手机分类选择器移到不会随页面标题消失的位置，并收成单行；顶部移动创作视图与作品卡入口也去掉旧“设定与资料”称呼。
- `test_shared_chrome_and_library_defaults.py` 24 passed；`test_reference_feedback_ui.py` 2 passed（包括七种详情路由在 390px 下的当前分类与横向溢出检查）。Node syntax、Ruff、限定文件 diff check 通过。正式 7179 预览只读验收 28 卡人物库、手机剧情/来源/关系入口和深色侧栏；主题恢复浅色、viewport override 已清除，预览留在人物库。未编辑用户资料。
