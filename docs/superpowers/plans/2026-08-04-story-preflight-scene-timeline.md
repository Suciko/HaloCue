# 剧本初审与场景演出时间线 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户用自然语言剧本完成 AI 初审，由系统生成可校对的场景演出时间线，并修复来源、素材、失败状态和界面可读性问题。

**Architecture:** 后端扩展初审 JSON 协议，增加按场景分段的 `usage_chain`；规则层继续兼容已有 AA 指令，但不再把内部 `@bg/@bgm/@sound` 当成普通用户输入。前端以场景时间线呈现背景、BGM 和音效需求，缺失背景生成可编辑的中文图片提示词，确认后才由后续生成流程转换为 AA 内部指令。来源信息只公开安全面包屑、文件大小和修改时间。

**Tech Stack:** Python 3、标准库 HTTP 服务、SQLite、原生 JavaScript、CSS、pytest、Node UI runtime harness。

## Global Constraints

- 浏览器永远不能收到源文件、项目目录、密钥或命令行绝对路径。
- 用户界面以中文为主；`@bg`、`@bgm`、`@sound` 仅保留为内部兼容/生成层概念。
- 初审失败不能显示为“没有需求”；必须保留规则结果并显示可执行的失败原因。
- AI 推断结果必须带证据和置信度；未确认结果不能修改原剧本正文。
- 缺失背景提示词只生成文本草稿，图片导入和素材登记仍由用户确认。
- 每个行为先添加能复现问题的失败测试，再写生产代码；改动后运行相关测试和完整回归测试。

---

### Task 1: 安全的剧本来源上下文

**Files:**
- Modify: `story_workspace.py:45-75,206-228`
- Modify: `js/story.js:25-75`
- Modify: `js/app.js:178-202`
- Test: `tests/test_story_workspace.py`
- Test: `tests/test_ui_story_workspace.py`

**Interfaces:**
- `public_story_context()` and `public_story_summary()` produce `source_display`, `source_size`, and `source_modified` without exposing `source_path`.
- The browser renders `文件类型 + 安全面包屑 + 大小 + 修改时间` and recent-story entries use the same safe fields.
- Restoring a recent story re-runs the current analysis so the visible workspace is tied to the restored source.

- [ ] **Step 1: Write failing tests** for safe source metadata, absence of the physical path, and automatic recent-story analysis.
- [ ] **Step 2: Run the focused tests** and confirm they fail because the fields and refresh behavior do not exist.
- [ ] **Step 3: Implement safe metadata serialization** using bounded parent components, file stat values, and a stable file-type label.
- [ ] **Step 4: Update the story context bar and recent-story renderer**; preserve `source_name` for compatibility while showing the richer display fields.
- [ ] **Step 5: Call `analyze()` after a successful recent-story restore** while keeping stale-operation guards intact.
- [ ] **Step 6: Run focused tests and the existing story workspace suite**.

### Task 2: 初审协议、完整演出链和可诊断失败

**Files:**
- Modify: `webui.py:1050-1490`
- Modify: `js/app.js:220-380`
- Modify: `tests/test_preflight.py`
- Modify: `tests/test_ui_preflight_timeline.py`

**Interfaces:**
- `_PREFLIGHT_SCHEMA` adds `usage_chain` segments containing `segment`, `location`, `start`, `end`, `evidence`, and typed `needs` entries.
- `_preflight_result()` returns `usage_chain`, `usage_chain_status`, and a safe `ai_diagnostics` object; model-provided statuses are normalized against official/current-story catalogs.
- Failed jobs preserve `job.error`; frontend shows `初审任务失败` plus the error text and does not claim that no asset need was found.

- [ ] **Step 1: Add provider fixtures and assertions** for a freeform script whose AI result contains background, BGM, and sound needs with evidence and confidence.
- [ ] **Step 2: Add a failure regression test** asserting that the UI keeps the backend error and labels the chain as `未完成分析`.
- [ ] **Step 3: Run the focused tests** and observe the missing schema, normalization, and error propagation failures.
- [ ] **Step 4: Extend the strict JSON schema and prompt** to require a complete natural-language scene chain, not directive discovery.
- [ ] **Step 5: Normalize each AI need** into `builtin`, `registered`, `missing`, `unsupported`, or `unknown`; generate a safe background prompt for missing backgrounds and attach source evidence.
- [ ] **Step 6: Return structured diagnostics** including stage, provider/model label, and a redacted message; preserve the raw job error only as a user-visible non-secret detail.
- [ ] **Step 7: Update `runPreflight()` and fallback rendering** to pass `job.error`, distinguish `未完成分析` from `暂无需求`, and keep rule-based character results.
- [ ] **Step 8: Run the focused backend and UI tests**.

### Task 3: 当前界面的统一场景演出时间线

**Files:**
- Modify: `ui.html:31-38,86`
- Modify: `js/app.js:267-345`
- Modify: `css/app.css:190-240`
- Modify: `css/layout.css:90-150`
- Test: `tests/test_ui_preflight_timeline.py`
- Test: `tests/test_ui_polish_contract.py`

**Interfaces:**
- `renderUsageChain(result)` renders one collapsible scene timeline; each scene contains background, BGM, and sound needs.
- Each need exposes status, evidence, confidence, and action buttons. Missing backgrounds expose `生成提示词`, `复制提示词`, and `导入生成图`/asset-workbench entry points.
- The old `素材引用` panel becomes `场景演出规划`; empty and failed states have different copy.

- [ ] **Step 1: Add UI runtime tests** for scene ordering, empty-success copy, failed-analysis copy, and background prompt generation.
- [ ] **Step 2: Run them and confirm the current directive-based panel fails the assertions.**
- [ ] **Step 3: Add the timeline container and an accessible collapsible summary in `ui.html`.**
- [ ] **Step 4: Implement DOM-safe rendering** for scene segments, typed needs, status labels, evidence, and confidence.
- [ ] **Step 5: Implement an editable prompt dialog/card** with one-click copy and no external-provider dependency.
- [ ] **Step 6: Add responsive/high-contrast styles** and explicitly set text colors for cast results and background cards; render available background previews.
- [ ] **Step 7: Keep old asset-workbench actions as secondary operations** and route history import using the actual need kind.
- [ ] **Step 8: Run UI harness tests and browser smoke tests.**

### Task 4: 本剧情自定义素材和历史导入修复

**Files:**
- Modify: `js/assets.js:240-315`
- Modify: `js/app.js:315-330`
- Modify: `ui.html:21,90-91`
- Modify: `css/app.css:195-205`
- Test: `tests/test_ui_asset_workbench_responsive.py`
- Test: `tests/test_ui_preflight_timeline.py`

**Interfaces:**
- The strip title is `本剧情自定义素材`; the “全部” filter offers neutral `导入素材` actions and never silently changes a character need into a background need.
- `known`, `registered`, and identifier text are translated or moved to detail-only UI.
- History import keeps `character`, `background`, and `sound` kinds intact.

- [ ] **Step 1: Add failing text/interaction assertions** for the title, Chinese labels, role history import, and status translations.
- [ ] **Step 2: Run the focused UI tests and confirm the current regressions.**
- [ ] **Step 3: Fix import-kind selection, history routing, and user-facing labels.**
- [ ] **Step 4: Fix cast-result and background-card contrast and insert background preview images.**
- [ ] **Step 5: Run focused UI tests and asset API tests.**

### Task 5: 回归验证与交付检查

**Files:**
- Modify: `docs/superpowers/plans/2026-08-04-story-preflight-scene-timeline.md`
- Test: `tests/test_preflight.py`, `tests/test_story_workspace.py`, `tests/test_ui_preflight_timeline.py`, `tests/test_ui_asset_workbench_responsive.py`

- [ ] **Step 1: Run all focused Python and Node tests.**
- [ ] **Step 2: Run the complete `pytest` suite and record failures with exact causes.**
- [ ] **Step 3: Start the local web server and run a browser smoke test at desktop and mobile widths.**
- [ ] **Step 4: Verify that generated prompt text contains no local paths or secrets, and that AI failure states never claim “暂无需求”.**
- [ ] **Step 5: Review the final diff for unrelated changes and report evidence-based results.**
