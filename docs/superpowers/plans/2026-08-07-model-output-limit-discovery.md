# Model Output Limit Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 根据模型接口的明确元数据或经过逐项核验的本地模型目录，自动填写模型最大输出，同时允许用户手动覆盖、保留覆盖状态并一键恢复推荐值。

**Architecture:** Provider 层保留 `/models` 的白名单能力字段，不再只返回 ID；独立 `model_capabilities.py` 负责精确模型/受控别名匹配和来源优先级；ModelProfileStore 持久化实际值与推荐来源；工作台在选择预制、自定义或已发现模型时统一应用推荐，并把手动编辑标记为 manual。运行模型调用只使用已保存数值，不在每次生成前抓网页。

**Tech Stack:** Python 3 标准库、OpenAI-compatible `/models`、Anthropic SDK model list、JSON profile store、原生 JavaScript、pytest、Node VM UI harness。

## Global Constraints

- 能力来源优先级固定为：当前连接 `/models` 的明确最大输出字段 > 本地已核验模型目录 > 保留当前值并标记“上限未识别”。
- `context_length` 只表示上下文窗口，永远不能回填为最大输出。
- 本地目录只接受供应商/模型官方资料或当前聚合连接自身的模型页/API；每条记录必须包含来源 URL、核对日期和匹配边界。
- 不使用不受控的子串匹配；只使用精确 ID、明确日期版本别名或 `fullmatch` 系列规则。
- 用户手动修改后，普通刷新和重新读取模型列表不得覆盖；选择另一个模型会重新解析，用户可点击“恢复推荐值”。
- 现有无来源元数据的保存记录标记为 `legacy`，不是 `manual`；首次获得可靠推荐时允许更新。
- 未找到可靠最大输出时不猜测、不使用上下文长度、不把旧 `16000` 包装成“推荐值”。
- Provider 或聚合服务的限制可能低于上游官方模型；因此远程 `/models` 明确值必须覆盖本地目录。
- API Key 继续只进入 Windows Credential Manager/当前内存，不写入能力目录、响应日志、文档或测试夹具。
- 保留当前脏工作区；每次提交只暂存本任务明确列出的文件。

## File Map

- Create `model_capabilities.py`: 远程模型记录归一化、本地已核验目录、精确/别名匹配和最终推荐解析。
- Create `tests/test_model_capabilities.py`: 远程字段优先级、上下文隔离、本地匹配、未知模型和来源信息测试。
- Create `docs/model-output-capability-sources.md`: 每个预制默认模型的逐项联网核验台账。
- Modify `llm.py`: `list_model_records()` 保留安全能力元数据，`list_models()` 继续作为只返回 ID 的兼容接口。
- Modify `model_profiles.py`: 保存 `max_tokens_source`、推荐值与推荐来源；迁移旧记录。
- Modify `webui.py`: 工作台模型列表返回能力对象，增加本地模型名推荐 API。
- Modify `ui.html`: 最大输出来源、手动状态和恢复推荐值命令。
- Modify `js/model.js`: 纯函数解析推荐状态和构造保存 payload。
- Modify `js/app.js`: 预制、发现列表、手动模型名和编辑值的交互。
- Modify `css/app.css`: 紧凑的来源/恢复行，不增加页面级卡片。
- Modify `tests/test_llm_profile_provider.py`: Provider 模型元数据兼容测试。
- Modify `tests/test_model_profiles.py`: 持久化和 legacy/manual 行为测试。
- Modify `tests/test_web_model_profiles.py`: 列表/推荐 API 契约。
- Modify `tests/test_ui_model_workbench.py`: 选择、手动覆盖、刷新和恢复推荐值行为。
- Modify `tests/ui_runtime_harness.js`: 注册新增 DOM 节点并支持 `input/change` 测试。

---

### Task 1: Verified Capability Ledger and Deterministic Resolver

**Files:**
- Create: `model_capabilities.py`
- Create: `tests/test_model_capabilities.py`
- Create: `docs/model-output-capability-sources.md`

**Interfaces:**
- Produces: `normalize_remote_model_record(item: Mapping[str, Any]) -> Dict[str, Any]`
- Produces: `resolve_output_capability(model_id: str, *, service_preset: str = "custom", remote_record: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]`
- Result: `{model_id, max_output_tokens, source, source_label, source_url, verified_at, context_length}`，其中 `source` 为 `api | catalog | unknown`。

- [ ] **Step 1: 逐个联网核验预制默认模型并写来源台账**

创建 `docs/model-output-capability-sources.md`，记录核对日期 `2026-08-07`、实际打开的页面、页面中的最大输出原文或“未明确披露”。至少逐项核验当前 `MODEL_PRESETS`：

| preset | 默认模型 | 首选来源 | 初始目录结论 |
|---|---|---|---|
| `openai` | `gpt-4o` | `https://developers.openai.com/api/docs/models/gpt-4o` | `16,384` |
| `anthropic` | `claude-sonnet-4-5` | `https://platform.claude.com/docs/en/about-claude/models/overview` | `64,000` |
| `gemini` | `gemini-2.5-flash` | `https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash` | `65,536` |
| `deepseek` | `deepseek-v4-flash` | `https://api-docs.deepseek.com/quick_start/pricing` | `384,000` |
| `glm` | `glm-4.6` | `https://docs.bigmodel.cn/cn/guide/models/text/glm-4.6` | `128,000` |
| `qwen` | `qwen-max` | `https://help.aliyun.com/zh/model-studio/getting-started/models` | 官方页面若仍未明确该旧别名的最大输出，则记录 `unknown`，依赖当前连接 `/models` |
| `moonshot` | `kimi-k2-0905-preview` | Moonshot 官方模型列表 | 只在页面明确给出最大输出时写数值，否则记录 `unknown` |
| `siliconflow` | `deepseek-ai/DeepSeek-V3` | SiliconFlow 当前模型详情 | 聚合连接限制必须由其页面或 `/models` 证明；不得直接套用上游 DeepSeek 值 |
| `openrouter` | `openai/gpt-4o-mini` | `https://openrouter.ai/openai/gpt-4o-mini` | 只使用 OpenRouter 页面明确的 max completion；当前预期 `16,384`，核对后落库 |
| `ollama` | `llama3.2` | `https://ollama.com/library/llama3.2` | 本地运行时输出上限可配置，没有固定明确值时记录 `unknown` |
| `custom` | 空 | 无 | `unknown`，由模型名目录匹配或 `/models` 决定 |

台账必须明确区分 `context window` 和 `max output/completion`。若页面只给上下文，结论必须是 `unknown`。不得把搜索摘要当证据，必须打开实际官方页面。

- [ ] **Step 2: 写出远程优先、本地匹配和未知回退的失败测试**

在 `tests/test_model_capabilities.py` 增加：

```python
import pytest

from model_capabilities import normalize_remote_model_record, resolve_output_capability


def test_remote_explicit_output_limit_beats_catalog():
    result = resolve_output_capability(
        "gpt-4o",
        service_preset="openai",
        remote_record={
            "id": "gpt-4o", "context_length": 128000,
            "max_completion_tokens": 8192,
        },
    )
    assert result["max_output_tokens"] == 8192
    assert result["source"] == "api"
    assert result["context_length"] == 128000


def test_context_length_is_never_used_as_output_limit():
    result = resolve_output_capability(
        "unlisted-model",
        remote_record={"id": "unlisted-model", "context_length": 1_000_000},
    )
    assert result["max_output_tokens"] is None
    assert result["source"] == "unknown"


@pytest.mark.parametrize("model_id,expected", [
    ("gpt-4o", 16384),
    ("gpt-4o-2024-11-20", 16384),
    ("gemini-2.5-flash", 65536),
    ("deepseek-v4-flash", 384000),
    ("glm-4.6", 128000),
])
def test_verified_catalog_matches_exact_models_and_bounded_aliases(model_id, expected):
    result = resolve_output_capability(model_id)
    assert result["max_output_tokens"] == expected
    assert result["source"] == "catalog"
    assert result["source_url"].startswith("https://")
    assert result["verified_at"] == "2026-08-07"


def test_similar_unknown_name_does_not_match_by_substring():
    result = resolve_output_capability("my-gpt-4o-wrapper-unverified")
    assert result["max_output_tokens"] is None
    assert result["source"] == "unknown"
```

核验台账若确认了 Anthropic/OpenRouter 或其他数值，再为每个数值增加同样的精确断言；台账结论为 unknown 的模型必须增加 `is None` 断言。

- [ ] **Step 3: 运行测试并确认模块尚不存在**

Run: `python -m pytest tests/test_model_capabilities.py -q`

Expected: FAIL with `ModuleNotFoundError: model_capabilities`。

- [ ] **Step 4: 实现只读取明确输出字段的远程归一化**

```python
OUTPUT_LIMIT_PATHS = (
    ("max_completion_tokens",),
    ("max_output_tokens",),
    ("output_token_limit",),
    ("top_provider", "max_completion_tokens"),
)


def _positive_int(value):
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def normalize_remote_model_record(item):
    model_id = str(item.get("id") or "").strip()
    record = {
        "id": model_id,
        "context_length": _positive_int(item.get("context_length")),
        "max_output_tokens": None,
    }
    for path in OUTPUT_LIMIT_PATHS:
        value = item
        for key in path:
            value = value.get(key) if isinstance(value, dict) else None
        parsed = _positive_int(value)
        if parsed is not None:
            record["max_output_tokens"] = parsed
            record["max_output_field"] = ".".join(path)
            break
    return record
```

白名单之外的远程字段不回传浏览器；特别是 pricing、owner、description 和任意嵌套供应商私有数据不参与推断。

- [ ] **Step 5: 实现带来源、日期和边界的本地目录**

目录记录采用不可变 tuple/dict，精确模型优先，别名只允许 `re.fullmatch()`：

```python
VERIFIED_MODEL_CAPABILITIES = (
    {
        "service_presets": ("openai", "custom"),
        "patterns": (r"gpt-4o", r"gpt-4o-\d{4}-\d{2}-\d{2}"),
        "max_output_tokens": 16384,
        "source_url": "https://developers.openai.com/api/docs/models/gpt-4o",
        "verified_at": "2026-08-07",
    },
    {
        "service_presets": ("gemini", "custom"),
        "patterns": (r"gemini-2\.5-flash",),
        "max_output_tokens": 65536,
        "source_url": "https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash",
        "verified_at": "2026-08-07",
    },
    {
        "service_presets": ("deepseek", "custom"),
        "patterns": (r"deepseek-v4-flash",),
        "max_output_tokens": 384000,
        "source_url": "https://api-docs.deepseek.com/quick_start/pricing",
        "verified_at": "2026-08-07",
    },
    {
        "service_presets": ("glm", "custom"),
        "patterns": (r"glm-4\.6",),
        "max_output_tokens": 128000,
        "source_url": "https://docs.bigmodel.cn/cn/guide/models/text/glm-4.6",
        "verified_at": "2026-08-07",
    },
)
```

把 Step 1 核验通过的其余数值按同样结构加入；unknown 只写在来源台账和测试中，不加入带数值目录。`resolve_output_capability()` 必须先用 remote explicit value，再按 preset-scoped exact/fullmatch 目录解析，最后返回 `source="unknown"`。

- [ ] **Step 6: 运行 resolver 测试并审查来源完整性**

Run: `python -m pytest tests/test_model_capabilities.py -q`

Run: `rg -n "context_length.*max_output|max_output.*context_length|TBD|TODO" model_capabilities.py docs/model-output-capability-sources.md`

Expected: pytest PASS；rg 不出现上下文回填逻辑、`TBD` 或 `TODO`。每个数值记录都有 URL 和日期。

- [ ] **Step 7: 提交能力目录**

```bash
git add model_capabilities.py tests/test_model_capabilities.py docs/model-output-capability-sources.md
git commit -m "feat: add verified model output capability catalog"
```

---

### Task 2: Preserve Safe `/models` Metadata Without Breaking ID Callers

**Files:**
- Modify: `llm.py:105-440`
- Modify: `tests/test_llm_profile_provider.py`

**Interfaces:**
- Produces: `Provider.list_model_records() -> List[Dict[str, Any]]`
- Preserves: `Provider.list_models() -> List[str]` derives sorted IDs from records for legacy callers.
- Each record is normalized to `id`, `context_length`, `max_output_tokens`, `max_output_field` only.

- [ ] **Step 1: 写出 Token Rhythm 风格元数据和旧 ID 接口失败测试**

```python
def test_openai_model_discovery_preserves_output_metadata(monkeypatch):
    monkeypatch.setattr(
        llm,
        "urlopen",
        lambda request, timeout: FakeHttpResponse({"data": [
            {
                "id": "deepseek-v4-flash",
                "context_length": 1_000_000,
                "max_completion_tokens": 384_000,
                "pricing": {"prompt": "private-shape-not-forwarded"},
            },
            {"id": "unknown", "context_length": 128_000},
        ]}),
        raising=False,
    )
    provider = llm.OpenAIProvider({"api_key": "secret", "model": "chosen"})

    records = provider.list_model_records()

    assert records[0] == {
        "id": "deepseek-v4-flash", "context_length": 1_000_000,
        "max_output_tokens": 384_000,
        "max_output_field": "max_completion_tokens",
    }
    assert "pricing" not in records[0]
    assert provider.list_models() == ["deepseek-v4-flash", "unknown"]
```

- [ ] **Step 2: 运行测试并确认当前接口丢弃所有能力字段**

Run: `python -m pytest tests/test_llm_profile_provider.py -k "model_discovery" -q`

Expected: `list_model_records()` 不存在；当前 `list_models()` 只保留 ID。

- [ ] **Step 3: 在 Provider 基类增加兼容接口**

```python
def list_model_records(self):
    raise LLMError(f"{self.name} 接口不支持读取模型列表")

def list_models(self):
    return sorted({
        str(record.get("id") or "")
        for record in self.list_model_records()
        if str(record.get("id") or "")
    })
```

OpenAI Provider 对 `/models.data` 每项调用 `normalize_remote_model_record()`；Anthropic Provider 将 SDK 对象安全转换成至少 `{"id": str(getattr(item, "id", ""))}`，只有 SDK 明确提供同名输出字段时才加入数值。

- [ ] **Step 4: 避免兼容接口造成第二次联网**

测试不得在同一断言中先调用 `list_model_records()` 再调用 `list_models()` 却只准备一次 fake response。生产 UI 只调用 records 接口一次；旧调用者调用 `list_models()` 时自行发一次请求。不要为模型列表引入跨连接全局缓存。

- [ ] **Step 5: 运行 Provider 全部测试**

Run: `python -m pytest tests/test_llm_profile_provider.py -q`

Expected: PASS；旧 ID 排序/去重契约保留，元数据被白名单化保留。

- [ ] **Step 6: 提交模型列表元数据支持**

```bash
git add llm.py tests/test_llm_profile_provider.py
git commit -m "feat: preserve model output metadata"
```

---

### Task 3: Persist Recommended, Legacy, and Manual Output-Limit State

**Files:**
- Modify: `model_profiles.py:300-520`
- Modify: `tests/test_model_profiles.py`
- Modify: `tests/test_llm_profile_provider.py`

**Interfaces:**
- Model record adds: `max_tokens_source`, `recommended_max_tokens`, `recommended_source`, `recommended_label`。
- `max_tokens_source` allowed values: `legacy | api | catalog | unknown | manual`。
- Runtime provider settings remain `{model, base_url, max_tokens, vision, api_key}`；推荐元数据不进入模型请求。

- [ ] **Step 1: 写出保存、迁移和手动覆盖失败测试**

```python
def test_model_store_persists_output_recommendation_and_manual_override(tmp_path):
    store = ModelProfileStore(tmp_path / "profiles.json", credentials=FakeCredentials())
    connection = store.save_connection({
        "name": "Token Rhythm", "protocol": "openai", "service_preset": "custom",
        "base_url": "https://tokenrhythm.studio/v1", "api_key": "secret",
    })
    recommended = store.save_model({
        "connection_id": connection["id"], "model": "deepseek-v4-flash",
        "max_tokens": 384000, "max_tokens_source": "api",
        "recommended_max_tokens": 384000, "recommended_source": "api",
        "recommended_label": "接口返回 · 384,000",
    })
    manual = store.save_model({**recommended, "max_tokens": 120000, "max_tokens_source": "manual"})

    assert manual["max_tokens"] == 120000
    assert manual["max_tokens_source"] == "manual"
    assert manual["recommended_max_tokens"] == 384000
    assert store.provider_settings_for_model(manual["id"])[1]["max_tokens"] == 120000


def test_v2_record_without_source_is_loaded_as_legacy(tmp_path):
    # 写入一个当前 schema_version=2、但没有新来源字段的完整状态。
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps({
        "version": 2,
        "active_profile_id": "",
        "profiles": [],
        "connections": [{
            "id": "connection-legacy",
            "name": "Legacy connection",
            "service_preset": "custom",
            "protocol": "openai",
            "base_url": "https://example.invalid/v1",
        }],
        "models": [{
            "id": "model-legacy",
            "connection_id": "connection-legacy",
            "model": "legacy-model",
            "max_tokens": 16000,
            "text_status": "untested",
            "vision_status": "unsupported",
        }],
        "assignments": {
            "base_model_id": "model-legacy",
            "vision_mode": "disabled",
            "vision_model_id": "",
        },
    }), encoding="utf-8")

    store = ModelProfileStore(path, credentials=FakeCredentials())
    state = store.public_state()

    assert state["schema_version"] == 2
    assert state["models"][0]["max_tokens"] == 16000
    assert state["models"][0]["max_tokens_source"] == "legacy"
```

第二个测试使用现有 `_empty_state()`/保存结构写出完整 JSON，不使用省略号；必须包括一条 connection、model 和 assignments，使迁移路径与真实文件一致。测试文件顶部需要保留 `import json`。

- [ ] **Step 2: 运行测试并确认当前 store 丢弃来源状态**

Run: `python -m pytest tests/test_model_profiles.py tests/test_llm_profile_provider.py -k "recommendation or manual_override or legacy" -q`

Expected: 新字段未被 `_validated_model()` 保存，provider settings helper 尚不保留相应实际值测试契约。

- [ ] **Step 3: 扩展 `_validated_model()` 的严格校验**

```python
_MAX_TOKEN_SOURCES = {"legacy", "api", "catalog", "unknown", "manual"}
_RECOMMENDATION_SOURCES = {"api", "catalog", "unknown"}

source = str(payload.get("max_tokens_source") or "legacy")
if source not in _MAX_TOKEN_SOURCES:
    raise ModelProfileError("最大输出来源状态无效")
raw_recommended = payload.get("recommended_max_tokens")
recommended = None if raw_recommended in (None, "") else int(raw_recommended)
if recommended is not None and not 1 <= recommended <= 1_000_000:
    raise ModelProfileError("recommended_max_tokens 必须在 1 到 1000000 之间")
recommended_source = str(payload.get("recommended_source") or "unknown")
if recommended_source not in _RECOMMENDATION_SOURCES:
    raise ModelProfileError("推荐来源无效")
```

`recommended_label` 截断到 120 字符并作为纯显示文本；不得保存远程原始对象。

- [ ] **Step 4: 定义旧记录迁移语义**

`_load()`/`_public_v2_state()` 在读到缺少新字段的 model 时，内存归一化为：

```python
{
    "max_tokens_source": "legacy",
    "recommended_max_tokens": None,
    "recommended_source": "unknown",
    "recommended_label": "上限未识别",
}
```

不因单纯读取配置而写文件；下次用户保存模型时才写入新字段。旧 `16000` 不是 manual，因此模型发现拿到 API/catalog 推荐后可以替换。

- [ ] **Step 5: 运行 store、router 和 Web profile 回归**

Run: `python -m pytest tests/test_model_profiles.py tests/test_llm_profile_provider.py tests/test_model_router.py tests/test_web_model_profiles.py -q`

Expected: PASS；模型调用只读取实际 `max_tokens`，推荐元数据不影响路由和密钥隔离。

- [ ] **Step 6: 提交持久化模型**

```bash
git add model_profiles.py tests/test_model_profiles.py tests/test_llm_profile_provider.py
git commit -m "feat: persist model output limit provenance"
```

---

### Task 4: Capability-Aware Workbench APIs

**Files:**
- Modify: `webui.py:1183-1200,4630-4665`
- Modify: `tests/test_web_model_profiles.py`

**Interfaces:**
- `POST /api/llm/models/list` returns `models: List[CapabilityResult]` rather than bare strings.
- Add `POST /api/llm/models/recommend` with `{model, service_preset}` and no secret requirement.
- Preserve `/v1` fallback fields: `base_url`, `base_url_adjusted`。

- [ ] **Step 1: 写出远程元数据、本地推荐和上下文隔离 API 失败测试**

```python
def test_workbench_model_list_prefers_remote_output_metadata(tmp_path, monkeypatch):
    class FakeProvider:
        def list_model_records(self):
            return [{
                "id": "deepseek-v4-flash", "context_length": 1_000_000,
                "max_output_tokens": 384_000,
                "max_output_field": "max_completion_tokens",
            }]

    monkeypatch.setattr(
        llm, "make_provider_from_settings", lambda _name, _settings: FakeProvider()
    )
    # 通过现有 model_server 请求 /api/llm/models/list。
    assert result["models"] == [{
        "model_id": "deepseek-v4-flash",
        "context_length": 1_000_000,
        "max_output_tokens": 384_000,
        "source": "api",
        "source_label": "接口返回 · 384,000",
        "source_url": "",
        "verified_at": "",
    }]


def test_local_recommendation_endpoint_matches_custom_model_name(tmp_path, monkeypatch):
    status, result = request_json(base, "/api/llm/models/recommend", {
        "model": "gpt-4o-2024-11-20", "service_preset": "custom",
    })
    assert status == 200
    assert result["max_output_tokens"] == 16384
    assert result["source"] == "catalog"
```

另加 unknown 模型测试，断言 response 的 `max_output_tokens is None`，即使 fake record 有 `context_length=1_000_000`。

- [ ] **Step 2: 运行 Web API 测试并确认返回仍是字符串列表**

Run: `python -m pytest tests/test_web_model_profiles.py -k "model_list or recommendation" -q`

Expected: `/models/list` 仍返回 bare strings，`/models/recommend` 不存在。

- [ ] **Step 3: 在 `list_workbench_models()` 统一解析每条记录**

```python
def _resolved_model_records(provider, service_preset):
    return [
        model_capabilities.resolve_output_capability(
            record["id"],
            service_preset=service_preset,
            remote_record=record,
        )
        for record in provider.list_model_records()
    ]
```

`list_workbench_models()` 使用 connection 的 `service_preset`，并在 `/v1` fallback 后对第二个 Provider 做同样处理。结果按 `model_id.casefold()` 排序和去重。

- [ ] **Step 4: 增加无密钥、无联网的本地推荐路由**

`/api/llm/models/recommend` 只调用 `resolve_output_capability(model, service_preset="custom")`（实际请求使用表单传入的 preset）；不构造 Provider、不读取 Credential Manager、不访问网络。空模型名返回 400 `模型名称不能为空`。

- [ ] **Step 5: 运行 Web profile 全部回归**

Run: `python -m pytest tests/test_web_model_profiles.py tests/test_web_setup_status.py -q`

Expected: PASS；错误响应不含密钥/绝对路径；`/v1` 自动补全行为保留。

- [ ] **Step 6: 提交能力 API**

```bash
git add webui.py tests/test_web_model_profiles.py
git commit -m "feat: return model output recommendations"
```

---

### Task 5: Auto-Fill, Manual Override, and Restore in the Model Workbench

**Files:**
- Modify: `ui.html:80`
- Modify: `css/app.css`
- Modify: `js/model.js:1-145`
- Modify: `js/app.js:1095-1125,1260-1375,2250-2290`
- Modify: `tests/test_ui_model_workbench.py`
- Modify: `tests/ui_runtime_harness.js`

**Interfaces:**
- `#modelMaxTokens` dataset stores `source`, `recommended`, `recommendationSource`, `recommendationLabel`。
- Add visible `#modelMaxTokensHint` and command `data-action="restore-model-max-tokens"`。
- `ModelSettings.profilePayload(document)` emits persisted provenance fields.
- `ModelSettings.nextOutputLimitState(current, capability, options) -> object` is pure and unit-tested.

- [ ] **Step 1: 写出纯状态转换失败测试**

在 `tests/test_ui_model_workbench.py` 的 Node 脚本中测试：

```javascript
const api=sandbox.window.ModelSettings;
const capability={max_output_tokens:384000,source:'api',source_label:'接口返回 · 384,000'};
console.log(JSON.stringify({
 selected:api.nextOutputLimitState({value:16000,source:'legacy'},capability,{modelChanged:true}),
 refreshed:api.nextOutputLimitState({value:120000,source:'manual',recommended:384000},capability,{modelChanged:false}),
 restored:api.restoreOutputLimitState({value:120000,source:'manual',recommended:384000,recommendationSource:'api',recommendationLabel:'接口返回 · 384,000'}),
 unknown:api.nextOutputLimitState({value:16000,source:'legacy'},{max_output_tokens:null,source:'unknown',source_label:'上限未识别'},{modelChanged:true})
}));
```

断言：selected 自动变 `384000/api`；refreshed 保持 `120000/manual`；restored 回到 `384000/api`；unknown 保留 `16000` 但来源变 `unknown`。

- [ ] **Step 2: 写出真实工作台交互失败测试**

扩展发现列表测试，使 API 返回能力对象。验证：

- 选择 `deepseek-v4-flash` 后名称和最大输出同时变为 `384000`，提示为 `接口返回 · 384,000`。
- 用户触发 `#modelMaxTokens` 的 `input` 后提示变 `手动设置`。
- 再次读取同一模型列表不覆盖手动值。
- 点击 `restore-model-max-tokens` 恢复 `384000`。
- 选择另一个有 catalog 推荐的模型会应用新值。
- 手工输入自定义 `gpt-4o` 并触发 `change` 时调用 `/api/llm/models/recommend`。
- 保存 payload 包含 actual/source/recommended 字段，且不改变 API Key 清空行为。

- [ ] **Step 3: 运行 UI 测试并确认 bare-string 渲染和固定 16000 默认失败**

Run: `python -m pytest tests/test_ui_model_workbench.py -k "output or discovered or saving" -q`

Expected: 当前 UI 把对象显示成 `[object Object]`，不会更新最大输出或记录 manual 状态。

- [ ] **Step 4: 实现纯推荐状态函数和保存 payload**

在 `js/model.js` 增加：

```javascript
function nextOutputLimitState(current, capability, options) {
  current = current || {}; capability = capability || {}; options = options || {};
  const recommended = Number(capability.max_output_tokens || 0) || null;
  if (!recommended) return Object.assign({}, current, {
    source: current.source === 'manual' ? 'manual' : 'unknown',
    recommended: null, recommendationSource: 'unknown',
    recommendationLabel: capability.source_label || '上限未识别'
  });
  if (current.source === 'manual' && !options.modelChanged) return Object.assign({}, current, {
    recommended: recommended,
    recommendationSource: capability.source,
    recommendationLabel: capability.source_label
  });
  return {
    value: recommended, source: capability.source,
    recommended: recommended, recommendationSource: capability.source,
    recommendationLabel: capability.source_label
  };
}
```

`profilePayload()` 从 input dataset 生成：

```javascript
max_tokens_source: maxInput.dataset.source || 'legacy',
recommended_max_tokens: Number(maxInput.dataset.recommended || 0) || null,
recommended_source: maxInput.dataset.recommendationSource || 'unknown',
recommended_label: maxInput.dataset.recommendationLabel || '上限未识别'
```

- [ ] **Step 5: 改造发现列表、预制和手动模型名路径**

`renderDiscoveredModels()` 将每项标准化为 `{model_id, max_output_tokens, source, source_label, source_url, verified_at, context_length}`，按钮的 `textContent` 只显示 ID，并将完整对象保存到当前 `state.discoveredModelCapabilities`，不放进 DOM attribute。

`chooseDiscoveredModel()` 比较旧模型名以设置 `modelChanged`，调用统一 `applyOutputCapability()`。`applyModelPreset()` 在填入默认模型后调用本地推荐 API。`#modelName change` 先查本次发现结果，找不到时请求 `/api/llm/models/recommend`。

`#modelMaxTokens input` 只设置 `dataset.source='manual'`，保留 recommended 数据。普通发现刷新相同模型时 manual 不变。

- [ ] **Step 6: 增加紧凑来源提示和恢复命令**

在现有“最大输出” field 内增加一行：

```html
<div class="model-limit-meta">
  <span id="modelMaxTokensHint">上限未识别</span>
  <button class="text-command" type="button" data-action="restore-model-max-tokens" hidden>恢复推荐值</button>
</div>
```

只在 `source=manual` 且有 recommended 值时显示恢复按钮。不要新增说明卡片或长段帮助文本；数字使用 locale 分隔符，input 仍保存纯整数。

- [ ] **Step 7: 运行 UI、HTML 和 syntax 回归**

Run: `python -m pytest tests/test_ui_model_workbench.py tests/test_ui_workbench.py tests/test_ui_polish_contract.py tests/test_web_model_profiles.py -q`

Run: `node --check js/model.js`

Run: `node --check js/app.js`

Expected: PASS；最长来源文字在窄宽度换行不遮挡 input/按钮；选择、manual、刷新和恢复行为符合契约。

- [ ] **Step 8: 提交工作台交互**

```bash
git add ui.html css/app.css js/model.js js/app.js tests/test_ui_model_workbench.py tests/ui_runtime_harness.js
git commit -m "feat: auto-fill model output limits"
```

---

### Task 6: Regression, Live Metadata Check, and Source Audit

**Files:**
- Verify only

**Interfaces:**
- Live check consumes the already authorized Token Rhythm base URL and API key from process memory/environment only.
- No completion request is required for this plan; `/models` metadata is sufficient.

- [ ] **Step 1: 运行全部模型配置定向测试**

Run:

```powershell
python -m pytest tests/test_model_capabilities.py tests/test_llm_profile_provider.py tests/test_model_profiles.py tests/test_model_router.py tests/test_web_model_profiles.py tests/test_ui_model_workbench.py tests/test_ui_workbench.py -q
```

Expected: PASS。

- [ ] **Step 2: 用授权连接读取一次真实 `/models` 元数据**

密钥只放当前进程环境变量，运行一个不打印请求 headers 的短命令或测试入口。验证 `deepseek-v4-flash` 的结果：

```json
{
  "model_id": "deepseek-v4-flash",
  "context_length": 1000000,
  "max_output_tokens": 384000,
  "source": "api"
}
```

不得把实际 API Key、完整 `/models` 原始响应或 Authorization 写入文件。若真实字段名变化，只把字段名和脱敏数字形状加入 fixture。

- [ ] **Step 3: 手工验收四条工作台路径**

1. 新建 Token Rhythm 自定义连接并读取模型，选择 `deepseek-v4-flash`，显示 `384,000` 和 `接口返回`。
2. 把值改为 `120000`，重新读取模型，值保持且显示 `手动设置`。
3. 点击恢复，回到 `384000`。
4. 选择没有明确上限的模型，只显示 `上限未识别`，不把 context length 填入 input。

- [ ] **Step 4: 运行全量回归和静态检查**

Run: `python -m pytest -q`

Run: `Get-ChildItem js\*.js | ForEach-Object { node --check $_.FullName }`

Run: `python -m compileall -q .`

Run: `git diff --check`

Expected: 全部通过。

- [ ] **Step 5: 审计来源和秘密隔离**

Run: `rg -n "sk_|Authorization|api_key" model_capabilities.py docs/model-output-capability-sources.md tests/test_model_capabilities.py`

Expected: 不包含真实密钥或 Authorization；测试中如需字段名只能使用固定假值 `secret`。

逐行检查台账：每个预制默认模型都有“明确数值”或“官方未明确，因此 unknown”的结论，没有只给 context window 却填写 output 的记录。

## Completion Gate

只有以下条件全部满足，才可以宣称本计划完成：

- Token Rhythm `/models` 的 `max_completion_tokens=384000` 能自动填入 `deepseek-v4-flash`。
- `context_length=1000000` 只显示为上下文信息，绝不成为最大输出。
- 预制默认模型已经逐个打开官方来源核验，数值/unknown 结论写入台账。
- 自定义连接中输入或选择已知模型名时，本地目录可按精确 ID/受控别名匹配。
- manual 值经刷新后保持，切换模型重新解析，恢复命令回到推荐值。
- 旧配置未被误标为 manual，未知模型未被伪造为 `16000` 推荐。
- 模型运行继续只使用保存的 `max_tokens`，生成前不联网抓文档。
- 定向测试、全量 pytest、JS syntax check 和一次授权 `/models` 实测通过。
