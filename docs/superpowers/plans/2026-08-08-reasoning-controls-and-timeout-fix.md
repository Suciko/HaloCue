# 审查草稿推理控制与超时修复实施计划

日期：2026-08-08
设计依据：`docs/superpowers/specs/2026-08-08-reasoning-controls-and-chunk-efficiency-design.md`

## 目标

消除高思考大块触发的长 reasoning、16K 截断和逐级缩块链；让用户能按模型真实能力选择推理模式，并在生成期间看到“等待响应 / 思考中 / 生成正文”的准确状态。

## 任务 1：模型推理能力与规范化配置

文件：

- 修改 `model_capabilities.py`
- 修改 `model_profiles.py`
- 测试 `tests/test_model_capabilities.py`
- 测试 `tests/test_model_profiles.py`

步骤：

1. 先写失败测试，覆盖 DeepSeek 精确模型匹配、未知自定义模型、支持开关/档位及默认开启语义。
2. 增加推理能力解析结果：`toggle`、`efforts`、`default_mode`、`wire_protocol`。
3. 模型记录保存规范化的 `reasoning_mode` 和独立 `annotation_max_tokens`；旧记录迁移为安全默认。
4. 验证公开状态和 Provider settings 携带这些字段，密钥仍不进入 JSON。

## 任务 2：Provider 参数映射与阶段 telemetry

文件：

- 修改 `llm.py`
- 测试 `tests/test_llm_profile_provider.py`

步骤：

1. 先写 fake SSE 测试，让 `reasoning_content` 早于 `content`，断言阶段事件、计数和正文拼接互不污染。
2. 写 DeepSeek payload 测试：速度发送 `thinking.type=disabled`；开启发送 `thinking.type=enabled` 与受支持 effort；未知协议不盲发字段。
3. 将首 SSE、首 reasoning、首 content、reasoning/content 字符数加入 activity 和完成事件。
4. 为流式请求增加独立墙钟截止；socket timeout 继续只处理网络静默。
5. 增加可分类的瞬时传输错误和请求截止错误，不把它们伪装成 Schema 错误。
6. DeepSeek 官方预设直接使用已验证的 `json_object` 路径，跳过严格 Schema 的必失败探测。

## 任务 3：Agent 安全分块、任务预算与有限重试

文件：

- 修改 `annotation_agent.py`
- 修改 `annotate.py`
- 测试 `tests/test_annotation_agent.py`
- 测试 `tests/test_annotation_chunks.py`

步骤：

1. 先写失败测试，覆盖速度/均衡/深入模式的块配置，以及高思考容量失败直接落到安全上限。
2. 将模型最大输出与 `annotation_max_tokens` 分离，Agent 只使用后者作为单次请求预算。
3. 速度模式使用 50/60/72；均衡使用 20/24/30；深入使用 16/20/24。
4. 容量失败不再遍历 60→50→30→20→10→5；先落到当前模式安全上限，之后最多再减半一次。
5. 只对 429/500/502/503/504、连接重置和超时做最多两次退避；协议纠正仍最多一次。
6. metrics 分别统计传输重试、协议重试、容量缩块和请求截止。

## 任务 4：Job 状态与浏览器显示

文件：

- 修改 `jobs.py`
- 修改 `webui.py`
- 修改 `js/app.js`
- 测试 `tests/test_jobmanager.py`
- 测试 `tests/test_ui_runtime_behavior.py`

步骤：

1. 先写失败测试，覆盖 reasoning 状态与不同阶段文案。
2. Job 保留结构化阶段字段，不存 reasoning 正文。
3. UI 显示“等待模型响应”“模型思考中”“模型正在生成草稿”，并持续显示耗时和计数。
4. 截止或失败时显示已保留检查点及切换速度模式的恢复建议。

## 任务 5：模型工作台推理模式控件

文件：

- 修改 `ui.html`
- 修改 `js/model.js`
- 修改 `js/app.js`
- 修改 `webui.py`
- 测试 `tests/test_ui_model_workbench.py`
- 测试 `tests/test_web_model_profiles.py`

步骤：

1. 先写失败测试，覆盖 DeepSeek 显示速度/均衡/深入，未知模型只显示供应商默认，不支持关闭时不显示速度。
2. 增加离散推理模式控件和简短风险说明。
3. 模型切换时按能力重建选项；保存规范化值，不保存 UI 文案。
4. API 返回模型推理能力，并验证非法模式不能越权保存。

## 任务 6：验证与真实冒烟

步骤：

1. 运行定向 Provider、Agent、模型能力、Job 和 UI 测试。
2. 运行完整 pytest 回归和 `git diff --check`。
3. 用 DeepSeek 官方 3 行样本验证速度模式没有 reasoning，均衡模式能报告 reasoning 阶段。
4. 用 24 行样本测试 low/medium/high，确认哪些 effort 真正生效并据此调整默认映射。
5. 用 60 行速度模式确认单请求完整；均衡模式确认按安全块完成且不发生逐级缩块。
6. 最后运行 266 行速度模式完整草稿，记录总耗时、请求、重试、输入、输出和缓存；均衡模式只有 60 行通过后才运行完整长稿。

## 完成条件

- 高思考 60 行不再形成逐级容量重试链。
- 活跃 reasoning 不再被显示为等待首段，也不能绕过墙钟截止。
- 速度模式真实关闭 DeepSeek 思考；未知模型没有虚假开关。
- 模型最大输出不再直接决定单次标注任务预算。
- 所有离线回归通过，真实 3/24/60 行冒烟结果可复盘。
