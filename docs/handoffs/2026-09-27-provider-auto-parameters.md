# 1.0 模型参数自动识别与服务商设置简化

- kind: handoff
- scope: HaloCue 1.0 / 模型服务设置
- status: 本次有界功能完成；不代表 NVIDIA/AMD 真实推理验收或整个 1.0 交付完成
- observed_at: 2026-09-27
- source: 用户明确要求；官方服务商文档与公开模型目录；Cherry Studio 中文界面参考；源码、行为回归和内置浏览器
- owner: backend / writing web
- branch: `codex/1.0-release-readiness-20260914`
- baseline: `e617f9bf`
- issue: 本次用户请求；未新建远程 Issue
- commit / PR: 未提交、未推送。保留其他会话工作树变更，没有把它们混入提交。
- source of truth: `docs/product-direction-1.x.md`、`CONTEXT-MAP.md`、`contexts/backend/CONTEXT.md`、`contexts/ai-galgame/CONTEXT.md`

## 用户要求与实现

1. 模型参数自动填入：打开设置、选择服务商/模型、获取模型列表后会自动更新。已知本地规格即时应用；未知项防抖查询目录。使用当前部署的元数据/已保存部署覆盖、已核对官方资料与目录，不通过付费推理猜容量。
2. 单次输出预算默认等于识别到的最大输出，不再把已知大输出模型固定为 8192。发送检测或保存之前会等待当前识别完成。真实生成仍由现有预算函数预留输入上下文；探测请求仍保持小额度，不能把检测变成百万 token 生成。
3. 未知字段明确展示未知/尚未公布；默认只读，必要时显式打开“手动调整”。切换模型清掉旧参数；异步返回不能覆盖另一模型、关闭后的表单或手动覆盖。协议参数名自动设置，只在手动覆盖时展示。
4. 加入 `nvidia` 与 `amd` 预设，服务商由 10 个增至 12 个。NVIDIA 使用 `https://integrate.api.nvidia.com/v1`；AMD 公共模型使用 `https://developer.amd.com.cn/radeon/api/v1`。两者使用已支持的 OpenAI Chat Completions 协议。模型列表可通过“获取模型”刷新，预设模型不是永久可用承诺。
5. 非自定义服务商隐藏整个协议/地址区块，不要求选择连接方式；仅自定义保留这些输入。旧配置若实际地址与预设不符，按自定义显示，不静默重写地址或挪用密钥。
6. 非自定义服务商增加官方网站、获取密钥、API 文档链接。只接纳无嵌入凭据的 HTTPS 目标，新标签打开并使用 `noopener noreferrer`。
7. 沿用 HaloCue 主题，参考 Cherry Studio 的服务商列表/详情结构和中文设置术语。使用“API 密钥、API 地址、模型、检测连接、模型参数、高级参数”，清掉不必要的中英双份描述。没有复制 Cherry Studio 实现代码或图标。
8. 扩充模型元数据解析：整数/数字串、`max_completion_tokens`、`top_provider`、`limit.context/input/output`；记录真正由接口提供的字段。ID-only 列表不再把内置规格标成“接口返回”。较小网关窗口不会继承不可能的大输出上限。

## 官方资料与边界

核对日期：2026-09-27。工具搜索没有返回可用正文，因此实际从官方页面/公开 API 读取资料；以下 URL 供后续复核，不要求访问私有账户。

- NVIDIA 统一 API：https://docs.api.nvidia.com/nim/reference/llm-apis
- NVIDIA 公共模型目录：https://integrate.api.nvidia.com/v1/models （本次无密钥 GET 返回 200）
- NVIDIA 当前预设 DeepSeek 接口限制：https://docs.api.nvidia.com/nim/reference/nvidia-deepseek-v4_1-flash-infer
- NVIDIA 对应模型说明：https://docs.api.nvidia.com/nim/reference/nvidia-deepseek-v4_1-flash
- AMD 公共模型与专用模型的区别及地址：https://amd-aim.github.io/radeon-cloud-docs/api/overview/
- AMD 模型元数据：https://amd-aim.github.io/radeon-cloud-docs/api/models/
- AMD Chat Completions 支持字段：https://amd-aim.github.io/radeon-cloud-docs/api/chat-completions/
- AMD 当前预设模型：https://amd-aim.github.io/radeon-cloud-docs/models/deepseek-v4-1-flash/
- AMD 申请/模型控制台：https://developer.amd.com.cn/radeon/tokenfactory
- Cherry Studio 参考：`CherryHQ/cherry-studio` 的 `packages/provider-registry/data/providers.json` 与 `src/renderer/i18n/locales/zh-cn.json`；只参考公开字段/术语，不移植 AGPL 实现。

NVIDIA 的所选模型文档明确给出 1,048,576 的上下文与接口 max_tokens 上限；这组部署参数只绑定该官方端点和确切模型 ID，不扩散到同名中转模型。AMD 对应模型页只公布 1,048,576 共享上下文，没有独立最大输出；不将上下文冒充输出能力。AMD 无密钥模型查询返回 401，不代表接入已失败，也不能宣称凭据已验证。免费/试用均保留账号配额和速率限制说明。

## 修改文件

- `model_capabilities.py`
- `services/halocue/writing/src/halocue_writing/model_settings.py`
- `services/halocue/writing/web/app.js`
- `services/halocue/writing/web/index.html`
- `services/halocue/writing/web/settings-center.css`
- `services/halocue/writing/tests/test_model_provider_defaults.py`（新）
- `services/halocue/writing/tests/settings_controller_cases.cjs`
- `services/halocue/writing/tests/test_settings_controller_safety.py`
- `services/halocue/writing/tests/test_settings_controller_browser.py`（匹配预设隐藏、自定义可编辑的新契约）

参数字段沿用既有配置；模型元数据只增加可选来源字段，无持久化迁移。上一轮的中转请求头与顶层错误提示修复保持不变。

## 验证

新增预设/元数据测试先有 7 项失败、2 项通过；实施后全过。自动表单用例先观察到未填默认值及预设连接区未隐藏，再实施修复。

```text
python -X utf8 -m pytest services/halocue/writing/tests/test_model_provider_defaults.py services/halocue/writing/tests/test_model_relay_transport.py services/halocue/writing/tests/test_provider_activation_contract.py services/halocue/writing/tests/test_provider_response_contract.py services/halocue/writing/tests/test_provider_tool_calling.py services/halocue/writing/tests/test_settings_controller_safety.py services/halocue/writing/tests/test_settings_hub.py services/halocue/writing/tests/test_ui_density_contract.py tests/test_model_capabilities.py -q --tb=short
159 passed in 19.64s

node services/halocue/writing/tests/settings_controller_cases.cjs <case> services/halocue/writing/web/app.js
逐一执行该文件全部 42 个命名 case：42 passed，外部模型请求 0

node --test services/halocue/writing/tests/toast_layer.test.cjs
3 passed

node --check services/halocue/writing/web/app.js
通过

python -X utf8 -m ruff check model_capabilities.py services/halocue/writing/tests/test_model_provider_defaults.py
python -X utf8 -m ruff format --check services/halocue/writing/tests/test_model_provider_defaults.py
通过

git diff --check -- <本次修改的已跟踪路径>
通过
```

### 内置浏览器与真实保存

- 当前 QA 实例服务商 12 个，新增两家可选择。
- NVIDIA 自动填写 context=1048576、max_output_tokens=1048576、max_tokens=1048576、token_limit_parameter=max_tokens；协议/地址控件隐藏，三个官方链接可见。
- AMD 自动填写已核对的 context=1048576；独立输出上限保持未知。实点 AMD 文档入口在新标签打开了正确文档页面。
- 明确手动覆盖预算为 4096，关闭手动覆盖后自动恢复已识别最大值；切换服务商密钥输入清空。
- 原有本机中转 `gpt-6-astra` 打开设置自动将预算改为 128000；保存并启用成功。再次读取后端确认 max_tokens=128000、max_output_tokens=128000、context_window=1050000、activation_status=active、secret_source=dpapi。
- 本次保存只触发既有小额度连接探测，不发送用户作品内容。QA 仍在仓库外独立数据目录，没有迁移或覆盖原有作品。
- 浏览器控制台未出现错误。最终 UI 截图在 maintainer-local QA 输出；不作为共享仓库依赖。
- 此次没有通过终端执行 Playwright 测试文件；真实浏览器验收由内置浏览器完成。没有 NVIDIA/AMD 账户密钥，故未做两家的付费/免费推理验证。

## 后续

当前服务和源码已更新；未重新构建 2026-09-26 的 EXE/ZIP，未运行全仓测试或远程发布。若要交付旧包用户，先整理相关源码再重新打包，不能将 QA 数据与密钥带入交付包。

## 2026-09-27 补充：免费访问标签

- 用户要求在模型服务商列表直接标注免费/试用性质。本次只补标签和限制说明，没有改调用、预算或已保存配置。
- NVIDIA NIM：`免费试用`；AMD Radeon Cloud：`限额免费`。服务商列表和详情标题都显示；详情常驻说明适用范围、密钥、额度/速率限制和以官网政策为准。搜索“免费”可筛出两家。付费/自定义服务商不继承免费标签。
- 没有官方统一截止日期证据，因此不臆造“限时”日期，也不把 NVIDIA AI Enterprise 的 90 天许可试用混同于 API Catalog。
- 来源复核：NVIDIA `https://build.nvidia.com/`、`https://docs.api.nvidia.com/nim/docs/product`、官方论坛 FAQ；AMD `https://amd-aim.github.io/radeon-cloud-docs/api/overview/`。核对时间 2026-09-27。
- 新增标签范围、搜索、HTML 转义、切换后清理的回归用例。执行 `python -X utf8 -m pytest services/halocue/writing/tests/test_model_provider_defaults.py services/halocue/writing/tests/test_settings_controller_safety.py services/halocue/writing/tests/test_settings_hub.py -q --tb=short`：66 passed in 12.54s；`node --check services/halocue/writing/web/app.js` 和本次已跟踪路径 `git diff --check` 通过。
- 内置浏览器确认列表出现两个标签、AMD 详情显示完整配额说明。已重启 QA 服务、更新前端版本号；没有调用真实模型、重新打包或提交其他已有变更。
