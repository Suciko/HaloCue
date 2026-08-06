# 双角色模型管理实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有“单一当前模型”配置改造成基础模型与可选图片识别模型分工，并提供三级模型管理 UI、旧配置迁移和可验证的降级行为。

**Architecture:** 在现有 `ModelProfileStore` 和 Windows 凭据存储之上增加连接、模型和用途分配的持久化层；用一个独立路由器为文字与视觉请求解析 Provider。前端保留当前设置抽屉和 vanilla JS 模式，但把第一层改为用途卡片，第二层改为按能力筛选的模型选择，第三层复用供应商预设和 API 表单。

**Tech Stack:** Python 3 stdlib HTTP server、JSON、Windows Credential Manager、vanilla JavaScript/CSS、pytest、Node UI harness。

## Global Constraints

- 基础模型必需，图片识别模型可选；纯文字请求只使用基础模型。
- 图片模型未配置时不阻塞文字任务、手动编辑、审查、编译和安装。
- 视觉调用失败不自动切换全局模型；用户必须明确选择重试、单次改用基础模型或手动处理。
- 能力状态以实际测试结果为准；`untested`、`passed`、`failed`、`unsupported` 不得混淆。
- API Key 不得进入 JSON、日志、公共 API 响应或错误信息，继续使用 Windows 凭据管理器。
- 主设置界面只展示名称、模型、能力、状态和短命令按钮；教程与协议解释只放帮助说明。
- 保留现有 `openai`、`anthropic` Provider 接口和 OpenAI-compatible 预设兼容性。
- 不加入用量统计、价格计算、自动最便宜模型选择、自动故障转移或第三种任务角色。

---

## 文件与边界

- `model_profiles.py`：新增 schema v2 的连接、模型、分配存储；保留旧 profile 读取和密钥兼容。
- `model_router.py`：新增纯文字/视觉路由和能力校验，隔离业务调用点对配置结构的依赖。
- `webui.py`：增加连接、模型、分配及迁移 API；将现有背景/表情视觉任务接到路由器；统一脱敏错误。
- `ui.html`、`css/layout.css`：将模型设置区域改为第一层用途总览与第二/三层面板容器，保证桌面和手机布局稳定。
- `js/model.js`：封装连接/模型/分配 payload、状态标签、筛选与脏状态判断。
- `js/app.js`：接入新的模型设置状态机、三级导航、保存/测试/分配动作和任务失败操作。
- `help` 内容所在 `ui.html` 区域：补充完整 API 接入说明，不把长说明放回设置卡片。
- `tests/test_model_profiles.py`：schema、密钥、引用保护、迁移测试。
- `tests/test_model_router.py`：路由策略与能力状态测试。
- `tests/test_web_model_profiles.py`：HTTP API、脱敏和未保存表单测试。
- `tests/test_ui_model_workbench.py`：Node harness 下的三级 UI、筛选、状态和降级动作测试。

## Task 1: Schema v2 与旧 Profile 迁移

**Files:**
- Modify: `model_profiles.py`
- Test: `tests/test_model_profiles.py`

**Interfaces:**
- Produce `ModelProfileStore.public_state()` with `connections`, `models`, `assignments`, `schema_version` while preserving a compatibility `profiles` projection during migration.
- Produce `ModelProfileStore.save_connection(payload) -> dict`, `save_model(payload) -> dict`, `set_assignments(payload) -> dict`, `delete_connection(id)`, `delete_model(id)`.
- Produce `ModelProfileStore.migrate_legacy_profiles() -> dict` as an idempotent transaction.
- Extend each `MODEL_PRESETS` record with `official_url` and `api_key_url`; these are public metadata returned to the help/connection UI.

- [ ] **Step 1: Write failing tests for v2 persistence and migration**

```python
def test_legacy_profile_migrates_to_connection_model_and_base_assignment(tmp_path):
    credentials = FakeCredentials()
    path = tmp_path / "llm_profiles.json"
    path.write_text(json.dumps({
        "version": 1,
        "active_profile_id": "profile-1",
        "profiles": [{
            "id": "profile-1", "name": "DeepSeek", "provider": "openai",
            "service_preset": "deepseek", "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat", "max_tokens": 16000, "vision": False,
        }],
    }), encoding="utf-8")
    credentials.write("AA-AutoWriter/profile-1", "secret")
    store = ModelProfileStore(path, credentials=credentials)
    state = store.migrate_legacy_profiles()
    assert state["schema_version"] == 2
    assert state["assignments"]["base_model_id"] == state["models"][0]["id"]
    assert state["connections"][0]["base_url"] == "https://api.deepseek.com/v1"

def test_migration_is_idempotent_and_keeps_secret(tmp_path):
    store = legacy_store_with_fake_credentials(tmp_path, api_key="secret")
    first = store.migrate_legacy_profiles()
    second = store.migrate_legacy_profiles()
    assert first == second
    assert store.resolve_connection_key(first["connections"][0]["id"]) == "secret"

def test_reject_delete_when_connection_or_model_is_referenced(tmp_path):
    store = v2_store_with_base_assignment(tmp_path)
    with pytest.raises(ModelProfileError, match="仍被使用"):
        store.delete_model("base-model")
```

- [ ] **Step 2: Run the focused tests and confirm they fail**

Run: `pytest tests/test_model_profiles.py -k "migrat or referenced" -v`

Expected: FAIL because v2 records and migration methods do not exist.

- [ ] **Step 3: Implement v2 state and compatibility helpers**

Add a `version: 2` state shape with independent arrays and an assignments object. Use the existing lock, atomic temp-file replacement and credential store. Keep secret targets deterministic (`AA-AutoWriter/connection/<id>`), and keep old profile targets readable until migration has completed. Validate connection protocol, URL, model name, max token limits, status enums and assignment references before writing. Add official/API-key URLs to every built-in preset and reject non-HTTP(S) public links.

- [ ] **Step 4: Run model profile tests**

Run: `pytest tests/test_model_profiles.py -v`

Expected: PASS, including all existing legacy tests and the new v2 tests.

- [ ] **Step 5: Commit the storage unit**

```bash
git add model_profiles.py tests/test_model_profiles.py
git commit -m "feat: add dual-role model profile storage"
```

## Task 2: Model Router And Capability State

**Files:**
- Create: `model_router.py`
- Test: `tests/test_model_router.py`

**Interfaces:**
- `ModelRouter(store).text_provider() -> Provider`.
- `ModelRouter(store).vision_provider() -> Provider | None`.
- `ModelRouter(store).vision_status() -> dict`.
- `ModelRouter(store).one_shot_base_fallback() -> Provider` validates `vision_status=passed` without changing assignments.

- [ ] **Step 1: Write failing routing tests**

```python
def test_text_always_uses_base_model(router, fake_provider_factory):
    router.store.set_assignments({"base_model_id": "deepseek-chat", "vision_mode": "disabled"})
    assert router.text_provider().model == "deepseek-chat"

def test_separate_vision_uses_vision_model(router):
    router.store.set_assignments({"base_model_id": "deepseek-chat", "vision_mode": "separate", "vision_model_id": "qwen-vl"})
    assert router.vision_provider().model == "qwen-vl"

def test_base_fallback_requires_passed_vision_status(router):
    router.store.set_assignments({"base_model_id": "deepseek-chat", "vision_mode": "base"})
    with pytest.raises(ModelProfileError, match="图片测试"):
        router.vision_provider()

def test_disabled_vision_returns_none_without_constructing_provider(router):
    router.store.set_assignments({"base_model_id": "deepseek-chat", "vision_mode": "disabled"})
    assert router.vision_provider() is None
```

- [ ] **Step 2: Run the tests to verify failure**

Run: `pytest tests/test_model_router.py -v`

Expected: FAIL because `model_router.py` is absent.

- [ ] **Step 3: Implement the router**

Resolve a model entry to its connection, load the connection secret through the store, and call the existing `llm.make_provider_from_settings(protocol, settings)`. Make `disabled` return `None`; make missing key and invalid references raise `ModelProfileError` with public-safe messages. Do not mutate assignments during one-shot fallback.

- [ ] **Step 4: Run router tests and existing provider tests**

Run: `pytest tests/test_model_router.py tests/test_llm_profile_provider.py -v`

Expected: PASS.

- [ ] **Step 5: Commit the router**

```bash
git add model_router.py tests/test_model_router.py
git commit -m "feat: route text and vision requests by role"
```

## Task 3: Backend Model Management APIs

**Files:**
- Modify: `webui.py`
- Test: `tests/test_web_model_profiles.py`

**Interfaces:**
- `GET /api/llm/workbench` returns redacted v2 state and preset metadata.
- `POST /api/llm/connections/save`, `/api/llm/models/save`, `/api/llm/assignments/save` persist validated payloads.
- `POST /api/llm/models/list` accepts a saved connection ID or unsaved connection payload.
- `POST /api/llm/models/test` accepts a model entry payload and `mode=text|vision`.
- `POST /api/llm/vision/fallback-test` performs a one-shot base-model vision test without changing assignments.
- Existing `annotation_provider()` becomes a compatibility wrapper over `ModelRouter.text_provider()`; callers no longer select an arbitrary profile ID.

- [ ] **Step 1: Add failing HTTP tests**

Add concrete request tests such as:

```python
def test_workbench_response_never_returns_connection_secret(model_server):
    status, result = request_json(model_server, "/api/llm/workbench")
    assert status == 200
    assert "api_key" not in json.dumps(result)

def test_assignment_rejects_untested_base_vision_model(model_server):
    status, result = request_json(model_server, "/api/llm/assignments/save", {
        "base_model_id": "model-text", "vision_mode": "base"
    })
    assert status == 400
    assert "图片测试" in result["e"]
```

Also cover unsaved connection testing, preset URL redaction, model list failure with manual-entry-safe error, text/vision test status updates, and error responses containing neither key nor absolute paths.

- [ ] **Step 2: Run focused HTTP tests and verify failure**

Run: `pytest tests/test_web_model_profiles.py -k "workbench orconnection orassignment orfallback" -v`

Expected: FAIL because the v2 endpoints are not registered.

- [ ] **Step 3: Implement API adapters**

Instantiate one `ModelRouter` from the global store. Register the new GET/POST routes beside existing `/api/llm/profiles` routes. Accept unsaved payloads for list/test by validating in memory. Return only labels, IDs, URLs, models and statuses. Wrap `ModelProfileError`, `CredentialStoreError` and `LLMError` through one sanitizer that removes credentials, bearer values, paths and stack traces.

- [ ] **Step 4: Route existing visual workers through `ModelRouter`**

Replace `annotation_provider()` internals and all pure-text preflight/annotation call sites with `router.text_provider()`. Replace `_optional_vision_provider()` use in background labeling and face labeling workers with `router.vision_provider()`. Preserve worker results and existing public error codes. Add an explicit one-shot fallback flag in the worker payload; it may call `one_shot_base_fallback()` only after user action. A failed visual call must keep render/non-visual results and expose `partial` plus retry/fallback/manual actions.

- [ ] **Step 5: Run backend tests**

Run: `pytest tests/test_web_model_profiles.py tests/test_story_asset_api.py tests/test_web_draft_endpoints.py -v`

Expected: PASS.

- [ ] **Step 6: Commit backend APIs**

```bash
git add webui.py tests/test_web_model_profiles.py
git commit -m "feat: expose dual-role model management APIs"
```

## Task 4: Three-Level Model Workbench UI

**Files:**
- Modify: `ui.html`, `css/layout.css`, `js/model.js`, `js/app.js`
- Create: `tests/test_ui_model_workbench.py`

**Interfaces:**
- `ModelSettings.workbenchPayload(document) -> {}` returns current assignment/connection/model form state.
- `ModelSettings.modelChanged(before, after) -> boolean` detects unsaved edits without treating an empty key as a change.
- `ModelSettings.filterModels(models, role, query, provider, status) -> []` filters by task role and test status.
- App actions: `open-model-role`, `choose-model`, `add-model`, `save-connection`, `save-model`, `test-model`, `save-assignments`, `one-shot-fallback`.

- [ ] **Step 1: Write failing Node harness tests**

Use the existing Node `vm` harness style to assert:

```javascript
const vision = ModelSettings.filterModels(models, 'vision', '', '', '');
console.log(JSON.stringify({
  roleCards: (html.match(/class="model-role-card/g) || []).length,
  visionIds: vision.map(item => item.id),
  passed: ModelSettings.statusLabel('vision', 'passed')
}));
```

The Python assertions require exactly two first-level role cards, no long tutorial paragraph in `#modelSettings`, role-filtered model IDs, and `图片已通过` for the status label. Runtime tests additionally verify “更换” opens the second layer, “添加模型” opens the third layer, and one-shot fallback does not mutate saved assignments.

- [ ] **Step 2: Run the harness tests and verify failure**

Run: `pytest tests/test_ui_model_workbench.py -v`

Expected: FAIL because the current UI still binds inputs directly to one profile.

- [ ] **Step 3: Implement model.js pure helpers**

Keep all DOM-independent transformations in `js/model.js`. Normalize v2 state, build connection/model/assignment payloads, map status enums to short Chinese labels, filter entries, and detect dirty forms. Add no provider/network calls to this file.

- [ ] **Step 4: Replace the model settings markup**

In `ui.html`, replace the current single profile form with role cards and hidden second/third layer panels. Use short labels and action verbs. Keep a compact `?` help button and move explanatory paragraphs into the existing help drawer section.

- [ ] **Step 5: Implement app state and actions**

Add a model workbench state object with `layer`, `role`, `selectedConnectionId`, `selectedModelId`, `assignments`, `connections`, `models`, `baseline`. Wire API calls to the new endpoints, preserve unsaved draft confirmation, and render loading/error/empty states without changing drawer width. On mobile, stack role cards and make all action buttons full-width where needed.

- [ ] **Step 6: Run UI tests and syntax checks**

Run: `pytest tests/test_ui_model_workbench.py tests/test_web_model_profiles.py -v` and `node --check js/model.js` and `node --check js/app.js`.

Expected: PASS with no syntax errors.

- [ ] **Step 7: Commit the UI unit**

```bash
git add ui.html css/layout.css js/model.js js/app.js tests/test_ui_model_workbench.py
git commit -m "feat: add compact dual-role model workbench"
```

## Task 5: Help Content And User-Facing State Copy

**Files:**
- Modify: `ui.html`, `README.md`, `使用说明-从这里开始.md`
- Test: `tests/test_ui_model_workbench.py`

- [ ] **Step 1: Add copy assertions**

Add exact scope assertions:

```python
def test_api_tutorial_copy_lives_in_help_not_model_settings():
    html = UI_HTML.read_text(encoding="utf-8")
    settings = html.split('id="modelSettings"', 1)[1].split('</section>', 1)[0]
    help_api = html.split('id="helpApiModels"', 1)[1].split('</section>', 1)[0]
    assert "基础模型" in settings and "图片识别模型" in settings
    assert "OpenAI-compatible 是什么" not in settings
    assert "单模型" in help_api and "双模型" in help_api
    assert "手动处理" in help_api
```

Also assert API-key link targets are generated from public preset metadata instead of duplicated constants in `ui.html`.

- [ ] **Step 2: Implement concise UI and detailed help copy**

Use only short labels in settings: `基础模型`、`图片识别模型`、`更换`、`添加模型`、`测试`、`使用`. Put registration, pricing and protocol guidance in help content with links from preset metadata.

- [ ] **Step 3: Run copy tests**

Run: `pytest tests/test_ui_model_workbench.py -k copy -v`

Expected: PASS.

- [ ] **Step 4: Commit documentation and copy**

```bash
git add ui.html README.md 使用说明-从这里开始.md tests/test_ui_model_workbench.py
git commit -m "docs: move API guidance into help"
```

## Task 6: Integration, Migration Safety And Release Verification

**Files:**
- Modify: `prepare_release.py`, `tests/test_llm_json.py`, `tests/test_web_setup_status.py`
- Test: full existing suite and new model tests

- [ ] **Step 1: Add migration and release checks**

Add tests that invoke preparation/setup helpers twice against a temporary legacy config:

```python
def test_release_migration_is_idempotent_and_setup_status_is_redacted(tmp_path, monkeypatch):
    store, credentials = legacy_store_with_fake_credentials(tmp_path, api_key="release-secret")
    monkeypatch.setattr(webui, "MODEL_PROFILES", store)
    store.migrate_legacy_profiles()
    store.migrate_legacy_profiles()
    state = store.public_state()
    status = webui.setup_status()
    assert len(state["connections"]) == len(state["models"]) == 1
    assert state["assignments"]["base_model_id"] == state["models"][0]["id"]
    assert "release-secret" not in json.dumps(state)
    assert "release-secret" not in json.dumps(status)
```

The release check also asserts the active model remains resolvable and setup readiness exposes only connection/model labels and role status.

- [ ] **Step 2: Run the focused complete model suite**

Run: `pytest tests/test_model_profiles.py tests/test_model_router.py tests/test_web_model_profiles.py tests/test_ui_model_workbench.py tests/test_llm_profile_provider.py tests/test_web_setup_status.py -v`

Expected: PASS.

- [ ] **Step 3: Run repository verification**

Run: `pytest -q`; `python -m compileall -q .`; `node --check js/model.js`; `node --check js/app.js`; `python prepare_release.py --help`.

Expected: all commands exit 0. Any unrelated pre-existing failure must be recorded with its exact test name and not masked.

- [ ] **Step 4: Perform browser QA at 1440px and 390px**

Start the existing web UI, open settings, verify first layer, drill into model selection, add a provider, test text and image, assign separate/base/disabled vision modes, and exercise missing-key and failed-vision actions. Capture exactly `output/playwright/model-workbench-1440.png` and `output/playwright/model-workbench-390.png`; inspect both for overflow, overlapping text and clipped buttons.

- [ ] **Step 5: Commit final verification notes**

```bash
git add docs/superpowers/plans/2026-08-06-dual-role-model-management.md output/playwright/model-workbench-1440.png output/playwright/model-workbench-390.png
git commit -m "test: verify dual-role model workbench"
```
