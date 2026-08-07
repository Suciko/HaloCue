# Model Profile Workbench Implementation Plan

> **For agentic workers:** Execute this plan task-by-task with tests before implementation.

**Goal:** 修复模型配置工作台的新建、保存、切换和测试流程，并支持主流 OpenAI-compatible 服务预设。

**Architecture:** 扩展 `ModelProfileStore` 的协议/预设元数据与保存校验；后端增加基于任意表单配置的模型测试入口；前端将 saved profile 与 draft profile 分离并实现脏状态确认。

**Tech Stack:** Python stdlib HTTP server, JSON profile store, Windows Credential Manager, vanilla JavaScript, pytest, Node syntax tests.

## Global Constraints

- 不把 API Key 写入 JSON、日志或公共 API 响应。
- 保留现有 `openai`/`anthropic` Provider 接口兼容性。
- OpenAI-compatible 预设只提供默认值，用户可以覆盖地址和模型。
- 配置保存允许 `missing` 密钥，但实际模型调用必须拒绝缺密钥。
- 不回滚工作区已有的用户修改。

### Task 1: Provider Presets And Store Validation

**Files:** `model_profiles.py`, `tests/test_model_profiles.py`

- [ ] 写测试：预设包含 DeepSeek、GLM、千问且保存后保留 `service_preset`；新建无 key 可保存；非法 URL/负输出限制被拒绝。
- [ ] 运行目标测试确认失败。
- [ ] 实现预设常量、`service_preset` 字段、允许保存 missing key、字段校验。
- [ ] 运行目标测试确认通过。

### Task 2: Backend Form Testing API

**Files:** `webui.py`, `tests/test_web_model_profiles.py`

- [ ] 写测试：`/api/llm/test` 和 `/api/llm/models` 接受完整表单 settings，不要求 profile 已保存，且错误只返回脱敏信息。
- [ ] 运行目标测试确认失败。
- [ ] 实现 payload 校验、临时 Provider 构造和统一错误响应。
- [ ] 运行目标测试确认通过。

### Task 3: Frontend Draft Lifecycle

**Files:** `ui.html`, `js/model.js`, `js/app.js`, `tests/test_web_model_profiles.py`, UI harness tests

- [ ] 写测试：点击新建后生成空 draft；保存使用 draft；切换脏表单要求确认；预设填充字段。
- [ ] 运行目标测试确认失败。
- [ ] 实现 draft state、dirty detection、save/discard/cancel flow、preset selector 和字段提示。
- [ ] 运行目标测试确认通过。

### Task 4: Output Budget And Documentation

**Files:** `llm.json.example`, `llm.py`, `annotate.py`, `docs/commands.md`, `README.md`

- [ ] 写测试：`finish_reason=length` 错误包含模型、输出上限和可执行建议；配置中的 Agent limits 独立于 `max_tokens`。
- [ ] 运行目标测试确认失败。
- [ ] 实现诊断、默认值和文档。
- [ ] 运行全量 pytest、Node 检查、compileall、prepare_release。
