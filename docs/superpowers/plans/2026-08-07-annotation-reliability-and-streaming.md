# Annotation Reliability and Streaming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让审查草稿生成在可选状态字段出现安全 `null` 时继续完成，正确区分容量错误与内容错误，避免隐藏重复调用和无效缩块，并把每次模型请求的首段、持续输出、重试、缩块、用量与缓存状态实时暴露给用户。

**Architecture:** 保留现有有状态 Annotation Agent、逐行身份协议、检查点和草稿格式。Provider 层负责真实流式接收、完成原因、usage 和细粒度活动事件；Agent 层负责协议归一化、错误分类、一次纠正及任务内安全块大小；Job/Web UI 只消费结构化活动字段，不解析中文进度字符串。

**Tech Stack:** Python 3 标准库、Anthropic Python SDK、OpenAI-compatible SSE、原生 JavaScript、pytest、Node VM UI harness。

## Global Constraints

- 不重写有状态 Agent、剧情记忆、逐行身份协议、检查点格式或审查草稿结构。
- `state_delta` 中的 `null` 仅表示“不更新该状态字段”；台词标注、`source_id`、`text_fingerprint`、事件、beats 和资源约束继续严格拒绝 `null`、缺失、重复、未知值和错误类型。
- 只有容量错误可以缩块；内容/协议错误最多进行一次同尺寸纠正，再失败时立即保留检查点并返回具体错误。
- 不把半截 JSON、原始流式 JSON、提示词、Authorization 头或 API Key 写入 Job、日志、检查点和测试夹具。
- 流式功能必须向后兼容只实现 `complete_json()` 的测试 Provider 和第三方 Provider。
- 缓存字段未上报时必须显示“未报告”，不得显示成 `0%`。
- 六位数 `max_tokens` 不是本计划的提速手段；单场景块固有延迟继续由独立性能债文档跟踪。
- 保留当前脏工作区；每次提交只暂存本任务明确列出的文件。

## File Map

- `llm.py`: 结构化输出错误类型、真实 Provider 流式入口、SSE/Anthropic delta 拼接、usage 与缓存统计。
- `annotation_protocol.py`: 仅对 `state_delta` 开放并归一化安全 `null`，继续执行状态类型和身份协议校验。
- `annotation_agent.py`: 错误分类、一次纠正、容量缩块、任务内安全块上限、模型活动转发和最终指标。
- `annotate.py`: 将 `model_activity` 回调从工作流选项传给 Agent，并保留 Agent metrics。
- `jobs.py`: 线程安全地保存结构化 `activity`。
- `webui.py`: 将 Agent/Provider 活动写入 Job，并将完成指标返回浏览器。
- `js/app.js`: 根据结构化活动显示等待首段、接收中、纠正、缩块和完成摘要。
- `tests/test_annotation_protocol.py`: 安全 `null` 与严格字段回归。
- `tests/test_llm_profile_provider.py`: 隐藏重发、流式拼接、完成原因和缓存字段回归。
- `tests/test_annotation_agent.py`: 分类、重试、缩块、检查点和任务内自适应上限回归。
- `tests/test_annotation_agent_scale.py`: 240 行严格覆盖和请求规模回归。
- `tests/test_jobmanager.py`: Job activity 的并发安全与序列化。
- `tests/test_web_draft_endpoints.py`: Web worker 活动和完成 metrics 契约。
- `tests/test_ui_runtime_behavior.py`: 用户可见流式状态和缓存摘要。
- `tests/ui_runtime_harness.js`: 如测试需要，补足 Job activity 所需的 DOM/runtime 能力。
- `tools/smoke_annotation_stream.py`: 显式环境变量门控、输出脱敏的小型真实接口冒烟工具。

---

### Task 1: Optional State Null Compatibility Without Protocol Relaxation

**Files:**
- Modify: `llm.py:20-72`
- Modify: `annotation_protocol.py:10-205`
- Modify: `tests/test_llm_json.py`
- Modify: `tests/test_annotation_protocol.py`

**Interfaces:**
- Consumes: `build_chunk_schema(target_ids: Sequence[str]) -> Dict[str, Any]`
- Produces: `_validate_schema_value()` 支持 JSON Schema `type: [<base>, "null"]`；`_validate_state_delta(value: Any) -> Dict[str, Any]` 删除值为 `None` 的已知状态字段。
- Invariant: `validate_chunk_response()` 的台词覆盖、指纹、事件证据和 beats 校验行为不变。

- [ ] **Step 1: 写出仅允许状态增量为 null 的失败测试**

在 `tests/test_annotation_protocol.py` 增加：

```python
@pytest.mark.parametrize("field", [
    "background", "place", "bgfx", "visible_characters", "positions",
    "last_faces", "recent_emoticons", "recent_actions", "recent_sounds",
    "open_threads",
])
def test_optional_state_null_means_no_update(field):
    response = complete_response()
    response["state_delta"] = {field: None}

    validated = validate_chunk_response(response, TARGETS)

    assert validated["state_delta"] == {}


@pytest.mark.parametrize("field,value", [
    ("background", []),
    ("visible_characters", "凯伊"),
    ("positions", []),
])
def test_state_delta_still_rejects_wrong_non_null_types(field, value):
    response = complete_response()
    response["state_delta"] = {field: value}

    with pytest.raises(ChunkProtocolError) as error:
        validate_chunk_response(response, TARGETS)

    assert error.value.code == "invalid_state_delta"
```

在 `tests/test_llm_json.py` 增加一个 schema 级测试，证明只有声明了联合类型的字段接受 `None`，台词字段仍失败：

```python
def test_schema_type_union_accepts_only_declared_null():
    schema = {
        "type": "object",
        "properties": {
            "state": {"type": ["string", "null"]},
            "source_id": {"type": "string"},
        },
        "required": ["state", "source_id"],
        "additionalProperties": False,
    }
    assert llm.validate_json_schema(
        {"state": None, "source_id": "src-1"}, schema
    )["state"] is None
    with pytest.raises(llm.StructuredOutputError, match="source_id"):
        llm.validate_json_schema({"state": None, "source_id": None}, schema)
```

- [ ] **Step 2: 运行测试并确认当前实现失败**

Run: `python -m pytest tests/test_llm_json.py tests/test_annotation_protocol.py -q`

Expected: 联合 `type` 尚未被 schema 校验器识别，且 `_validate_state_delta()` 尚未删除 `None` 或拒绝错误的非空类型。

- [ ] **Step 3: 让 schema 只在 state_delta 字段接受 null**

在 `llm.py` 用明确的类型匹配函数处理字符串或字符串数组，不实现 `anyOf`、类型强制转换或宽松跳过：

```python
def _matches_schema_type(value, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return False


def _validate_schema_value(value, schema, path: str) -> None:
    expected = schema.get("type")
    if isinstance(expected, list):
        if not expected or not any(_matches_schema_type(value, item) for item in expected):
            raise _schema_error(path, "类型不符合允许范围")
        if value is None:
            return
        expected = next(item for item in expected if _matches_schema_type(value, item))
    # 继续执行现有 object/array/enum/范围校验。
```

在 `build_chunk_schema()` 中只改 `state_properties`：

```python
state_properties = {
    name: {"type": [base_type, "null"]}
    for name, base_type in STATE_FIELD_TYPES.items()
}
```

- [ ] **Step 4: 在协议层归一化 null，并独立校验非空状态类型**

在 `annotation_protocol.py` 增加并使用同一份显式类型表：

```python
STATE_FIELD_TYPES = {
    "background": str,
    "place": str,
    "bgfx": str,
    "visible_characters": list,
    "positions": dict,
    "last_faces": dict,
    "recent_emoticons": list,
    "recent_actions": list,
    "recent_sounds": list,
    "open_threads": list,
}


def _validate_state_delta(value: Any) -> Dict[str, Any]:
    state = _require_dict(value, "invalid_state_delta", "state_delta 必须是对象")
    unknown = set(state) - STATE_FIELDS
    if unknown:
        raise ChunkProtocolError("invalid_state_delta", f"state_delta 包含未知字段: {sorted(unknown)}")
    normalized = {}
    for name, field_value in state.items():
        if field_value is None:
            continue
        if not isinstance(field_value, STATE_FIELD_TYPES[name]):
            raise ChunkProtocolError("invalid_state_delta", f"state_delta.{name} 类型不正确")
        normalized[name] = field_value
    return normalized
```

- [ ] **Step 5: 运行协议回归**

Run: `python -m pytest tests/test_llm_json.py tests/test_annotation_protocol.py tests/test_annotation_memory.py -q`

Expected: PASS；`state_delta.bgfx=null` 被归一化为空增量，非法台词字段、状态类型、未知字段和事件引用仍失败。

- [ ] **Step 6: 提交协议修复**

```bash
git add llm.py annotation_protocol.py tests/test_llm_json.py tests/test_annotation_protocol.py
git commit -m "fix: normalize optional annotation state nulls"
```

---

### Task 2: Explicit Output Errors and Removal of Hidden Full-Request Replay

**Files:**
- Modify: `llm.py:15-430`
- Modify: `tests/test_llm_profile_provider.py`

**Interfaces:**
- Consumes: `StructuredOutputError`
- Produces: `OutputCapacityError(StructuredOutputError)`；内容校验失败不再触发 Provider 内部的第二次完整请求。
- Invariant: 端点以 HTTP 400 明确拒绝 `response_format=json_schema` 时，仍按现有路径降级到 `json_object`；再次明确拒绝时仍可降级为无 `response_format`。

- [ ] **Step 1: 写出容量类型和“内容错误只调用一次”的失败测试**

将现有“Markdown 内容会自动重发”的测试改成下面的契约，并保留 HTTP 400 response-format 降级测试：

```python
def test_invalid_strict_content_does_not_replay_full_request(monkeypatch):
    payloads = []

    def fake_urlopen(request, timeout):
        payloads.append(json.loads(request.data))
        return FakeHttpResponse({
            "choices": [{
                "message": {"content": "### 不是 JSON"},
                "finish_reason": "stop",
            }],
        })

    monkeypatch.setattr(llm, "urlopen", fake_urlopen, raising=False)
    provider = llm.OpenAIProvider({"api_key": "secret", "model": "scene-model"})

    with pytest.raises(llm.StructuredOutputError, match="合法 JSON"):
        provider.complete_json("system", "", "user", {"type": "object"})

    assert len(payloads) == 1


def test_length_finish_reason_raises_capacity_error(monkeypatch):
    monkeypatch.setattr(
        llm,
        "urlopen",
        lambda request, timeout: FakeHttpResponse({
            "choices": [{"message": {"content": "{"}, "finish_reason": "length"}],
        }),
        raising=False,
    )
    provider = llm.OpenAIProvider({
        "api_key": "secret", "model": "deepseek-v4-flash", "max_tokens": 16000,
    })

    with pytest.raises(llm.OutputCapacityError, match="finish_reason=length"):
        provider.complete_json("system", "", "user", {"type": "object"})
```

- [ ] **Step 2: 运行测试并确认隐藏重发仍存在**

Run: `python -m pytest tests/test_llm_profile_provider.py -k "replay or capacity or response_format" -q`

Expected: 当前实现对内容解析错误再次请求兼容模式，且没有 `OutputCapacityError`。

- [ ] **Step 3: 增加明确的容量异常，并只按完成原因抛出**

```python
class OutputCapacityError(StructuredOutputError):
    """The provider stopped because the configured output budget was exhausted."""


def _capacity_message(self, prefix: str) -> str:
    return (
        f"{self.model} {prefix}输出被截断（finish_reason=length，"
        f"max_tokens={self.cfg.get('max_tokens', 16000)}）"
    )
```

在空文本和 JSON 解析失败路径中，只要最终 `finish_reason == "length"` 就抛 `OutputCapacityError`；其余非法 JSON/schema 继续抛 `StructuredOutputError`。

- [ ] **Step 4: 删除基于内容错误的 Provider 内部降级重发**

`OpenAIProvider._complete()` 只在 `_completion_text()` 抛 `UnsupportedResponseFormatError` 时切换兼容格式。`parse_and_validate_json_response()` 抛出的 `StructuredOutputError` 原样返回给 Agent，不设置 `_strict_response_format_unavailable`：

```python
try:
    text = self._completion_text(messages, strict_format, vision=vision)
except UnsupportedResponseFormatError:
    self._strict_response_format_unavailable = True
    return self._complete_compatible(messages, schema, prefix, vision=vision)
return parse_and_validate_json_response(text, schema, f"{self.model} {prefix}")
```

- [ ] **Step 5: 运行 Provider 回归**

Run: `python -m pytest tests/test_llm_json.py tests/test_llm_profile_provider.py -q`

Expected: PASS；内容错误只有一次 HTTP 请求，`finish_reason=length` 是容量错误，HTTP 400 格式不支持仍按 2/3 段兼容路径工作。

- [ ] **Step 6: 提交错误分类修复**

```bash
git add llm.py tests/test_llm_profile_provider.py
git commit -m "fix: stop replaying invalid structured responses"
```

---

### Task 3: Provider Streaming and Cache-Aware Usage Telemetry

**Files:**
- Modify: `llm.py:105-440`
- Modify: `tests/test_llm_profile_provider.py`

**Interfaces:**
- Produces: `Provider.complete_json_stream(static_system, volatile_system, user, schema, *, on_activity=None) -> dict`
- Callback payload: `{state, model, request_started_at_ms, elapsed_ms, first_delta_ms, received_chars, finish_reason}`；`state` 为 `waiting | receiving | completed`。
- Backward compatibility: `Provider.complete_json_stream()` 默认包装现有 `complete_json()`；没有流式实现的 Provider 仍可完成任务。
- Stats keys: `in`, `out`, `cache_read`, `cache_miss`, `cache_write`, `cache_reports`, `calls`。

- [ ] **Step 1: 写出 OpenAI SSE 拼接、Anthropic delta 和 usage 失败测试**

在 `tests/test_llm_profile_provider.py` 增加 `FakeSseResponse`，逐行返回：

```python
class FakeSseResponse:
    def __init__(self, lines):
        self.lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def __iter__(self):
        return iter(self.lines)


def test_openai_stream_joins_deltas_and_reports_activity(monkeypatch):
    lines = [
        b'data: {"choices":[{"delta":{"content":"{\\"ok\\":"},"finish_reason":null}]}\n',
        b'data: {"choices":[{"delta":{"content":"true}"},"finish_reason":"stop"}]}\n',
        b'data: {"choices":[],"usage":{"prompt_tokens":100,"completion_tokens":2,"prompt_cache_hit_tokens":70,"prompt_cache_miss_tokens":30}}\n',
        b'data: [DONE]\n',
    ]
    monkeypatch.setattr(llm, "urlopen", lambda request, timeout: FakeSseResponse(lines))
    events = []
    provider = llm.OpenAIProvider({"api_key": "secret", "model": "stream-model"})
    schema = {
        "type": "object", "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"], "additionalProperties": False,
    }

    result = provider.complete_json_stream(
        "stable", "volatile", "user", schema, on_activity=events.append,
    )

    assert result == {"ok": True}
    assert events[0]["state"] == "waiting"
    assert any(event["state"] == "receiving" and event["received_chars"] > 0 for event in events)
    assert events[-1]["state"] == "completed"
    assert provider.stats["cache_read"] == 70
    assert provider.stats["cache_miss"] == 30
    assert provider.stats["cache_reports"] == 1
```

另加参数化 usage 测试覆盖 `prompt_tokens_details.cached_tokens` 与 DeepSeek 的 `prompt_cache_hit_tokens`/`prompt_cache_miss_tokens`，并用一个 SDK fake 验证 Anthropic `text_stream` 的两段文本会触发 `receiving`。

- [ ] **Step 2: 运行测试并确认当前 Provider 没有流式回调**

Run: `python -m pytest tests/test_llm_profile_provider.py -k "stream or cache" -q`

Expected: `complete_json_stream`、SSE 读取和 `cache_miss/cache_reports` 尚不存在。

- [ ] **Step 3: 实现向后兼容的活动事件入口**

在基类中增加包装实现和统一 emitter：

```python
def _emit_activity(callback, state, **fields):
    if callback:
        callback({"state": state, **fields})


def complete_json_stream(
    self, static_system, volatile_system, user, schema, *, on_activity=None,
):
    started_ms = int(time.time() * 1000)
    _emit_activity(on_activity, "waiting", model=self.model,
                   request_started_at_ms=started_ms, elapsed_ms=0,
                   first_delta_ms=None, received_chars=0, finish_reason="")
    result = self.complete_json(static_system, volatile_system, user, schema)
    _emit_activity(on_activity, "completed", model=self.model,
                   request_started_at_ms=started_ms,
                   elapsed_ms=int(time.time() * 1000) - started_ms,
                   first_delta_ms=None, received_chars=0, finish_reason="unknown")
    return result
```

在模块 import 中加入 `time` 和 typing callback 所需类型；事件只包含可序列化标量。

- [ ] **Step 4: 实现 OpenAI-compatible SSE 和 Anthropic 文本 delta**

OpenAI 路径发送 `stream: true` 与 `stream_options: {include_usage: true}`，逐行只解析 `data:` JSON 和 `[DONE]`。只拼接 `choices[0].delta.content`，记录最终 `finish_reason` 与最后一个 usage；在完整文本收到后才调用现有 JSON/schema 校验。HTTP 状态和 response-format 降级仍复用现有错误处理。

Anthropic 路径在使用现有请求参数调用 `client.messages.stream(model=self.model, max_tokens=self.max_tokens, system=system, messages=messages)` 后迭代 `stream.text_stream`，每次 delta 更新字符数和首段耗时，退出迭代后调用 `get_final_message()` 取得 usage/stop reason。不得把中间文本交给 Agent 或 Job。

- [ ] **Step 5: 解析三类缓存字段并保留“未报告”状态**

```python
def _record_usage(self, response):
    usage = response.get("usage") or {}
    details = usage.get("prompt_tokens_details") or {}
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    cached = usage.get("prompt_cache_hit_tokens")
    if cached is None:
        cached = details.get("cached_tokens")
    missed = usage.get("prompt_cache_miss_tokens")
    if missed is None and cached is not None:
        missed = max(0, prompt_tokens - int(cached or 0))
    self.stats["calls"] += 1
    self.stats["in"] += prompt_tokens
    self.stats["out"] += int(usage.get("completion_tokens") or 0)
    if cached is not None or missed is not None:
        self.stats["cache_reports"] += 1
        self.stats["cache_read"] += int(cached or 0)
        self.stats["cache_miss"] += int(missed or 0)
```

Anthropic 在 SDK usage 有缓存字段时也递增 `cache_reports`；没有字段时保持 0 reports，而不是伪造 0% 命中。

- [ ] **Step 6: 运行流式与非流式 Provider 回归**

Run: `python -m pytest tests/test_llm_profile_provider.py tests/test_llm_json.py -q`

Expected: PASS；SSE/Anthropic 文本只在结束后解析，活动事件有首段与字符数，原 `complete_json()` 契约仍通过。

- [ ] **Step 7: 提交流式 Provider**

```bash
git add llm.py tests/test_llm_profile_provider.py
git commit -m "feat: stream structured model activity"
```

---

### Task 4: Agent Failure Policy, Learned Chunk Limit, and Metrics

**Files:**
- Modify: `annotation_agent.py:20-260`
- Modify: `annotate.py:830-870`
- Modify: `tests/test_annotation_agent.py`
- Modify: `tests/test_annotation_agent_scale.py`

**Interfaces:**
- Consumes: `OutputCapacityError`, `Provider.complete_json_stream(static_system, volatile_system, user, schema, on_activity=callback)`
- Produces: `run_annotation_agent` 的 keyword-only `model_activity: Optional[Callable[[Mapping[str, Any]], None]]` 参数
- Produces metrics: `requests`, `retries`, `subdivisions`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `uncached_input_tokens`, `cache_hit_rate`, `cache_reported`, `elapsed_ms`, `actual_model`。
- Failure policy: `capacity -> 直接缩块`；`protocol -> 同尺寸纠正一次后失败`；连接/运行错误 -> 立即失败。

- [ ] **Step 1: 写出分类、null 第七块、自适应上限和检查点失败测试**

在 `tests/test_annotation_agent.py` 增加四组断言：

```python
def test_seventh_chunk_optional_state_null_finishes_without_retry(tmp_path):
    class NullStateProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            response = super().complete_json(static, volatile, user, schema)
            if self.calls == 7:
                response["state_delta"] = {"bgfx": None}
            return response

    provider = NullStateProvider()
    result = fixture(tmp_path, provider, count=301)

    assert result["cancelled"] is False
    assert len(result["rows_by_id"]) == 301
    assert result["metrics"]["retries"] == 0


def test_protocol_error_gets_one_correction_and_never_subdivides(tmp_path):
    class WrongTypeProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            response = super().complete_json(static, volatile, user, schema)
            response["state_delta"] = {"positions": []}
            return response

    provider = WrongTypeProvider()
    with pytest.raises(AnnotationAgentError, match="invalid_state_delta"):
        fixture(tmp_path, provider, count=25)

    assert provider.calls == 2


def test_capacity_success_teaches_remaining_chunks_the_safe_limit(tmp_path):
    class TenLineProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            ids = re.findall(r"\[TARGET ([^\]]+)\]", user)
            if len(ids) > 10:
                self.calls += 1
                self.requests.append({"target_ids": ids, "user": user, "volatile": volatile})
                raise llm.OutputCapacityError("finish_reason=length")
            return super().complete_json(static, volatile, user, schema)

    provider = TenLineProvider()
    result = fixture(tmp_path, provider, count=80)
    successful_sizes = [len(row["target_ids"]) for row in provider.requests if len(row["target_ids"]) <= 10]

    assert result["metrics"]["subdivisions"] >= 1
    assert successful_sizes
    assert all(size <= 10 for size in successful_sizes)
    # 第一个 10 行成功后，不再向后续基础块发送大于 10 行的请求。
    first_safe = next(i for i, row in enumerate(provider.requests) if len(row["target_ids"]) <= 10)
    assert all(len(row["target_ids"]) <= 10 for row in provider.requests[first_safe:])
```

另加一个后续块失败测试：第一块提交检查点后，第二块连续两次内容错误，断言检查点仍只有第一块且没有 10/5 行缩块诊断。

- [ ] **Step 2: 运行 Agent 测试并确认旧实现把所有结构错误都当成容量错误**

Run: `python -m pytest tests/test_annotation_agent.py -k "null or protocol_error or safe_limit or checkpoint" -q`

Expected: 当前实现会对内容错误继续缩到 5 行，且没有任务内安全上限或 `model_activity`。

- [ ] **Step 3: 实现唯一的错误分类函数**

```python
_CAPACITY_PROTOCOL_CODES = {"missing_target"}


def _classify_chunk_error(exc: Exception) -> str:
    if isinstance(exc, OutputCapacityError):
        return "capacity"
    if isinstance(exc, ChunkProtocolError) and exc.code in _CAPACITY_PROTOCOL_CODES:
        return "capacity"
    if isinstance(exc, (ChunkProtocolError, StructuredOutputError)):
        return "protocol"
    return "fatal"
```

不要通过中文错误文本猜分类；删除 `"finish_reason=length" in str(exc)` 和 `"返回了空文本" in str(exc)` 这类分支。Provider 必须用异常类型携带容量语义。

- [ ] **Step 4: 重写每块的最小重试状态机**

每个块使用以下顺序：

```python
protocol_attempts = 0
while True:
    try:
        response = complete_chunk(
            static_system, volatile_system, user, schema,
            on_activity=emit_activity,
        )
        validated = validate_chunk_response(response, schema)
        break
    except Exception as exc:
        kind = _classify_chunk_error(exc)
        if kind == "capacity":
            last_error = exc
            break
        if kind == "protocol" and protocol_attempts == 0:
            protocol_attempts += 1
            retries += 1
            correction = f"上次响应无效：{error_code(exc)} - {exc}。请修正内容，保持相同 TARGET。"
            emit_model_state("retrying", reason=error_code(exc))
            continue
        if kind == "protocol":
            raise AnnotationAgentError("structured_output", scene_id, chunk_id, str(exc)) from exc
        raise AnnotationAgentError("model_call", scene_id, chunk_id, str(exc)) from exc
```

容量错误不做同尺寸重发；协议纠正失败不进入 `_next_subdivision_limit()`。

- [ ] **Step 5: 在任务内学习成功的安全块上限**

维护 `candidate_limit` 和 `safe_target_limit`。容量错误产生 `subdivision` 后将其设为 candidate；第一个 candidate 子块完整成功后才将其提升为 `safe_target_limit`。后续从队列取出的未处理块若大于 safe limit，在模型调用前直接 `subdivide_chunk()`。该值只存在当前 `run_annotation_agent()` 调用内，不写入配置或检查点。

活动事件在 Agent 包装 Provider payload 时补充 `scene_id`、`chunk_id`、`chunk_current`、`chunk_total`、`request_index`、`retry_count`、`subdivision_count`；缩块时发送：

```python
{
    "state": "subdividing",
    "reason": error_code(last_error),
    "next_chunk_lines": subdivision,
    "retry_count": retries,
    "subdivision_count": subdivisions,
}
```

- [ ] **Step 6: 从 Provider stats 计算可判空的缓存指标**

```python
cache_reports = token_delta("cache_reports")
cache_read = token_delta("cache_read")
cache_miss = token_delta("cache_miss")
cache_reported = bool(cache_reports)
cache_total = (cache_read or 0) + (cache_miss or 0)
metrics.update({
    "cache_read_tokens": cache_read if cache_reported else None,
    "uncached_input_tokens": cache_miss if cache_reported else None,
    "cache_hit_rate": (cache_read / cache_total) if cache_reported and cache_total else (0.0 if cache_reported else None),
    "cache_reported": cache_reported,
    "actual_model": str(getattr(provider, "model", "") or ""),
})
```

在 `annotate.py` 将 `options.get("model_activity")` 原样传给 Agent，并继续把 `agent_result["metrics"]` 放进 `agent_meta`。

- [ ] **Step 7: 运行 Agent 和 240 行规模回归**

Run: `python -m pytest tests/test_annotation_agent.py tests/test_annotation_agent_scale.py tests/test_annotate_main.py -q`

Expected: PASS；240 行每个目标恰好一个结果；内容错误不缩块；容量错误缩块后学习上限；失败保留已提交检查点。

- [ ] **Step 8: 提交 Agent 策略**

```bash
git add annotation_agent.py annotate.py tests/test_annotation_agent.py tests/test_annotation_agent_scale.py
git commit -m "fix: classify annotation failures before retrying"
```

---

### Task 5: Structured Job Activity and User-Visible Streaming Progress

**Files:**
- Modify: `jobs.py:14-67`
- Modify: `webui.py:3109-3160`
- Modify: `js/app.js:113-121,2135-2150`
- Modify: `tests/test_jobmanager.py`
- Modify: `tests/test_web_draft_endpoints.py`
- Modify: `tests/test_ui_runtime_behavior.py`
- Modify: `tests/ui_runtime_harness.js` only if the runtime test needs additional node behavior

**Interfaces:**
- Produces: `Job.update_activity(activity: Mapping[str, Any]) -> None`
- `Job.to_dict()` adds `activity: dict`.
- `annotate_draft_worker()` result adds `agent_metrics` while retaining `resumed_chunks`.
- `window.AppRuntime.annotationProgressDetail(item)` and `formatAnnotationCompletion(result)` become testable pure formatters.

- [ ] **Step 1: 写出 Job activity 序列化失败测试**

```python
def test_job_serializes_model_activity_without_replacing_progress_detail():
    job = Job("job-stream", label="标注")
    job.update_progress(25, "正在标注第 1/4 个场景块")
    job.update_activity({
        "state": "receiving", "model": "deepseek-v4-flash",
        "received_chars": 2048, "elapsed_ms": 7300,
    })

    payload = job.to_dict()

    assert payload["detail"] == "正在标注第 1/4 个场景块"
    assert payload["activity"]["state"] == "receiving"
    assert payload["activity"]["received_chars"] == 2048
```

- [ ] **Step 2: 写出 Web worker 与 UI 状态失败测试**

在 `tests/test_web_draft_endpoints.py` 的 worker fake 中主动调用 `options["model_activity"]({"state": "receiving", "model": "deepseek-v4-flash", "received_chars": 128})`，断言 Job 最终可读取 activity，且返回：

```python
assert result["agent_metrics"] == {
    "actual_model": "deepseek-v4-flash",
    "requests": 7,
    "cache_reported": True,
    "cache_read_tokens": 130432,
    "uncached_input_tokens": 58682,
    "cache_hit_rate": pytest.approx(0.69, abs=0.01),
}
```

在 `tests/test_ui_runtime_behavior.py` 通过 runtime 导出的 formatter 检查：

```javascript
const now=Date.now();
const waiting=h.window.AppRuntime.annotationProgressDetail({
  state:'running',detail:'正在标注第 2/7 个场景块',
  activity:{state:'waiting',model:'deepseek-v4-flash',request_started_at_ms:now-5200}
});
const receiving=h.window.AppRuntime.annotationProgressDetail({
  state:'running',detail:'正在标注第 2/7 个场景块',
  activity:{state:'receiving',received_chars:8192,elapsed_ms:9600}
});
const retrying=h.window.AppRuntime.annotationProgressDetail({
  state:'running',detail:'正在标注第 2/7 个场景块',
  activity:{state:'retrying',reason:'invalid_state_delta',retry_count:1}
});
```

断言分别包含 `等待模型首段响应`、`已接收 8,192 字符`、`正在纠正返回格式`；完成摘要在有缓存报告时包含真实百分比，没有报告时包含 `缓存未报告`。

- [ ] **Step 3: 运行 Job/Web/UI 测试并确认结构化 activity 尚不存在**

Run: `python -m pytest tests/test_jobmanager.py tests/test_web_draft_endpoints.py tests/test_ui_runtime_behavior.py -k "activity or streaming or cache" -q`

Expected: `Job.activity`、worker 回调和 formatter 状态分支尚不存在。

- [ ] **Step 4: 实现 Job 的线程安全 activity 快照**

```python
class Job:
    def __init__(self, job_id: str, label: str = "job"):
        # 现有字段保持不变。
        self.activity: Dict[str, Any] = {}

    def update_activity(self, activity: Mapping[str, Any]):
        allowed = {
            "state", "model", "scene_id", "chunk_id", "chunk_current", "chunk_total",
            "request_index", "request_started_at_ms", "elapsed_ms", "first_delta_ms",
            "received_chars", "finish_reason", "retry_count", "subdivision_count",
            "reason", "next_chunk_lines",
        }
        with self._lock:
            self.activity.update({key: value for key, value in dict(activity).items() if key in allowed})
            self.updated_at = datetime.datetime.now(datetime.timezone.utc)
```

`to_dict()` 返回 `dict(self.activity)`，不得返回可由调用方修改的内部字典。

- [ ] **Step 5: 将 Provider 活动接到标注 Job，并返回 metrics**

在 `webui.annotate_draft_worker()` 内定义：

```python
def annotation_model_activity(activity):
    if job:
        job.update_activity(activity)
```

把它放入 `opts["model_activity"]`。完成结果保留原字段，并加入：

```python
return {
    "draft_token": token,
    "project": project,
    "lines": len(annotated.splitlines()),
    "proposals": len(proposals),
    "resumed_chunks": int(agent.get("resumed_chunks") or 0),
    "agent_metrics": dict(agent.get("metrics") or {}),
}
```

- [ ] **Step 6: 用结构化字段渲染实时状态和完成摘要**

`annotationProgressDetail(item)` 优先读取 `item.activity`：

```javascript
if (activity.state === 'waiting') return base + ' · 等待模型首段响应 · 已等待 ' + seconds + ' 秒';
if (activity.state === 'receiving') return base + ' · 模型持续返回中 · 已接收 ' + number(activity.received_chars) + ' 字符 · 已用时 ' + seconds + ' 秒';
if (activity.state === 'retrying') return base + ' · 正在纠正返回格式 · 第 ' + activity.retry_count + ' 次';
if (activity.state === 'subdividing') return base + ' · 输出容量不足，缩小到 ' + activity.next_chunk_lines + ' 行';
```

没有 activity 的旧 Job 才使用当前 `updated_at` 超过 60 秒的兼容提示。完成摘要显示实际模型、总耗时、请求次数、缩块次数、复用检查点数和缓存命中；不要显示原始 JSON。

将两个 formatter 暴露到 `window.AppRuntime` 供 Node 测试调用。

- [ ] **Step 7: 运行后端和 UI 回归**

Run: `python -m pytest tests/test_jobmanager.py tests/test_web_draft_endpoints.py tests/test_ui_runtime_behavior.py tests/test_ui_async_operations.py -q`

Run: `node --check js/app.js`

Expected: PASS；Job 每次 delta 都刷新 `updated_at`，轮询期间可看到等待/接收/纠正/缩块状态，完成摘要正确区分真实 0% 与未报告。

- [ ] **Step 8: 提交流式进度 UI**

```bash
git add jobs.py webui.py js/app.js tests/test_jobmanager.py tests/test_web_draft_endpoints.py tests/test_ui_runtime_behavior.py tests/ui_runtime_harness.js
git commit -m "feat: expose live annotation model activity"
```

---

### Task 6: Guarded Real-Endpoint Smoke Test and Full Regression

**Files:**
- Create: `tools/smoke_annotation_stream.py`
- Verify: all files changed by Tasks 1-5

**Interfaces:**
- Consumes environment variables: `AA_SMOKE_BASE_URL`, `AA_SMOKE_API_KEY`, `AA_SMOKE_MODEL`, `AA_SMOKE_MAX_TOKENS`。
- Produces stdout only: model ID, elapsed ms, first-delta ms, received characters, finish reason and usage totals；绝不输出密钥、Authorization、提示全文或原始模型响应。

- [ ] **Step 1: 写出显式门控的 5 行冒烟工具**

工具在任一必需环境变量缺失时以退出码 2 和简短用法结束；构造 5 个 synthetic TARGET 和最小资源约束，通过真实 `OpenAIProvider.complete_json_stream()` 收集活动。脚本最终调用 `validate_chunk_response()`，并断言 5 个 source ID 都恰好出现一次。

输出结构固定为：

```python
print(json.dumps({
    "model": provider.model,
    "elapsed_ms": completed["elapsed_ms"],
    "first_delta_ms": completed["first_delta_ms"],
    "received_chars": completed["received_chars"],
    "finish_reason": completed["finish_reason"],
    "input_tokens": provider.stats["in"],
    "output_tokens": provider.stats["out"],
    "cache_read_tokens": provider.stats["cache_read"] if provider.stats["cache_reports"] else None,
    "cache_miss_tokens": provider.stats["cache_miss"] if provider.stats["cache_reports"] else None,
}, ensure_ascii=False))
```

- [ ] **Step 2: 先运行全部离线定向测试**

Run:

```powershell
python -m pytest tests/test_llm_json.py tests/test_llm_profile_provider.py tests/test_annotation_protocol.py tests/test_annotation_memory.py tests/test_annotation_agent.py tests/test_annotation_agent_scale.py tests/test_annotate_main.py tests/test_jobmanager.py tests/test_web_draft_endpoints.py tests/test_ui_runtime_behavior.py tests/test_ui_async_operations.py -q
```

Expected: PASS；真实接口测试尚未运行且不消耗额度。

- [ ] **Step 3: 在用户已授权的 Token Rhythm 连接上运行一次小型冒烟**

在当前 PowerShell 进程中设置环境变量，不把值写入 `.env`、脚本、shell history 文档或测试夹具。使用已核验的 URL、模型和上限运行：

```powershell
python tools/smoke_annotation_stream.py
```

Expected: 5 个目标全部校验通过；stdout 显示 `deepseek-v4-flash`、非空 `first_delta_ms`、递增字符数、`finish_reason=stop` 和脱敏 usage。若接口返回新的协议差异，先把响应形状转换为不含内容/密钥的离线 fixture，再修 Provider；不得直接放宽整个标注协议。

- [ ] **Step 4: 运行全量测试与静态检查**

Run: `python -m pytest -q`

Run: `Get-ChildItem js\*.js | ForEach-Object { node --check $_.FullName }`

Run: `python -m compileall -q .`

Run: `git diff --check`

Expected: 全部通过；`git diff --check` 无空白错误。

- [ ] **Step 5: 对比安全性和行为边界**

检查 `git diff -- llm.py annotation_protocol.py annotation_agent.py annotate.py jobs.py webui.py js/app.js tools/smoke_annotation_stream.py`，确认：

- 没有 API Key、Authorization、用户脚本正文或原始响应。
- 没有更改检查点 fingerprint、草稿格式、台词字段严格性和资源 allowlist。
- 不再按中文错误文本分类。
- 内容错误不会在 Provider 和 Agent 两层各自重发。
- `cache_reported=False` 时 UI 显示“缓存未报告”。

- [ ] **Step 6: 提交冒烟工具与最终测试调整**

```bash
git add tools/smoke_annotation_stream.py
git commit -m "test: add guarded annotation streaming smoke check"
```

## Completion Gate

只有以下条件全部满足，才可以宣称本计划完成：

- 截图中的 `state_delta.bgfx=null` 场景可继续生成，不产生重试或缩块。
- 同一个非容量内容错误最多请求两次，第二次失败后立即返回具体错误；Provider 不再隐藏重发。
- 容量失败成功缩块后，后续大块直接使用任务内学到的安全上限。
- 每个真实模型请求期间，用户都能看到等待首段或累计接收字符状态。
- 完成结果包含实际模型、请求、重试、缩块、耗时、输入、输出和可判空缓存指标。
- 240 行离线严格覆盖测试、全量 pytest、JS syntax check 和一次授权的小型真实接口冒烟通过。
- 不得把“单个场景块的总生成时间已经恢复到从前”列入完成声明；该问题仍由独立性能债文档追踪。
