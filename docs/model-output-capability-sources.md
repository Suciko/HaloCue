# 模型最大输出能力来源台账

核验日期：2026-08-07

本台账只记录官方文档明确写出的最大输出或明确结论为未知的情况。`context window` 只表示上下文窗口，不会被当作最大输出。聚合服务的限制以聚合服务自身的 `/models` 元数据优先。

| preset | 默认模型 | 来源 | 结论 |
|---|---|---|---:|
| `openai` | `gpt-4o` | https://developers.openai.com/api/docs/models/gpt-4o | 16,384 |
| `anthropic` | `claude-sonnet-4-5` | https://platform.claude.com/docs/en/about-claude/models/overview | 64,000 |
| `gemini` | `gemini-2.5-flash` | https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash | 65,536 |
| `deepseek` | `deepseek-v4-flash` | https://api-docs.deepseek.com/quick_start/pricing | 384,000 |
| `glm` | `glm-4.6` | https://docs.bigmodel.cn/cn/guide/models/text/glm-4.6 | 128,000 |
| `qwen` | `qwen-max` | https://help.aliyun.com/zh/model-studio/getting-started/models | 未明确，unknown |
| `moonshot` | `kimi-k2-0905-preview` | https://platform.moonshot.cn/docs/intro | 未明确，unknown |
| `siliconflow` | `deepseek-ai/DeepSeek-V3` | https://siliconflow.cn/models | 聚合限制以 `/models` 为准 |
| `openrouter` | `openai/gpt-4o-mini` | https://openrouter.ai/openai/gpt-4o-mini | 16,384 |
| `ollama` | `llama3.2` | https://ollama.com/library/llama3.2 | 可配置，unknown |
| `custom` | 用户填写 | 无 | unknown，等待当前连接的 `/models` |

来源 URL 和日期属于能力元数据；API key 只允许进入内存或 Windows Credential Manager，不进入本台账。
