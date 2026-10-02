# 1.0 中转模型接入与弹窗反馈修复

- kind: handoff
- scope: HaloCue 1.0 / 写作模型连接 / 设置反馈
- status: 本次有界修复已完成；不代表整个 1.0 已完成验收
- observed_at: 2026-09-27
- source: 用户提供的错误截图、授权的本机中转接口、实际 HTTP 对照、内部浏览器与自动化测试
- owner: backend / writing web
- branch: `codex/1.0-release-readiness-20260914`
- baseline: `e617f9bf`
- issue: 本次用户报告，未新建远程 Issue
- commit / PR: 未提交、未推送；工作树已有大量其他会话变更，本次没有把这些改动混入提交。
- source of truth: `docs/product-direction-1.x.md`、`CONTEXT-MAP.md`、`contexts/backend/CONTEXT.md`、`contexts/ai-galgame/CONTEXT.md`

## 根因与改动

1. 同一中转、模型与凭据：普通请求成功，HaloCue 写作连接测试返回 HTTP 403 / `error code: 1010`。将请求 User-Agent 改为 Python 默认标识可复现失败，使用诚实的应用标识 `HaloCue/1.0` 则成功。
2. 获取模型列表已有应用标识，但写作连接测试和实际生成遗漏了该请求头。两条调用路径现已补齐，OpenAI 兼容与 Anthropic 分支均覆盖；未绕过鉴权、关闭证书验证或改变用户代理设置。403 提示同时区分“网关拒绝”与“密钥错误”。
3. 全局 toast 原来挂在 body，位于模态设置弹窗及遮罩下，增加 z-index 不能修好。现挂到打开的模态弹窗内，并以 manual popover 显示在顶层；旧 WebView 降级为弹窗内提示。关闭弹窗、关闭提示或超时后清理并归还 body。
4. 保存结果原来在设置顶部，用户从底部保存时结果在屏幕外。结果现位于表单按钮前，完成后在设置内部滚动并聚焦，避开固定按钮栏。启用结果明确标注模型名；启用自带测试替代上一次测试卡，不再同时显示误导的“配置已更改”。

## 业务文件

- `services/halocue/writing/src/halocue_writing/model_settings.py`
- `services/halocue/writing/src/halocue_writing/providers.py`
- `services/halocue/writing/web/app.js`
- `services/halocue/writing/web/index.html`
- `services/halocue/writing/web/authoring-ui.css`

没有更改持久化格式、跨服务版本化契约或模型输出门禁；无需迁移。

## 自动化验证

先新增失败用例再修改实现：本机 HTTP relay 拒绝默认 Python UA，连接/启用/真实 provider 调用 4 项均先失败，修复后全部通过。fixture 只用合成数据，没有真实密钥或远程调用。

```text
python -X utf8 -m pytest services/halocue/writing/tests/test_model_relay_transport.py services/halocue/writing/tests/test_provider_activation_contract.py services/halocue/writing/tests/test_provider_response_contract.py services/halocue/writing/tests/test_provider_tool_calling.py services/halocue/writing/tests/test_settings_controller_safety.py services/halocue/writing/tests/test_settings_hub.py tests/test_model_capabilities.py -q --tb=short
131 passed in 17.82s

node --test services/halocue/writing/tests/toast_layer.test.cjs
3 passed

node services/halocue/writing/tests/settings_controller_cases.cjs <case> services/halocue/writing/web/app.js
对该文件中全部 33 个命名 case 逐一执行：33 passed，外部请求 0

node --check services/halocue/writing/web/app.js
通过

python -X utf8 -m ruff check services/halocue/writing/tests/test_model_relay_transport.py
python -X utf8 -m ruff format --check services/halocue/writing/tests/test_model_relay_transport.py
通过

git diff --check -- <本次修改的已跟踪路径>
通过
```

## 真实接口与浏览器证据

- 用户指定本机中转可获取 6 个模型；实测 `gpt-6-astra`。
- 从设置页面执行“获取模型 → 测试连通性 → 保存并立即启用”均成功。
- 连接测试一次约 2671ms；独立重建 `LLMWritingProvider`，从已保存配置读取凭据并实际调用，收到 `OK`（一次约 2266ms）。这些是单次连通验证，不是性能基准。
- 重载后模型仍为已测试并启用，密码框不回显；后端报告 `secret_source=dpapi`。本次 9 个源码/测试文件和设置查询响应均未包含真实密钥。
- 使用隔离的、仓库外 QA 数据目录，没有改动原有作品。真实调用只发送短连接验证文本，没有发送用户作品正文。
- 1366×768 桌面：故障 toast 的 top-layer 与 elementFromPoint 命中均确认；保存错误结果 bottom≈660.65、按钮栏 top≈672.67。
- 默认窄屏 595×871 也验证启用结果可见；最终截图存于 maintainer-local QA 输出，不作为共享仓库依赖。

## 边界与后续

- 实测的是“仅写作”。AA 制作模型未配置，本次没有宣称真实 AA 模型验收通过。
- 未修改中转服务本身；未改变模型目录、提示词策略或重试策略。
- 未跑全仓测试、重新打包 EXE/ZIP 或发布；2026-09-26 的旧交付包不会自动包含此修复。
- 如需向旧包用户交付，下一步应在整理对应源码变更后重新构建并验收安装包，而不是把本地 QA 配置或密钥打进包内。
