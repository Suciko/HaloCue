# 模型配置工作台设计

## 目标

修复模型配置“新建/保存/切换”流程，并让 DeepSeek、GLM、千问等 OpenAI-compatible 服务可以通过统一预设配置；同时把模型输出上限和 Agent 分块上限分开表达。

## 设计

- 配置协议保留 `openai` 和 `anthropic` 两种内部实现；OpenAI-compatible 服务通过 `service_preset` 提供 OpenAI、DeepSeek、GLM、千问、Moonshot、OpenRouter、Ollama、自定义等默认地址。
- 新建只创建前端草稿，不写入磁盘；保存时才生成 ID、保存非密钥字段并写入凭据管理器。新建可以在没有 API Key 时保存为 `missing` 状态，模型调用前仍要求密钥。
- 当前配置、表单草稿、已保存配置三者分离。切换配置或关闭设置时，若表单脏则显示保存/丢弃/取消。
- 模型列表和连接测试使用当前表单 payload，未保存编辑也可以测试；保存后的 profile API 仍只返回脱敏字段。
- `max_tokens` 表示一次模型响应的最大输出 token；Agent 使用独立的目标/软上限/硬上限字段。遇到 `finish_reason=length` 时显示明确诊断并自动缩小块。

## 验收

- 新建后表单进入空白可编辑状态，保存后配置列表出现新项并自动成为当前项。
- 保存空 API Key 不覆盖已有密钥；清除密钥后状态变为 missing。
- DeepSeek、GLM、千问预设可填充地址和模型示例，自定义地址仍可覆盖。
- 当前表单可直接读取模型和测试文本/视觉连接。
- 旧 profile 和 legacy `llm.json` 可继续读取；所有密钥不进入 JSON 或公共 API 响应。
