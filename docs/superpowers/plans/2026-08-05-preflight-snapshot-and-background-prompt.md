# AI 初审快照与背景提示词入口 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 历史剧情恢复最近一次有效 AI 初审结果，并为所有低于 90% 官方匹配度的背景稳定提供网页端生图提示词工作流。

**Architecture:** 在现有 `StoryWorkspaceRegistry` 原子历史索引中保存经过裁剪的初审快照和原文指纹；HTTP 层在初审任务成功及用户确认时更新快照；前端从历史记录恢复快照并区分 fresh/stale。背景提示词继续使用现有模态框，后端保证返回提示词，前端提供兼容旧数据的保底生成。

**Tech Stack:** Python 3、标准库 `hashlib/json/pathlib`、现有 `ThreadingHTTPServer` API、原生 JavaScript、HTML/CSS、pytest、Node VM 测试、Playwright Chromium。

## Global Constraints

- 不使用子 Agent，不创建 worktree，直接在当前 `main` 工作区实施。
- 不回滚、覆盖、暂存或提交与当前任务无关的已有改动。
- 不修改 AA 的 EXE、配置、AssetBundle、工作区文件或时间戳。
- 原文未变化时恢复快照；原文变化时显示旧结果但禁止直接进入生成步骤。
- 官方背景最高匹配度达到 90% 时不显示自定义背景工作流。
- 不在网页内直接调用图像生成服务。

---

### Task 1: 持久化初审快照与原文新鲜度

**Files:**
- Modify: `story_workspace.py`
- Test: `tests/test_story_workspace.py`

**Interfaces:**
- Produces: `StoryWorkspaceRegistry.set_preflight_snapshot(story_token: str, result: dict) -> StoryContext`
- Produces: `StoryWorkspaceRegistry.set_preflight_approved(story_token: str, approved: bool) -> StoryContext`
- Produces: `public_story_context(context)` 中的 `preflight_snapshot = {state, result, approved, saved_at}`

- [ ] **Step 1: Write failing registry tests**

新增测试，保存包含 `ai_diagnostics` 的结果，重建 registry 后断言快照恢复、诊断字段未持久化、状态为 `fresh`；修改原文后断言同一快照状态为 `stale` 且结果仍可读取。

```python
registry.set_preflight_snapshot(context.story_token, {
    "ai_status": "completed", "characters": [], "usage_chain": [],
    "ai_diagnostics": {"message": "private"},
})
restored = StoryWorkspaceRegistry(index_path, aa_data).list_recent()[0]
payload = public_story_context(reloaded.resolve_story_token(restored.story_token))
assert payload["preflight_snapshot"]["state"] == "fresh"
assert "ai_diagnostics" not in payload["preflight_snapshot"]["result"]
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest -q tests/test_story_workspace.py -k preflight_snapshot`

Expected: FAIL because snapshot methods and public field do not exist.

- [ ] **Step 3: Implement fingerprinted atomic snapshot storage**

Add SHA-256/size/mtime fingerprint helpers, safe JSON snapshot normalization, the optional `preflight_snapshot` context field, record serialization, and both update methods. Preserve snapshots in `open_path` and `set_latest_draft_token`; never expose the fingerprint or source path to the browser.

- [ ] **Step 4: Run focused registry tests**

Run: `python -m pytest -q tests/test_story_workspace.py`

Expected: all tests pass.

- [ ] **Step 5: Review diff and commit only Task 1 files**

Run: `git diff --check -- story_workspace.py tests/test_story_workspace.py`

Commit: `feat: persist story preflight snapshots`

---

### Task 2: 保存后台初审并同步确认状态

**Files:**
- Modify: `webui.py`
- Test: `tests/test_story_asset_api.py`

**Interfaces:**
- Consumes: Task 1 registry methods.
- Produces: `POST /api/preflight/approve` with `{story_token, approved}`.
- Produces: successful preflight job result field `snapshot_saved: bool`.

- [ ] **Step 1: Write failing HTTP tests**

扩展 preflight endpoint 测试：后台任务成功后读取 `/api/story/current`，断言返回 fresh snapshot；POST `/api/preflight/approve` 后再次读取并断言 `approved is True`。模拟索引写入失败时断言 job 仍成功且 `snapshot_saved is False`。

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest -q tests/test_story_asset_api.py -k 'preflight_endpoint or preflight_approve'`

Expected: FAIL because jobs do not save snapshots and approve route is absent.

- [ ] **Step 3: Implement worker persistence and approve endpoint**

`preflight_story_worker` computes the public result, attempts `set_preflight_snapshot`, and records only a boolean save status. The approve route resolves the opaque story token and calls `set_preflight_approved`; invalid tokens return the existing stable error shape.

- [ ] **Step 4: Run focused API tests**

Run: `python -m pytest -q tests/test_story_asset_api.py -k 'preflight or story_current'`

Expected: all selected tests pass.

- [ ] **Step 5: Review diff and commit only Task 2 files**

Run: `git diff --check -- webui.py tests/test_story_asset_api.py`

Commit: `feat: restore saved preflight through story api`

---

### Task 3: 历史记录恢复 fresh/stale 初审

**Files:**
- Modify: `js/app.js`
- Test: `tests/test_ui_story_workspace.py`
- Test: `tests/test_ui_preflight_timeline.py`

**Interfaces:**
- Consumes: `context.preflight_snapshot` from Task 2.
- Produces: `restorePreflightSnapshot(snapshot)` and asynchronous `approvePreflight()`.

- [ ] **Step 1: Write failing runtime tests**

测试历史打开 fresh snapshot 时 `renderPreflight` 恢复内容且 `/api/analyze`、`/api/preflight` 调用数均为零；fresh + approved 直接显示第 3 步。测试 stale snapshot 显示“原文已变化”，禁用确认和生成，点击重新检查后才请求 preflight。

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest -q tests/test_ui_story_workspace.py tests/test_ui_preflight_timeline.py -k 'snapshot or recent_restores'`

Expected: FAIL because `openRecent` always calls `analyze()`.

- [ ] **Step 3: Implement snapshot restoration**

Add `state.preflightStale`; clear it on story switches/reruns. Restore `analysis`, mapping, rendered result and approval state from a fresh snapshot. Render stale results with a warning and disabled approval; do not reveal generation. Make approval persist through `/api/preflight/approve`, while a save failure leaves the current session usable and reports that the confirmation was not saved.

- [ ] **Step 4: Run focused UI runtime tests**

Run: `python -m pytest -q tests/test_ui_story_workspace.py tests/test_ui_preflight_timeline.py`

Expected: all tests pass.

- [ ] **Step 5: Review diff and commit only Task 3 files**

Run: `node --check js/app.js`

Commit: `feat: restore preflight decisions from history`

---

### Task 4: 稳定提示词入口并整理背景工作流 UI

**Files:**
- Modify: `js/app.js`
- Modify: `ui.html`
- Modify: `css/app.css`
- Test: `tests/test_ui_preflight_timeline.py`
- Test: `tests/test_ui_asset_workbench_responsive.py`
- Test: `tests/test_ui_polish_contract.py`

**Interfaces:**
- Produces: `backgroundGenerationPrompt(need) -> string` for legacy snapshots.
- Keeps: `data-usage-action="generate-prompt"` and existing `mGenerationPrompt` modal.

- [ ] **Step 1: Write failing prompt and layout tests**

Remove `generation_prompt` from the test need while keeping a 72% candidate. Assert all four actions exist, the first action text is `生成生图提示词`, clicking it opens a non-empty prompt containing the scene name and `16:9`, and the modal exposes `导入生成结果`. Update Chromium assertions for compact summary and no horizontal overflow.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest -q tests/test_ui_preflight_timeline.py tests/test_ui_polish_contract.py tests/test_ui_asset_workbench_responsive.py -k 'background_workflow or generation_prompt'`

Expected: FAIL because the prompt button is omitted when the field is absent and the modal has no import action.

- [ ] **Step 3: Implement fallback prompt and polished controls**

Always derive a prompt for `shouldOfferCustomBackground(need)`. Make the prompt button the primary action labeled `生成生图提示词`; style the details summary as a compact disclosure row, use subdued body treatment, and add `导入生成结果` to the modal using the existing `StoryAssets.importLocal('background', {name})` flow.

- [ ] **Step 4: Run focused tests and Chromium QA**

Run: `python -m pytest -q tests/test_ui_preflight_timeline.py tests/test_ui_polish_contract.py tests/test_ui_asset_workbench_responsive.py`

Expected: all tests pass and generated screenshots show no overflow at desktop/mobile widths.

- [ ] **Step 5: Review diff and commit only Task 4 files**

Run: `node --check js/app.js`

Commit: `fix: expose background generation prompt workflow`

---

### Task 5: 全量验证与关机前检查

**Files:**
- Verify only; do not change AA files.

- [ ] **Step 1: Run complete automated verification**

Run: `python -m pytest -q`

Run: `node --check js/app.js`

Run: `python prepare_release.py --check`

- [ ] **Step 2: Review repository boundaries**

Run: `git diff --check`

Run: `git status --short`

Run: `git diff --cached --name-only`

Confirm no generated official preview files are staged and no test ports remain listening.

- [ ] **Step 3: Shut down Windows after successful completion**

Only after every required verification exits successfully, run: `shutdown.exe /s /t 0`
