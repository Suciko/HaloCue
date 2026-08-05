# Background Visual Labeling and Scene Binding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让顶层导入的背景经视觉模型生成可编辑语义并参与初审匹配，同时让场景内导入的背景立即、持久地绑定到对应场景。

**Architecture:** 复用 `asset_install.metadata_json.labels` 保存背景语义，新增纯背景标注模块负责视觉输出规范化；Web 层用现有任务管理器排队视觉调用，并以故事令牌和素材键执行作用域校验。场景绑定由专用服务端接口更新指纹化初审快照，前端只消费结构化状态与受控预览 URL。

**Tech Stack:** Python 3、SQLite、Pillow、现有 LLM provider、原生 JavaScript/CSS、pytest、Node VM、Playwright Chromium。

## Global Constraints

- 不使用子 Agent，不创建 worktree，直接在当前 `main` 工作区实施。
- 不回滚、覆盖、暂存或提交与当前任务无关的已有改动。
- 不修改 AA 的 EXE、配置、AssetBundle、工作区文件或时间戳。
- 背景登记成功与视觉标注成功必须是两个独立状态。
- 未标注背景不得自动作为 AI 语义候选，但始终允许用户手动选择。
- 浏览器不得提交或接收本地安装路径；视觉任务只能解析服务端已登记副本。

---

### Task 1: 背景标签模型与目录持久化

**Files:**
- Create: `background_labeler.py`
- Modify: `asset_catalog.py`
- Create: `tests/test_background_labeler.py`
- Modify: `tests/test_story_asset_api.py`

**Interfaces:**
- Produces: `BackgroundLabels` with `label`, `description`, `place`, `indoor_outdoor`, `time`, `weather`, `season`, `mood`, `tags`.
- Produces: `normalize_background_labels(value: object) -> dict`.
- Produces: `label_background(provider, image_path: Path) -> dict`.
- Produces: `asset_catalog.library_background_analysis_target(con, *, aa_key, sha256) -> dict`.
- Produces: `asset_catalog.update_background_labels(con, *, aa_key, sha256, labels, status, error="") -> dict`.

- [ ] **Step 1: Write failing label normalization and persistence tests**

Test that overlong/path-shaped text is removed, tags are deduplicated and bounded, the visual provider receives a JPEG derivative rather than a path, and an update changes every custom copy with the same immutable key/hash while leaving unrelated rows unchanged.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest -q tests/test_background_labeler.py tests/test_story_asset_api.py -k 'background_label'`

Expected: FAIL because the module and catalog methods do not exist.

- [ ] **Step 3: Implement pure visual labeling and safe catalog updates**

Use a strict JSON schema with the nine fields listed above. Convert the registered image to a bounded RGB JPEG in memory before `provider.complete_json_vision`. Store `labels`, `label_status`, `label_error`, and `labels_updated_at` inside metadata JSON for all matching custom copies. Synchronize the legacy `bg` row from the normalized labels without changing AA files.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest -q tests/test_background_labeler.py tests/test_story_asset_api.py -k 'background_label'`

Expected: PASS.

- [ ] **Step 5: Review and commit Task 1 only**

Run: `git diff --check -- background_labeler.py asset_catalog.py tests/test_background_labeler.py tests/test_story_asset_api.py`

Commit only Task 1 hunks: `feat: label imported backgrounds with vision`

---

### Task 2: 视觉任务 API 与素材工作台编辑

**Files:**
- Modify: `webui.py`
- Modify: `js/assets.js`
- Modify: `js/library.js`
- Modify: `css/app.css`
- Modify: `tests/test_story_asset_api.py`
- Modify: `tests/test_ui_asset_tasks.py`
- Modify: `tests/test_ui_asset_workbench_responsive.py`

**Interfaces:**
- Produces: `queue_background_label_analysis(payload: dict) -> {status, queued, job_id}`.
- Produces: `POST /api/assets/library/background-label` for AI retry.
- Produces: `POST /api/assets/library/background-labels` for manual edits.
- Adds import result field `background_analysis`.

- [ ] **Step 1: Write failing API and runtime tests**

Assert context-free background registration queues a visual job; supplied scene labels skip the job; a failed visual job leaves registration available with `label_status=failed`; manual label save updates the library response. Assert asset task copy says “正在识别背景场景” and a failed label job says “背景已登记，AI 标注失败，可在素材工作台补充”。

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest -q tests/test_story_asset_api.py tests/test_ui_asset_tasks.py tests/test_ui_asset_workbench_responsive.py -k 'background_label or visual_background'`

Expected: FAIL because background jobs and editor controls are absent.

- [ ] **Step 3: Implement secure queueing and manual-save endpoints**

Resolve the installed image through `library_background_analysis_target`; never accept a path. Use `global_job_manager` for the provider call, persist success/failure through Task 1, and return only public job state. Accept scene-provided labels during registration and skip visual queue when they normalize to a non-empty label set.

- [ ] **Step 4: Implement workbench label editor**

For background detail, render status, fields for the nine label properties, “AI 识别场景” and “保存标注”. Poll jobs with the existing API helper, refresh the selected asset after completion, and keep import status “已登记” even when labeling fails.

- [ ] **Step 5: Run focused tests and syntax checks**

Run: `python -m pytest -q tests/test_story_asset_api.py tests/test_ui_asset_tasks.py tests/test_ui_asset_workbench_responsive.py`

Run: `node --check js/assets.js`

Run: `node --check js/library.js`

Expected: all pass.

- [ ] **Step 6: Review and commit Task 2 only**

Run: `git diff --check -- webui.py js/assets.js js/library.js css/app.css tests/test_story_asset_api.py tests/test_ui_asset_tasks.py tests/test_ui_asset_workbench_responsive.py`

Commit only Task 2 hunks: `feat: edit background scene labels in workbench`

---

### Task 3: 自定义背景参与 AI 初审候选

**Files:**
- Modify: `webui.py`
- Modify: `tests/test_preflight.py`
- Modify: `tests/test_story_asset_api.py`

**Interfaces:**
- Consumes: labeled `custom_assets.backgrounds` from Task 1.
- Produces: normalized background candidates with `source` equal to `official` or `custom`.
- Guarantees: custom candidate keys are validated against the current story scope.

- [ ] **Step 1: Write failing custom-candidate tests**

Provide one labeled custom background, one unlabeled custom background, and one forged key. Assert only the labeled in-scope item reaches the model candidate input and survives normalization with `source=custom`; the forged and unlabeled items do not become automatic candidates.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest -q tests/test_preflight.py tests/test_story_asset_api.py -k 'custom_background_candidate'`

Expected: FAIL because candidate normalization currently accepts official `bg` rows only.

- [ ] **Step 3: Extend preflight prompt and candidate normalization**

Tell the model to prefer a semantically fitting current-story custom background and return its exact key. Validate custom candidates against `custom_assets.backgrounds` before official lookup, attach the source and display label, and expose a story-scoped preview marker without paths.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest -q tests/test_preflight.py tests/test_story_asset_api.py -k 'background or preflight'`

Expected: PASS.

- [ ] **Step 5: Review and commit Task 3 only**

Run: `git diff --check -- webui.py tests/test_preflight.py tests/test_story_asset_api.py`

Commit only Task 3 hunks: `feat: recommend labeled custom backgrounds`

---

### Task 4: 单一导入模态与持久场景绑定

**Files:**
- Modify: `story_workspace.py`
- Modify: `webui.py`
- Modify: `js/app.js`
- Modify: `js/library.js`
- Modify: `tests/test_story_workspace.py`
- Modify: `tests/test_story_asset_api.py`
- Modify: `tests/test_ui_preflight_timeline.py`
- Modify: `tests/test_ui_story_workspace.py`

**Interfaces:**
- Produces: `StoryWorkspaceRegistry.bind_preflight_background(story_token, selector, binding) -> StoryContext`.
- Produces: `POST /api/preflight/background-binding`.
- Extends: asset workbench context with `background_target` and completion event `assetworkbench:background-applied`.

- [ ] **Step 1: Write failing binding and single-modal tests**

Assert clicking either import action closes `mGenerationPrompt` before opening `mBrowse`. After registration, assert the matching need becomes `registered`, stores `aa_key`, `selected_label`, `source=custom`, has a story preview URL, and remains so after registry reconstruction. Assert a stale story token cannot bind another story.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest -q tests/test_story_workspace.py tests/test_story_asset_api.py tests/test_ui_preflight_timeline.py tests/test_ui_story_workspace.py -k 'background_binding or generation_import'`

Expected: FAIL because current code stacks modals and only reruns preflight.

- [ ] **Step 3: Implement scoped snapshot binding**

Match a need using bounded `segment`, `location`, and `requested_name`; validate the background against the story scope before updating. Persist the updated result with the existing source fingerprint and return a public snapshot. Reject missing, ambiguous, stale, or cross-story selectors without changing the snapshot.

- [ ] **Step 4: Implement direct scene import and workbench apply mode**

Close the prompt modal before the picker opens. Pass inherited scene labels to `StoryAssets.importLocal`, call the binding endpoint with the returned key, replace the current need locally from the returned snapshot, and render the story preview immediately. When workbench is opened from a need, show “应用到当前场景”; copy first if needed, then call the same binding endpoint and return focus to the originating card.

- [ ] **Step 5: Run focused tests and syntax checks**

Run: `python -m pytest -q tests/test_story_workspace.py tests/test_story_asset_api.py tests/test_ui_preflight_timeline.py tests/test_ui_story_workspace.py`

Run: `node --check js/app.js`

Run: `node --check js/library.js`

Expected: all pass.

- [ ] **Step 6: Review and commit Task 4 only**

Run: `git diff --check -- story_workspace.py webui.py js/app.js js/library.js tests/test_story_workspace.py tests/test_story_asset_api.py tests/test_ui_preflight_timeline.py tests/test_ui_story_workspace.py`

Commit only Task 4 hunks: `fix: bind imported backgrounds to scene needs`

---

### Task 5: 浏览器与全量验收

**Files:**
- Verify only.

- [ ] **Step 1: Run complete automated verification**

Run: `python -m pytest -q`

Run: `node --check js/app.js`

Run: `node --check js/assets.js`

Run: `node --check js/library.js`

Run: `python prepare_release.py --check`

- [ ] **Step 2: Run Playwright desktop/mobile workflow**

Verify at 1200px and 390px: prompt-to-picker never stacks two modals; context import returns to the scene card with preview and saved state; top-level import shows labeling progress; workbench labels are editable; applying an existing background closes the workbench and updates the originating card. Confirm no horizontal overflow and no console errors from this feature.

- [ ] **Step 3: Verify repository and AA boundaries**

Run: `git diff --check`

Run: `git status --short`

Run: `git diff --cached --name-only`

Capture the actual AA EXE/data/resource-cache metadata fingerprint before and after read-only discovery; confirm it is unchanged. Do not start any test server against real `--aa-data` unless the test is proven not to write.
