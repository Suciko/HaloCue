# 审查状态与最近剧情 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让最近剧情列表可折叠，并让审查预览与初审背景候选在首次载入和重开项目时稳定恢复。

**Architecture:** 保持现有 RecentStories、Player、StoryWorkspaceRegistry 边界。RecentStories 只负责会话内显示截断；播放器由 AppRuntime 在工作区生命周期内显式销毁/重建；初审结果继续以项目快照为权威数据源，完整保留候选数组和绑定字段。

**Tech Stack:** 原生 JavaScript、Python 标准库、pytest、现有 `tests/ui_runtime_harness.js`。

## Global Constraints

- 不修改用户剧本正文、草稿内容或既有素材数据库。
- 不把候选压缩为单一 `suggested_aa_key`；重开时保留候选顺序、分数和理由。
- 最近剧情展开状态只存在页面会话，不写入项目索引。
- 播放器不可用时仍保留卡片审查，右侧只显示空预览提示。

---

### Task 1: 最近剧情三条截断与展开

**Files:**
- Modify: `js/story.js:68-106`
- Test: `tests/test_ui_story_workspace.py`

**Interfaces:**
- `RecentStories` 继续消费 `/api/stories/recent` 返回数组。
- 组件增加会话字段 `expanded`，不改变回调 `onOpen(story)`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_ui_story_workspace.py` 增加 harness 场景，返回 5 条记录；断言首次列表只有 3 个 `.recent-story`，存在“打开查看更多”；点击后有 5 条并出现“收起”，再次点击恢复 3 条。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_ui_story_workspace.py -k recent_story_limit -q`

Expected: FAIL，因为当前 `RecentStories.refresh()` 渲染全部记录且没有展开控件。

- [ ] **Step 3: 实现最小改动**

在 `RecentStories` 构造函数初始化 `this.expanded = false`。刷新后按返回顺序取 `stories.slice(0, this.expanded ? stories.length : 3)`，当 `stories.length > 3` 在列表末尾追加按钮；按钮只切换 `expanded` 并再次调用 `refresh()`，不触发网络以外的项目状态改变。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_ui_story_workspace.py -k recent_story_limit -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add js/story.js tests/test_ui_story_workspace.py
git commit -m "feat: collapse recent stories after three entries"
```

### Task 2: 修复播放器首次载入生命周期

**Files:**
- Modify: `js/app.js:95-105, 160-170, 1718-1739`
- Test: `tests/test_ui_runtime_behavior.py`, `tests/test_ui_player.py`

**Interfaces:**
- 保持 `playerInstance()`、`ensurePlayer()`、`window.Preview.clear()` 的公开调用方式。
- 新增内部 `destroyPlayer()`，负责暂停、清空引用并移除旧播放器 DOM。

- [ ] **Step 1: 写失败测试**

在 `tests/test_ui_runtime_behavior.py` 增加场景：先加载第一份草稿并记录 `window.storyPlayer`，调用工作区清理，再加载第二份草稿；断言第二次 `storyPlayer` 不是旧实例，`#storyPlayer` 有预览文本且 `#rvSelectionLabel` 指向第一张卡。补充空卡片场景，断言仍显示“选择卡片”提示。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_ui_runtime_behavior.py -k player_rebuild -q`

Expected: FAIL，因为清理流程保留旧 Player 实例，第二次 `loadCards()` 更新的是已脱离 DOM 的节点。

- [ ] **Step 3: 实现最小改动**

实现 `destroyPlayer()`：暂停当前实例、清空 `window.storyPlayer`，并清空 `#storyPlayer`。让 `resetReview()`/工作区清理调用它；`loadReview()` 在渲染卡片后创建播放器并调用 `selectCard(cards[0])`（存在卡片时），不存在时仅装载空数组。避免 `selectCard()` 在播放器尚未创建时丢失同步：先创建播放器，再选择第一卡。

- [ ] **Step 4: 运行相关测试**

Run: `python -m pytest tests/test_ui_runtime_behavior.py tests/test_ui_player.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add js/app.js tests/test_ui_runtime_behavior.py tests/test_ui_player.py
git commit -m "fix: rebuild story preview when review workspace changes"
```

### Task 3: 背景候选快照完整恢复

**Files:**
- Modify: `story_workspace.py:115-166, 381-410`
- Test: `tests/test_story_workspace.py`, `tests/test_web_background_resume.py`

**Interfaces:**
- `set_preflight_snapshot(story_token, result)` 继续接收公开初审结果。
- `public_story_context()` 继续返回 `preflight_snapshot.result`，其中 `usage_chain[].needs[].candidates` 必须完整保留。

- [ ] **Step 1: 写失败测试**

增加快照回归测试：构造同一 need 含 90% 与 60% 两个官方候选，保存快照、重新创建 `StoryWorkspaceRegistry`，断言两个候选及其 `confidence`、`reason` 和顺序均存在；再绑定一个候选，断言绑定字段与候选列表同时保留。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_story_workspace.py tests/test_web_background_resume.py -k candidates -q`

Expected: FAIL if snapshot sanitization or binding path drops the non-selected candidate.

- [ ] **Step 3: 实现最小改动**

在 `_safe_preflight_snapshot()` 中只移除诊断和不安全路径字段，不删除 `candidates`；在 `bind_preflight_background()` 中只更新 `selected_aa_key`/`binding` 等当前选择字段，保留 `need["candidates"]`；恢复时直接使用保存快照，不调用新的候选排序。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_story_workspace.py tests/test_web_background_resume.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add story_workspace.py tests/test_story_workspace.py tests/test_web_background_resume.py
git commit -m "fix: preserve all preflight background candidates"
```

### Task 4: 集成验证

**Files:**
- Test: `tests/test_ui_story_workspace.py`, `tests/test_ui_runtime_behavior.py`, `tests/test_story_workspace.py`, `tests/test_web_background_resume.py`

- [ ] **Step 1: 运行聚焦测试**

Run: `python -m pytest tests/test_ui_story_workspace.py tests/test_ui_runtime_behavior.py tests/test_ui_player.py tests/test_story_workspace.py tests/test_web_background_resume.py -q`

- [ ] **Step 2: 运行完整测试套件**

Run: `python -m pytest -q`

- [ ] **Step 3: 浏览器烟测**

启动现有 `webui.py` 服务，打开一份含草稿的剧情，确认首次点击“打开草稿”时右侧显示 `1 / N` 和第一张卡内容；返回首页确认默认最多三条最近剧情，点击“打开查看更多”后能看到其余记录；重开项目确认初审背景候选仍显示完整列表。
