# HaloCue 写作 Agent Harness 与工作台演进计划

状态：实施中（阶段 0–3 已通过；阶段 4 协议预验收完成，真实 Provider 验收待用户授权；阶段 5 的 09 发布合同完成，10 同壳集成待外部证据）  
基线日期：2026-08-17  
实施目录：`09-HaloCue-1.0-Writing/`  
统一入口：`http://127.0.0.1:8910/`

## 1. 计划目的

本计划解决的核心问题不是继续给现有页面增加按钮，而是把已经存在的写作后端能力组织成一套易理解、可恢复、可审查的 Agent Harness。

目标体验：

1. 用户在“作品”中通过持续讨论形成全局方向，Agent 同时维护人物、世界、事实和结构建议。
2. 用户在“写作”中选定卷、章、场景，围绕当前范围讨论、生成、局部改写和审查正文。
3. Agent 的工具、公开思考摘要和后台运行可观察，但不会淹没对话。
4. 人物卡、世界规则、事实、关系与正文修改以专用 UI 和 Proposal/Diff 展示，用户决定后才写入正式 Revision。
5. 正式资料、正文、长期记忆、运行轨迹和对话记录继续分开存储。
6. 用户能在刷新、重启、失败重试和跨页面切换后回到同一任务。

## 2. 架构判断

现有后端已经具备多数关键边界：

- `Artifact / Revision` 是正式内容事实源；
- `Proposal` 是 Agent 修改正式内容的唯一候选边界；
- `ConversationThread / AgentRun / AgentToolCall` 保存对话与运行；
- `WorkItem / JobAttempt` 保存可恢复后台任务；
- `WritingPack` 固定 ba-writing 的阶段规则和来源哈希；
- `ReviewFinding / Gate / ScriptRelease` 保存审查与发布交付；
- `CommitProjection` 维护可重建摘要、检索和后续任务；
- Provider 身份已在一次运行中固定，并能区分真实模型和 Fake Provider。

因此不重写领域层。主要新增一个稳定的“Agent 表现层投影”，把分散的运行、工具、Proposal、影响和恢复状态整理成前端可直接渲染的结构。

实施前必须填写和复核下表。新功能不得建立平行数据库、第二套任务状态或绕过现有服务的直接写入路径。

| 边界 | 现有实现路径/符号 | 必须复用 | 允许新增 | 禁止旁路 |
| --- | --- | --- | --- | --- |
| SQLite 与原子文件 | `repository.py` 的 `Repository.transaction`、`atomic_write_bytes/text` | 事务、现有表、原子替换和 Hash 校验 | 向后兼容的表/列迁移、只读查询 | 前端写文件、另建内存事实源 |
| Artifact/Revision | `repository.py` 的 `artifacts/revisions`；`service.py` 的 `_add_revision` | 当前 Revision、来源、版本检查 | 表现层引用和比较投影 | 直接更新正式内容而不建 Revision |
| Proposal/影响 | `service.py` 的 `accept_proposal`；`proposal_impact.py`；`GET .../proposals/{id}/impact` | 候选文件、基准 Revision、影响摘要、采纳事务 | 专用审批 UI 和表现层 Schema | 聊天组件直接写回 Artifact |
| 对话/Agent 运行 | `service.py` 的 `create_conversation_thread`、`post_conversation_message`、`enqueue_conversation_message`、`get_agent_run` | ConversationThread、AgentRun、AgentToolCall、固定输入快照 | Timeline 只读投影、游标 | 第二套聊天记录或运行状态机 |
| 取消/重试/队列 | `service.py` 的 `cancel_agent_run`、`retry_agent_run`；`agent_dispatcher.py` 的 `AgentDispatcher` | WorkItem、JobAttempt、租约、幂等键和迟到结果保护 | 用户可理解的恢复卡 | 浏览器本地重试冒充后台恢复 |
| ba-writing | `ba_skill_runtime.py` 的 `BaWritingSkillRegistry/BaWritingPromptAssembler`；`workflow_pack.py` | 固定 WritingPack、Template 版本、来源 Hash | 新 Workflow Template 和路由投影 | 将 Skill 原文作为全局长提示或运行时数据库 |
| Provider | `providers.py` 的 `WritingProvider/FakeWritingProvider/LLMWritingProvider`；`service.py` 的 Provider 捕获 | 一次运行的 Provider 身份、用量、失败语义 | 能力声明和缓存观测字段 | 真实调用失败后回退 Fake 成功 |
| CommitProjection | `commit_projection.py` 的 `CommitProjection` | 当前 Revision 派生、幂等补跑、Hash 校验 | 关系图/时间线等可重建投影 | 派生数据反向成为事实源 |
| Harness/Doctor | `writing_harness.py` | 作者状态、阻塞原因、唯一恢复动作 | Agent 表现层消费同一投影 | 页面各自推导下一步 |
| Gate/ScriptRelease | `service.py` 的审查流程、`freeze_release/get_release`；`gates/script_releases` 表 | 依赖失效、冻结事务、不可变交付 | 发布表现层和交接摘要 | UI 自行判定 Gate 通过 |
| HTTP/错误 | `app.py` 的 `WritingRequestHandler`；`errors.py` 的 `DomainError` | `/api/v1`、`{ok,error:{code,message,details}}` | 新稳定路由和 Schema 版本 | 临时返回形状或吞掉错误 |

参考来源及采用边界：

| 项目 | 采用内容 | 不采用内容 | 许可证边界 |
| --- | --- | --- | --- |
| DeepWrite | 资源范围、Agent、正式文稿并排；阶段上下文；Diff 审批 | Markdown 文件事实源、自动写回 | Apache-2.0，可研究并独立实现 |
| Hermes Desktop | Chat 为主界面；持久工作窗格；工具摘要；记忆与 Skill；不抢焦点 | 官网视觉、无边界自治 | MIT，可参考设计和代码结构，仍优先独立实现 |
| Cherry Studio | 会话侧栏、稳定 Composer、附件和模型入口、设置管理 | 消息下长期展示 Token；通用助手堆叠 | AGPL-3.0，只研究交互 |
| assistant-ui | Tool UI、Generative UI、人工审批、独立 Artifact Surface | 把前端组件状态当正式事实 | MIT，可评估组件思想，不要求引入 React |
| Webnovel Writer | 预检、提交账本、投影、Doctor、恢复报告 | `.story-system` 文件事实源、GPL 代码 | GPL-3.0，只研究行为和架构 |

## 3. 产品信息架构

### 3.1 全局导航

保留一个应用壳和一个入口：

- 作品：全局创作讨论与作品方向；
- 写作：卷、章、场景与正文；
- AA 制作：消费不可变 ScriptRelease；
- 资料：正式人物卡、世界规则、事实、证据和关系；
- 任务：失败、等待、可重试和后台执行；
- 设置：模型、权限、归档会话、偏好和诊断。

全局导航只切换产品域，不重复显示当前页面内部动作。AA 制作继续由统一入口承载，但写作模块不进入 AA 编译、映射或安装实现。

### 3.2 作品页

作品页是全局 Agent 工作面，不是资料表单集合。

桌面布局：

- 左侧：作品身份、会话列表、新建对话、会话菜单；
- 中央：连续对话、工具摘要、生成式产物卡和 Composer；
- 临时右侧检查器：只在用户主动查看方向、人物卡、世界规则、关系或 Proposal 时打开；关闭后回到对话，不改变当前会话。

规则：

- 不在顶部重复显示当前会话名称；
- 已归档会话不占用日常侧栏，在设置或搜索中查找；
- 全局方向敲定后可以折叠早期引导，但用户可重新打开；
- “人物卡”“世界观”“事实”不是固定的大表单，而是 Agent 可生成和更新的正式产物；
- 用户仍可从“资料”手工新建或修改。

### 3.3 写作页

写作页只负责具体卷、章和场景。

桌面布局：

- 左侧 Binder：卷、章、场景稳定树和当前范围状态；
- 中央：正文编辑器、候选、Diff 或审查结果；
- 右侧：绑定当前章节或场景的 Agent；
- 底部状态仅在确有保存、冲突或后台任务时出现，不保留空占位栏。

用户进入写作页前必须选定或建立写作范围。全局方向讨论留在作品页；章节细纲和场景讨论留在写作页。

### 3.4 资料页

资料页是正式资源管理器，不是新用户必经步骤。

- 人物：官方参考卡、自定义卡、作品覆盖层和归档状态；
- 世界：官方基础、作品自定义规则、地点、组织、时间线；
- 事实：已确认、待确认、冲突和来源；
- 关系：人物关系和变化轨迹的只读图形投影，正式关系仍来源于版本化资料；
- 证据：文件、引用范围、来源 Hash 和使用位置。

常用创建操作收敛为一个“添加”菜单，复杂表单使用弹窗或检查器，不把所有输入常驻展开。

### 3.5 移动端

移动端不压缩桌面三栏：

- 作品页：会话列表抽屉、单列对话、底部 Composer；
- 写作页：正文、Agent、审查三个单任务页签；
- 卷章场景树：独立抽屉；
- Proposal/Diff：全屏审查页；
- 每个页面保留明确返回路径和当前作品/章节/场景身份。

## 4. Agent Harness 交互合同

### 4.1 一次 Agent 运行的可见结构

前端按照以下层级展示，不直接拼接数据库记录：

1. 用户请求；
2. Agent 的自然语言回应；
3. 可折叠“正在处理/运行过程”；
4. 必要时出现正式产物卡或 Proposal；
5. 需要用户决定时暂停；
6. 采纳、部分采纳、退回或追加约束后继续同一会话。

运行过程默认只显示一行，例如：

```text
已查阅 2 张人物卡、4 条世界规则，并检查当前章节连续性
```

展开后才显示工具名称、状态、时间和用户可理解的结果摘要。原始参数、缓存输入、API Key、内部 Prompt 和隐藏思维链不进入对话。

### 4.2 Thinking

- 仅显示 Provider 主动返回、允许公开的 `reasoning_summary`；
- 运行中显示简短“正在分析当前场景”等状态；
- 默认折叠，用户可展开；
- 不生成、推测或保存隐藏思维链；
- 不把 Thinking 当长期记忆或正式证据。

### 4.3 生成式产物卡

Agent 使用受限组件词汇渲染专用卡，而不是任意生成 HTML。

第一批组件：

- `DirectionProposalCard`：作品方向、核心冲突、语气和下一步；
- `CharacterProposalCard`：人物身份、声音、边界、证据和更新项；
- `WorldRuleProposalCard`：规则、作用域、例外、冲突和影响；
- `CanonProposalCard`：事实内容、来源、适用范围和可信状态；
- `BlueprintProposalCard`：卷章场景结构和依赖；
- `SceneDraftProposalCard`：正文候选、基准 Revision 和 Diff；
- `ReviewFindingCard`：OOC、连续性、信息归属和严重度；
- `RecoveryCard`：失败原因、已保存进度和唯一恢复操作。

卡片只负责展示和收集用户决定。正式写入仍由后端 Proposal 采纳接口完成。

### 4.4 Proposal 审批

统一信息层级：

```text
小鸟游星野 · 3 项更新建议
2 项来自直接证据 · 1 项为行为推断

触发因素
不愿被迫停留
→ 不愿被迫停留；封闭空间会放大警觉

未发现冲突 · 将影响人物卡、场景行为约束和连续性检查

已选择 2 / 3              应用 2 项修改
```

统一操作：

- 主操作：`应用 N 项修改`；
- 次操作：`全部选择`、`查看差异`、`退回`；
- 每项可以独立选择；
- 推断与直接证据使用不同标记，但不展示低价值的置信度数字；
- 冲突摘要直接显示“未发现冲突”或“与 N 条现有设定存在冲突”；
- 世界规则和 WorkCanon 必须显示影响预览；
- 采纳时服务端重新校验作品版本、目标 Revision、候选 Hash 和冲突摘要。

### 4.5 Agent 权限

提供两个用户可理解的模式：

- 审核模式：所有正式修改都等待用户决定；
- 托管模式：Agent 可自动执行读取、检索、上下文装配、确定性投影和低风险后台检查。

托管模式仍不能自动：

- 修改正文、人物卡、世界规则或 WorkCanon；
- 采纳 Proposal；
- 通过 Gate；
- 冻结 ScriptRelease；
- 启动 AA 安装或改变用户工程。

权限显示在 Composer 的紧凑菜单中，不在对话正文重复提示。

### 4.6 Composer

- Enter 发送，Shift+Enter 换行；
- `+` 菜单统一承载文件、引用、人物、世界规则和当前选区；
- 模型、权限和当前作用域使用紧凑菜单；
- 发送、停止、重试使用熟悉图标和清晰状态；
- 运行期间允许停止，也允许追加一条“转向”要求；
- 不显示“本来就是聊天框”的冗余说明；
- 不因模式切换复制对话或让 Composer 向下无限增长。

## 5. 后端演进

### 5.1 Agent 表现层投影

新增只读 `AgentPresentationQuery` 投影服务，将现有数据投影为稳定结构。消息发送、取消和重试继续复用 `WritingService` 的现有 Agent 命令；“运行中转向”必须先定义持久语义和测试，再作为命令扩展，不能进入只读投影服务。

- 会话与当前作用域；
- 消息片段；
- 运行状态和公开思考摘要；
- 折叠工具活动；
- 正式产物引用；
- 等待决定的 Proposal；
- 唯一恢复动作；
- Provider、用量和缓存的紧凑运行元数据。

建议查询接口：

```text
GET  /api/v1/works/{work_id}/agent-surfaces/{surface_id}
GET  /api/v1/works/{work_id}/threads/{thread_id}/timeline
```

继续复用的命令接口：

```text
POST /api/v1/works/{work_id}/threads/{thread_id}/messages:enqueue
POST /api/v1/works/{work_id}/agent-runs/{run_id}:cancel
POST /api/v1/works/{work_id}/agent-runs/{run_id}:retry
```

接口名在实施前以 `app.py` 的现有路由风格复核。Timeline 使用游标增量读取；首版允许轮询，不为展示层提前引入复杂消息基础设施。

### 5.2 事件类型

统一表现层事件：

- `message.user`、`message.assistant`；
- `run.started`、`run.reasoning_summary`、`run.waiting_user`、`run.completed`、`run.failed`、`run.cancelled`；
- `tool.started`、`tool.summary`、`tool.failed`；
- `artifact.presented`；
- `proposal.presented`、`proposal.decided`、`proposal.stale`；
- `recovery.available`。

事件是现有领域记录的投影，不成为新的事实源。

### 5.3 ba-writing 阶段路由

ConversationThread 保持连续，但每轮任务根据当前产品范围选择 Workflow Template：

| 用户位置 | 默认 Workflow |
| --- | --- |
| 作品初始讨论 | `brief.build` |
| 方向比较 | `blueprint.generate` |
| 人物/世界确认 | `canon.assemble`、`character.prepare` |
| 章节规划 | `chapter.blueprint.generate` |
| 场景讨论与生成 | `scene.context.assemble`、`scene.draft.generate` |
| 局部改写 | `scene.draft.rewrite` |
| 场景检查 | `scene.review` |
| 跨场景检查 | `continuity.review` |
| 发布检查 | `release.review` |

路由必须保存 Template ID、版本、WritingPack 版本、来源 Hash、固定输入和失败状态。Agent 可以建议切换任务，但不能绕过阶段所需的正式依赖。

### 5.4 资料维护

Agent 对人物、世界和事实的维护流程：

```text
发现候选事实
→ 查找当前正式 Revision
→ 检索证据和潜在冲突
→ 创建 Proposal + 影响预览
→ 对话中展示产物卡
→ 用户选择并应用
→ 创建新 Revision
→ 触发 CommitProjection
→ 使依赖的审查 Gate 失效
```

后台可以生成“待整理建议”，但不能把建议直接写进正式资料。重复建议应按目标、基准 Revision 和内容摘要去重。

### 5.5 缓存与上下文

- 固定且可复用的前缀：WritingPack、模式规则、稳定人物卡和世界规则；
- 变化部分后置：当前指令、当前选区、最近场景片段；
- 长篇上下文优先使用正式 Revision 的确定性摘要和检索投影；
- 必须保留上一节中段与末尾的可追溯片段；
- 每次运行记录 `input_tokens / output_tokens / cached_input_tokens / cache_write_tokens / estimated_cost`；
- 主对话只显示一句运行摘要，详细数据放入运行详情和设置诊断；
- Fake Provider 不产生或伪报真实缓存收益。

## 6. 分阶段实施

阶段 0 是所有功能实现的强制前置 Gate。必须先完成基线截图、导航/返回状态测试、设计 Token 和 `agent-presentation/1.0` Schema；阶段 0 验收通过后，才进入阶段 1–5。Schema 工作属于阶段 0，只读接口实现属于阶段 1。

每阶段验收记录必须包含：固定测试夹具、可执行测试命令、预期断言、浏览器状态与视口、证据保存路径和验收负责人。仅描述性人工判断不构成完成。统一证据目录为：

```text
09-HaloCue-1.0-Writing/artifacts/acceptance/<phase>/<yyyy-mm-dd>/
```

每个阶段至少保留一个命名端到端夹具：`phase0-shell-baseline`、`phase1-work-agent`、`phase2-scene-writing`、`phase3-knowledge-impact`、`phase4-real-provider`、`phase5-release-handoff`。

### 阶段 0：基线和 UI 合同

目标：冻结当前可用能力，建立重构不会破坏的合同。

任务：

1. 记录作品页、写作页、资料页、任务页的桌面和移动基线截图。
2. 建立全局 Shell、面板宽度、内容轴、Composer、按钮、菜单、空状态和 Proposal 的设计 Token。
3. 建立统一图标表，不再使用文字方块或混合图标风格。
4. 为作品、写作和 AA 制作建立唯一 active 导航与返回状态测试。
5. 固定 Agent Presentation 的 JSON Schema 和错误结构。

完成标准：

- 重构前测试全绿；
- 每个主要页面有高清基线；
- 设计 Token 无重复来源；
- 后续阶段不再通过文件尾覆盖修复主布局。

### 阶段 1：作品 Agent Harness

目标：把作品页变成真正的全局创作 Agent。

任务：

1. 重建会话侧栏，修复省略菜单、截断、滚动和归档入口。
2. 对话正文、工具摘要、Thinking、产物卡和 Composer 使用同一阅读轴。
3. 接入方向、人物、世界规则和事实的生成式产物卡。
4. 把早期 Brief、方向和资料确认合并为连续讨论，不再跳转资料库完成第三步。
5. 实现阶段性下一步：当前步骤未满足时解释阻塞原因；已满足时提供一个主操作。
6. 实现 Agent 运行取消、失败恢复和追加约束。

完成标准：

- 用户能从一句想法持续讨论到可审查的 Brief/方向 Proposal；
- 人物卡和世界规则建议可在对话中查看、选择并应用；
- 工具和 Thinking 默认折叠；
- 页面没有重复会话标题、常驻无用右栏或被截断底部操作；
- 刷新和重启后恢复同一会话与待决定 Proposal。

### 阶段 2：写作工作台

目标：形成“范围树 + 正文 + 场景 Agent”的稳定工作面。

任务：

1. 统一卷、章、场景 Binder，补齐新建卷、章节和场景的清晰入口。
2. 进入写作前明确当前作品、卷、章、场景和承接来源。
3. 正文改为适合 AA 剧本的结构化块编辑器：头像/说话人、对白、旁白和必要动作标记。
4. 保留稳定 SceneBlock ID，不以 DOM 顺序代替身份。
5. 接入场景 Agent 的多轮讨论、候选生成和公开运行轨迹。
6. 实现划选文本 → 追加要求 → 生成 Diff → 逐项/全部应用。
7. 实现全场风格、旁白比例、OOC 和节奏检查。
8. 桌面左右栏独立收起；移动端使用正文/Agent/审查单任务切换。

完成标准：

- 可以从章节范围进入一个场景，讨论、生成候选、查看 Diff 并采纳为新 Revision；
- 场景切换不会串对话、串 Proposal 或串选区；
- 中央正文空间在 1366×768 仍可用；
- 手机 390×844 不出现桌面三栏压缩或横向滚动。

### 阶段 3：资料维护与影响审查

目标：让 Agent 共同维护作品知识，而不是让用户手工填完所有资料。

任务：

1. 统一人物、世界规则和 WorkCanon Proposal 的选择与部分采纳。
2. 增加影响消费者、现有冲突、重复规则和审查失效预览。
3. 展示直接证据与 Agent 推断的来源差异，不展示伪精确置信度。
4. 增加只读关系图、时间线和章节结构图，全部来自当前 Revision 投影。
5. 增加资料变更历史和回到旧 Revision 的比较入口。
6. Agent 后台发现新事实时建立待整理建议，不打断当前写作。

完成标准：

- 人物卡、世界规则和事实都能从对话产生并经过审批进入正式资料；
- 冲突与影响在应用前可见；
- 关系图和时间线可重建，不成为事实源；
- 资料变化正确使相关 OOC、连续性和发布 Gate 失效。

### 阶段 4：真实模型、缓存与可观察性

目标：验证真实 Provider 下的质量、成本和恢复能力。

前置条件：实施前指定一个必测 Provider/模型、凭据提供方式、单次纵切费用上限和无凭据时的明确阻塞状态；Fake Provider 不可替代此阶段验收。凭据不得写入测试夹具、截图或文档。

任务：

1. 使用用户配置的真实 Provider 完成作品讨论和一个场景纵切。
2. 对 ba-writing Prompt 做稳定前缀分层和缓存命中测试。
3. 记录真实 Token、缓存、时延、重试和费用，不在主对话制造噪声。
4. 增加 Provider 不支持缓存或 reasoning summary 时的明确能力降级。
5. 建立长对话压缩、上一节中段/末尾续写和检索命中回归。
6. 对关键任务支持局部重跑，不重复消耗已经固定的步骤。

完成标准：

- 至少一个真实 Provider 完成全纵切；
- Provider 失败不会回退成 Fake 成功；
- 缓存命中数据来自真实响应；
- 同一运行的 Provider 身份、成本和产物归属一致；
- 长对话压缩后仍能追溯正式来源。

### 阶段 5：审查、发布与 AA 交接

目标：完成写作域闭环并稳定交给制作域。

任务：

1. 统一场景、连续性和发布审查的 Finding UI。
2. 将阻塞项、警告和已处理项分层，不展示内部日志。
3. 冻结前重新校验正文、人物、世界、Canon、WritingPack 和 Gate 依赖。
4. ScriptRelease 页面展示版本、Hash、来源和影响摘要。
5. 通过现有适配器把 ScriptRelease 交给 AA 制作；不复制或调用 AA 内部编译细节。
6. 09 工作树仅实现并验证 ScriptRelease/导航适配器合同，不修改 08/10。由明确指定的集成工作树负责人在 10 中完成同壳接入；其提交 ID 和验收结果作为阶段 5 的外部依赖证据。

完成标准：

- 未通过 Gate 时不能冻结；
- 冻结后 ScriptRelease 不可变；
- 09 合同验收：AA 制作只读取合同，不依赖写作数据库内部结构；
- 10 集成验收（外部负责人）：从写作切换 AA 制作不刷新整个应用壳、不闪白、不出现第二入口；
- 若 10 的外部集成证据尚未提供，阶段 5 只能标记为“09 合同完成、集成待验收”，不能宣称全阶段完成。

## 7. 测试与浏览器验收

### 7.1 后端

必须覆盖：

- ConversationThread、AgentRun、Proposal 和 Revision 的重启恢复；
- 同一作品不同场景的隔离；
- 乐观锁和过期 Proposal；
- 部分采纳和重复提交幂等；
- Agent 取消、失败、重试和旧进程迟到结果；
- WritingPack/Provider/正式资料变化导致的输入失效；
- CommitProjection 局部失败和补跑；
- Gate 依赖失效和 ScriptRelease 冻结；
- Fake/真实 Provider 标记、费用和缓存数据真实性。

### 7.2 前端合同

必须覆盖：

- 每个当前决策面仅有一个视觉主操作；Composer、打开的 Proposal、Diff 审查等彼此独立的决策面可以各有一个主操作，但同一决策面不得出现竞争性主按钮；
- Enter 发送、Shift+Enter 换行、Esc 关闭顶层可关闭界面；
- 会话、作品、章节和场景切换不串状态；
- 归档、恢复、菜单键盘导航和焦点返回；
- Proposal 全选、部分选择、退回、过期和冲突；
- 侧栏收起后中心内容扩展，重新打开后状态保留；
- 后台运行更新 Badge，不抢焦点、不自动打开检查器；
- 隐藏区域使用 `inert/aria-hidden`，不可继续获得焦点。

### 7.3 真实浏览器矩阵

每次明显 UI 修改后检查：

| 视口 | 重点 |
| --- | --- |
| 1920×1080 | 宽屏三栏、阅读轴、过度留白 |
| 1440×900 | 标准桌面主验收 |
| 1366×768 | 低高度、Composer 和底部操作可见性 |
| 390×844 | 移动导航、抽屉、单任务切换、触控尺寸 |

每个视口都检查字体、对比度、溢出、滚动容器、返回路径、焦点、Console error/warning 和网络失败状态。截图必须保存原分辨率，不用模糊缩略图替代验收。

## 8. 视觉与组件约束

- 延续墨青、竹青和暖米纸基础色，但减少大面积单一绿色；
- 普通中文正文至少 14px，辅助文字原则上不低于 12px；
- 扁平优先，不做卡片套卡片；
- 页面区域用留白和单一发丝线分组；
- 常规按钮使用统一高度、圆角、图标和按压反馈；
- 省略菜单不显示重复 Tooltip，菜单中使用明确动词；
- 高风险操作使用文字确认，不只依赖颜色；
- 工具、Thinking 和运行详情默认折叠；
- 动画只服务状态变化，约 100-180ms，并尊重 `prefers-reduced-motion`；
- 后台事件不能自动导航、打开侧栏或抢走输入焦点。

## 9. 明确不做

- 不把 ba-writing Skill 原文变成一条超长聊天提示；
- 不把 Agent、聊天记录或派生摘要变成事实源；
- 不自动采纳正文、人物、世界规则或 WorkCanon 修改；
- 不展示或伪造隐藏思维链；
- 不把缓存和 Token 明细塞进每条消息；
- 不把关系图或思维导图作为正文编辑器；
- 不复制 GPL/AGPL 项目代码；
- 不修改 `08-HaloCue-1.0/`、`10-HaloCue-1.0-Integrated/`、`01-完整程序/aa/`、`06-安卓端/` 或 0.9.2 运行数据；
- 不在写作模块实现 AA 编译、骨骼、安装或 Android。

## 10. 实施顺序与提交策略

阶段 0 是下面所有功能项的强制前置 Gate。先完成基线截图、导航/返回测试、设计 Token 和 `agent-presentation/1.0` Schema，再实施只读接口和页面纵切。

按可运行纵切提交，不按“先写完所有后端、再写所有前端”拆分：

1. 阶段 0：基线、Token、`agent-presentation/1.0` Schema 和合同测试；
2. `AgentPresentationQuery` 只读接口和测试；
3. 定义运行中转向的持久化语义、幂等规则、旧运行结果处理和合同测试；验收通过后再实现 Composer 的追加约束 UI 与命令接口；
4. 作品页单会话纵切：消息 → 工具摘要 → 人物/规则 Proposal → 部分采纳；
5. 作品页完整会话侧栏、归档和恢复；
6. 写作页单场景纵切：讨论 → 候选 → Diff → Revision；
7. 卷章场景 Binder 与移动端单任务导航；
8. 资料影响审查、关系图和时间线投影；
9. 真实 Provider、缓存与成本验收；
10. 发布 Gate、ScriptRelease 和统一入口联调。

每个提交都应：

- 保持 API 版本和错误结构稳定；
- 带对应单元/HTTP/UI 合同测试；
- 对明显 UI 改动保存真实浏览器截图；
- 更新 `CONTEXT.md`，只追加本阶段真实完成内容；
- 不把未实现按钮显示为可用；
- 不回退其他工作树或用户已有改动。

## 11. 下一批可直接执行的工作

下一批聚焦阶段 0 和阶段 1 的最小闭环：

1. 保存作品页、写作页、资料页、任务页在 1920×1080、1440×900、1366×768、390×844 下的原分辨率基线截图与 Console 记录。
2. 固定 Shell、内容轴、Composer、按钮、菜单、空状态和 Proposal 的设计 Token，并建立禁止文件尾主布局覆盖的静态合同。
3. 补齐唯一 active 导航、刷新/返回恢复和隐藏区域 `inert/aria-hidden` 测试。
4. 为现有 `ConversationThread / AgentRun / AgentToolCall / Proposal` 定义 `agent-presentation/1.0` Schema。
5. 完成阶段 0 验收记录后，新增单会话 Timeline 读取接口，先使用游标轮询，不引入 WebSocket 重构。
6. 重建作品 Agent 消息渲染器，区分自然语言、折叠工具、公开 Thinking、产物卡和恢复卡。
7. 把现有知识 Proposal 接入统一审批卡：`全部选择`、`应用 N 项修改`、冲突与影响摘要。
8. 修复作品会话侧栏的归档、菜单、滚动和底部操作层级，并再次完成四种视口验收。

这批完成后再进入写作页重构，避免同时拆动作品页、写作页和资料页而失去可验证的纵切。
