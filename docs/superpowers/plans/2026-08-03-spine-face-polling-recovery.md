# 骨骼表情标注轮询恢复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复骨骼表情标注在一次进度读取失败后永久停在 rendering，并为长时间 Spine 渲染提供逐表情进度。

**Architecture:** 前端 `FaceWorkspace` 保存连续轮询失败次数并调度有上限的退避重试，成功响应清零并回到正常间隔。后端 `render_face_variations` 通过可选回调报告逐表情进度，`analyze_character_faces` 将其映射到现有 FACE_JOB 字段。

**Tech Stack:** 原生 JavaScript、Node `vm` 测试、Python 3.13、pytest、Pillow。

## Global Constraints

- 不新增运行时依赖。
- 不改变 `/api/assets/faces/job` 的公开字段。
- 不重新提交或并行启动失败轮询对应的任务。
- 关闭工作区或 generation 变化后必须停止旧轮询。
- 保留 Spine 命令现有 120 秒超时。

---

### Task 1: 前端恢复型轮询

**Files:**
- Modify: `tests/test_ui_asset_library.py`
- Modify: `js/library_faces.js`

**Interfaces:**
- Consumes: `exports.Api.request('/api/assets/faces/job')`、`FaceWorkspace.generation`、`FaceWorkspace.timer`
- Produces: `FaceWorkspace.scheduleRefresh(delay)`、连续失败计数和自动恢复行为

- [ ] **Step 1: 写失败测试**

新增 Node `vm` 运行时测试：第一次 API 请求 reject，执行捕获的重试 timer；第二次返回 `running=true`；执行正常 timer；第三次返回 `done=true, ok=true`。断言请求共三次、首个失败后按钮禁用、状态包含“自动重试”、成功后失败计数归零、终态不再排 timer。

- [ ] **Step 2: 验证测试因当前实现不重试而失败**

Run: `python -m pytest tests/test_ui_asset_library.py -k recovers -vv`

Expected: FAIL，timer 数量或请求次数不足。

- [ ] **Step 3: 写最小实现**

在 `FaceWorkspace` 中增加 `pollFailures`；`open` 重置计数；`refresh` 成功时归零，运行中以 850ms 调度；失败时递增计数、禁用启动按钮、显示自动重试信息，并以 `min(8000, 850 * 2 ** pollFailures)` 调度。所有调度都复用一个 `scheduleRefresh` 并检查工作区/generation。

- [ ] **Step 4: 验证前端测试通过**

Run: `python -m pytest tests/test_ui_asset_library.py -k 'face_workspace or recovers' -vv`

Expected: PASS。

- [ ] **Step 5: 提交**

Run: `git add js/library_faces.js tests/test_ui_asset_library.py && git commit -m "fix: recover spine face job polling"`

### Task 2: 逐表情渲染进度

**Files:**
- Modify: `tests/test_spine_face_renderer.py`
- Modify: `tests/test_spine_face_analysis.py`
- Modify: `spine_face_renderer.py`
- Modify: `spine_face_analysis.py`

**Interfaces:**
- Produces: `render_face_variations(..., progress: Callable[[str, int, int], None] | None = None)`
- Consumes: `analyze_character_faces(..., progress=ProgressCallback)`

- [ ] **Step 1: 写渲染器失败测试**

复用现有假的 Spine runner 和两张 face fixture，传入收集回调，断言事件包含 `('00', 0, 2)`、`('00', 1, 2)`、`('01', 1, 2)`、`('01', 2, 2)`。

- [ ] **Step 2: 验证缺少 progress 参数导致失败**

Run: `python -m pytest tests/test_spine_face_renderer.py -k reports_per_face_progress -vv`

Expected: FAIL with unexpected keyword argument `progress`。

- [ ] **Step 3: 实现渲染回调**

在串行渲染循环前后调用回调；并行分支保持线程池但只在主线程按完成结果更新累计值。本工作流传入 `workers=1`，不改变渲染输出和缓存契约。

- [ ] **Step 4: 写编排层失败测试并实现映射**

假的 `render_face_variations` 调用 progress，断言对外回调收到 `phase='rendering'`、准确 current/total 和 face ID 文案。然后在 `analyze_character_faces` 传入适配器。

- [ ] **Step 5: 验证后端相关测试通过并提交**

Run: `python -m pytest tests/test_spine_face_renderer.py tests/test_spine_face_analysis.py -vv`

Expected: PASS。

Run: `git add spine_face_renderer.py spine_face_analysis.py tests/test_spine_face_renderer.py tests/test_spine_face_analysis.py && git commit -m "feat: report spine face render progress"`

### Task 3: 集成验证

**Files:**
- Verify only

**Interfaces:**
- Consumes: 前两项的最终行为
- Produces: 合并前验证证据

- [ ] **Step 1: 运行 JavaScript 语法与定向测试**

Run: `node --check js/library_faces.js`

Run: `python -m pytest tests/test_ui_asset_library.py tests/test_spine_face_renderer.py tests/test_spine_face_analysis.py -vv`

- [ ] **Step 2: 运行完整测试**

Run: `python -m pytest`

Expected: 0 failures。

- [ ] **Step 3: 真实浏览器验证**

启动独立端口，打开骨骼表情标注工作区，拦截一次 job 请求为网络失败并确认页面自动恢复；检查桌面与移动视口无布局回归。

- [ ] **Step 4: 检查工作树**

Run: `git diff --check && git status --short --branch`

Expected: 无空白错误，仅保留预期提交。
