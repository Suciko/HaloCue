# HaloCue 1.0 Writing

独立的 HaloCue 写作域纵切。它持有作品、创意简报、故事方向、章节、场景、正文修订、候选方案与不可变的剧本发布版本；只在发布后通过 HTTP 把固定文本交给制作后端。

## 运行

```powershell
cd services/halocue/writing
$env:PYTHONPATH = (Resolve-Path .\src).Path
python -m halocue_writing.server --port 8899
```

打开 `http://127.0.0.1:8899/`。默认数据目录为 `./data`，可通过 `HALOCUE_WRITING_DATA_DIR` 修改。制作后端地址默认为 `http://127.0.0.1:8892`，可通过 `HALOCUE_PRODUCTION_URL` 修改。

未配置模型时，Provider 明确标记为 `fake`：它只用于验证可替换模型边界与完整审查链，不声称执行真实模型调用。设置中心可以测试并启用 OpenAI-compatible 或 Anthropic Provider；正式 BA 写作步骤缺少已校准运行时人物卡时仍会在上下文中报告未就绪。

`ba-writing` 规则源通过 `HALOCUE_BA_WRITING_SKILL_DIR` 注入。仓库不包含
用户人物卡、官方资料或本机 Skill；未配置时服务会明确报告规则源不可用，
不会读取旧电脑上的绝对路径。

### 写作模型激活与运行身份

写作模型使用“先测试、后替换”的原子激活接口：

```text
GET  /api/v1/settings/writing-model
POST /api/v1/settings/writing-model:activate
```

候选连接测试失败时，现有配置、Windows DPAPI 密钥和运行时 Provider 都保持不变。成功激活后会返回非敏感的 `settings_version / config_revision / config_digest / activated_at / last_tested_at`；API Key 不进入 AgentRun、Proposal 或日志。

每次 Agent 和可排队工作流在开始时固定一个 Provider 实例及其配置摘要。运行期间切换模型不会改变该次运行的 Proposal、用量或审查记录；失败运行若检测到配置摘要已变化，会返回 `409 provider_config_changed`，要求用户用当前模型重新发起。真实请求只对 `408 / 429 / 5xx` 和临时网络错误做最多三次有限重试，`401 / 403` 等配置错误立即失败，不会回退成模拟结果。

## ba-writing 运行时

外部 `ba-writing` Skill 会被编译为不可变的 `ba-writing.productized/1.1.0` WritingPack 快照。运行时只加载当前 Workflow 阶段、当前单一写作模式和必要老师规则，不把整份 Skill 作为巨型提示词，也不在服务运行期间跟随外部文件静默变化。

每次场景生成或复写都会建立 `scene-writing-pack/1.0`，固定场景合同、场景级老师在场状态、完整人物主档的运行时投影、已确认事实、压缩且可追溯的资料片段、上一场中段与末尾，以及所有来源修订和哈希。真实 Provider 缺少这些输入时失败闭合；模型正文只接受 `角色: 内容` 或 `旁白: 内容`，非法行和未知说话人不会被静默删除。

`scene.review` 是只读审查 Agent：模型只能返回结构化 `ReviewFinding`，不能改写正文。审查运行会持久化 AgentRun、工具轨迹、JobAttempt、Provider 用量、输入快照、Gate 和三层指纹；用户仍通过 Proposal/Diff 决定正文和资料是否产生新 Revision。

`structure.plan`、`scene.candidate.generate` 和 `memory.extract` 也采用相同的可恢复执行模型：先固定输入快照与 SHA-256，再建立 AgentRun、WorkItem 和 JobAttempt，随后在写事务外调用 Provider。失败后可以从原快照显式重试；作品结构、场景正文或依赖修订已经变化时拒绝重放，不能用新上下文伪装为旧任务恢复成功。

作品对话和可排队写作工作流使用 SQLite 持久 Dispatcher。任务通过 `BEGIN IMMEDIATE` 原子领取，持有带 token 的短租约并定时心跳；第二个服务实例只回收已过期租约，不会把其他活实例的 `running` 任务全部判为失败。取消会同步终结 AgentRun、WorkItem、JobAttempt 和队列租约；所有 Proposal、Finding 和 Gate 在提交前再次检查 AgentRun 状态，因此迟到的 Provider 结果不会产生副作用。相同 `idempotency_key` 的并发重试复用同一结果，只调用一次 Provider。

```text
POST /api/v1/works/{work_id}/agent-jobs
GET  /api/v1/works/{work_id}/agent-jobs/{job_id}
POST /api/v1/works/{work_id}/agent-jobs/{job_id}:cancel
```

可排队的 operation 包括 `scene.candidate.generate`、`scene.draft.generate`、`scene.draft.rewrite`、`scene.review`、`continuity.review`、`release.review`、`memory.extract`、`memory.sweep` 和后台 `knowledge.discover`。同步领域方法继续保留给测试和受控内部调用；正式服务入口会在启动时恢复持久队列。

## Writing Harness

正式工作台不再由各页面分别猜测流程状态。`WritingHarness` 从持久的 Artifact/Revision、Proposal、AgentRun、WorkItem、Gate 和 ScriptRelease 只读推导当前阶段、阻塞原因、唯一推荐操作和可信恢复入口：

```text
GET /api/v1/works/{work_id}/harness
GET /api/v1/works/{work_id}/doctor
```

Harness 状态也包含在作品详情的 `harness` 字段中，所以写操作返回新作品版本后，前端会立即得到同一份下一步判断。失败 Agent 只有在最新运行确实失败且固定输入快照 SHA-256 仍匹配时才显示重试；实际重试仍会重新检查作品版本、对话版本、场景 Revision 和上下文指纹。

Doctor 是只读体检，只检查数据库、Revision、待决定 Proposal、失败 AgentRun 快照、持久队列、Provider、BA WritingPack 和 Dispatcher。它不会自动修复、接受 Proposal、改变 Gate 或重建 ScriptRelease。当前 Fake Provider 会作为非阻塞 warning 明确显示。

### Revision 提交投影

场景正文、人物卡、世界观或 WorkCanon 形成正式 Revision 后，会建立 `commit-projection/1.0`。摘要、检索、记忆待办和审查待办分别持久化，任何一项失败都不会回滚或修改正式内容；重复运行不执行已完成项，补跑只领取失败项，重启后的迟到结果通过 attempt CAS 拒绝。资料 Revision 不需要场景记忆或场景审查，其对应步骤明确记为 `skipped/not_applicable`。

```text
GET  /api/v1/works/{work_id}/commit-projections/{revision_id}
POST /api/v1/works/{work_id}/commit-projections/{revision_id}:run
POST /api/v1/works/{work_id}/commit-projections/{revision_id}:retry
GET  /api/v1/works/{work_id}/projection-search?q={query}&kind={artifact_kind}
```

这些步骤由同一个持久 Dispatcher 在后台推进。服务启动时会幂等扫描既有作品的当前正文与资料 Revision，补登记缺失投影，并按完整 payload 合并重复的 active job；老作品不需要手工保存一次才能获得新 Harness。`summary` 和 `search` 默认是明确标记的确定性派生，不调用模型；`memory_followup` 和 `review_followup` 只建立待办，真正的 BA 记忆提取与审查仍使用 Provider、Proposal 和 Gate。

场景正文形成正式 Revision 后，CommitProjection 还会幂等排队 `knowledge.discover`。它只从该次正式 Scene Revision 提取带 SceneBlock 证据的 WorkCanon 候选，并建立标记为后台建议的 `canon_fact` Proposal；不会生成 `memory_bundle`，不会占用当前写作决策面，也不会静默写入 WorkCanon。相同 Scene Revision 按内容摘要去重，新 Revision 会使旧的待整理建议变为 `superseded`；服务重启不会重复执行已经完成的同 Revision 任务。资料页的“待整理建议”是用户审批入口，作品页只显示安静提示，这类后台建议不阻塞后续场景或发布导航。

`commit-projection-search/1.0` 只查询 Artifact 当前 Revision 的完整索引，校验投影与正式 Revision 的 SHA-256 后返回正式内容及来源。Agent 的人物、世界观和事实检索已使用这一读模型；索引缺失、待处理或损坏时回退到正式 Revision，不把派生结果当作事实源。Harness 只在当前 Revision 的投影失败时提示一个补跑操作，普通同步细节不会进入作品对话。

连续性与发布审查会把每张当前人物卡和它的 Revision/Hash 固定进审查包与 Gate 依赖。审查后修改人物卡会使旧 Gate 失效并要求重新审查；CommitProjection 的完成状态不能替代这一正式依赖检查。

Webnovel Writer 的采用原则、GPL-3.0 许可证边界与明确不采用项见 `docs/webnovel-writer-harness-adoption.md`。

### BA 世界观资料导入

资料库支持 `ba-world-card/full/1.0` JSON 文件的服务端校验与导入：

```text
POST /api/v1/works/{work_id}/world-bible:validate
POST /api/v1/works/{work_id}/world-bible:import
```

文件可包含 `entities`、`rules` 和 `timeline`；每条内容都需要来源、可信状态和作用域。导入会保留原始/清理文件、SHA-256、验证报告和稳定卡 ID；待核对资料不会进入场景上下文，多重身份命中或结构验证失败不会写入 WorldBible。

## 反馈同步

反馈始终先写入本地 `writing.db`。需要同步到独立的 HaloCue 反馈服务时，在启动 1.0 的进程环境中配置：

```text
HALOCUE_FEEDBACK_REMOTE_URL=http://127.0.0.1:8001/api/halocue/feedback
HALOCUE_FEEDBACK_REMOTE_TOKEN=与反代服务相同的 Bearer 访问密码
```

远端不可用时，反馈仍保留在本地并标记为 `pending`；浏览器不会接触远端 Token。

## 作品 Agent 工具边界

作品对话的每一轮都会建立持久化 `AgentRun`，保存输入快照、当前 Workflow Task、权限模式和工具调用。服务端 `AgentToolRegistry` 负责校验工具名称、输入 Schema、风险、允许作用域和是否需要用户确认；Provider 自报的工具名称不会直接被当作成功执行。

AgentRun 查询同时提供 `agent-run-timeline/1.0` 用户摘要时间线。它按发生顺序投影运行开始、受控工具、助手回复、Proposal 和运行结束，供工作台在执行完成后折叠为一行摘要。时间线不包含原始工具参数、缓存用量或模型内部思考链；这些信息仍分别保存在受控运行记录和用量接口中。

```text
GET /api/v1/agent-tools
```

首批工具覆盖正式上下文读取、对话历史读取、人物/世界观/作品事实检索，以及人物卡、世界观卡和事实讨论草稿。资料草稿不会修改正式 Artifact；`create_knowledge_proposal` 会进入 `waiting_user`，只有用户采纳 Proposal 后才产生正式 Revision。`review` 与 `managed` 都不能绕过这条边界。

资料 Proposal 同时保存确定性的 `proposal-impact/1.0` 影响预览，列出直接目标、变更字段、冲突摘要，以及会在后续读取该资料的场景上下文、连续性/OOC 审查和发布 Gate。影响预览不会执行写入；前端可以独立读取，并在采纳时回传其摘要哈希：

```text
GET  /api/v1/works/{work_id}/proposals/{proposal_id}/impact
POST /api/v1/works/{work_id}/proposals/{proposal_id}/accept
```

采纳仍会重新检查作品版本、基准 Revision、候选文件哈希和冲突。影响摘要不一致时返回 `proposal_impact_mismatch`，不会使用新的影响范围替代用户已经审查的内容。

人物卡、世界观、WorkCanon 和故事结构的不可变历史可以按字段比较。默认与当前 Revision 比较，也可用 `against` 指定同一 Artifact 的另一 Revision：

```text
GET /api/v1/works/{work_id}/artifacts/{artifact_id}/revisions/{revision_id}/compare
GET /api/v1/works/{work_id}/artifacts/{artifact_id}/revisions/{revision_id}/compare?against={revision_id}
```

返回 `artifact-revision-comparison/1.0`、字段级 `add/remove/replace`、变更计数和比较摘要。读取前会校验两个 Revision 的 SHA-256；跨作品、跨 Artifact 或损坏 Revision 会以稳定错误结构拒绝，比较操作不会改变当前 Revision。

### 长对话恢复

超过最近 12 条的消息会进入增量维护的 `conversation-summary/1.1`。摘要保存来源范围、消息摘要链、当前用户约束、修正/否决、待确认问题和明确的可信状态；数据库仍保留全部原始消息。Provider 与 AgentRun 快照只接收有界摘要和最近消息，失败重试固定使用原快照，不会漂移到后续讨论。

摘要只是派生的续聊索引，不是 WorkCanon、人物卡、世界观卡或官方证据。涉及正式资料的 Proposal 会重新校验并登记原始用户消息 ID；摘要完整性或来源消息校验失败时，本轮会在模型调用前停止，原始消息不会被删除。摘要容量溢出会明确要求回查原始消息，不能静默当作完整事实继续写入。

### 场景 Conversation Harness

逐场写作使用绑定单一 Scene ID 的持久 `ConversationThread`，不是一次性生成表单。用户可以先连续讨论本场目标、人物边界、节奏和需要保留的正文选择；消息、AgentRun、工具轨迹、Proposal 与正式正文分别保存，服务重启后仍能恢复同一场景对话。场景线程不会出现在全作对话列表，也不能跨作品或跨场景读取。

```text
POST /api/v1/works/{work_id}/threads/{thread_id}/messages:enqueue
POST /api/v1/works/{work_id}/threads/{thread_id}/scene-proposal:generate
```

`messages:enqueue` 只推进讨论并保存结构化运行记录；`scene-proposal:generate` 才会基于当前讨论、固定 SceneContract、当前正文 Revision、BA WritingPack 和可追溯人物/世界资料形成完整正文或改写 Proposal。选中文本会作为显式 selection 进入改写输入。任何权限模式都不能静默写回正文，只有用户采纳 Proposal 后才建立新的不可变 Revision。

工作台只显示 Provider 明确返回的 `reasoning_summary`，并将工具调用折叠为运行摘要；不会展示或伪造模型内部思考链。当前 Provider 不可真实调用、人物卡不完整或 Skill 未就绪时，`SceneReadiness` 返回稳定的 `can_run=false` 与 `blocking_reasons`，界面会禁用发送和形成候选操作，而不是用模拟成功掩盖缺失条件。测试可以注入 Fake Provider 验证完整协议，但生产界面始终明确标注模拟结果。

### 长期记忆

正文保存或正文 Proposal 被采纳后，系统会为该场景修订幂等建立 `memory.extract` 待办。Agent 只能生成 `memory_bundle/1.0` Proposal，候选可包含 `episode_memory`、`scene_state_snapshot`、`open_thread` 和 `decision_record`；用户可以全部采纳、部分采纳或退回。每条正式记忆都使用稳定 ID，以 Artifact/Revision 保存不可变历史，并记录来源场景、正文修订、内容哈希、作用域、版本和可信状态。

```text
GET  /api/v1/works/{work_id}/memories
POST /api/v1/works/{work_id}/scenes/{scene_id}/memory-proposals:generate
POST /api/v1/works/{work_id}/chapters/{chapter_id}/memory:sweep
POST /api/v1/works/{work_id}/scenes/{scene_id}/memory:skip
POST /api/v1/works/{work_id}/memories/{memory_id}/archive
POST /api/v1/works/{work_id}/memories/{memory_id}/restore
```

只有 `active + confirmed` 的记忆会进入后续场景上下文。来源正文或目标记忆的基准 Revision 已变化时，整个 Proposal 会变为 `superseded`，不会部分写入。`release.review` 要求每个待发布场景修订都已完成记忆 Proposal 决策，或者由用户明确记录“本场无需沉淀”；否则 Gate 阻止冻结 `ScriptRelease`。

## 正文修订

场景正文使用 `scene-blocks/1.0`：每个动作或对白块都有稳定 ID。工作台手工保存调用：

```text
POST /api/v1/works/{work_id}/scenes/{scene_id}/manuscript
```

请求必须携带 `expected_version`、`expected_base_revision_id` 与完整 `blocks` 列表。保存总是创建新的不可变 Revision；作品版本或基准正文已变化时会返回冲突。用户手工保存不会调用 Agent，并会替代基于旧正文的待决定 Proposal。`ScriptRelease` 仍导出每个 Revision 的规范纯文本 `text`，制作后端无需理解 SceneBlock。

## 测试

```powershell
python -m pytest -q
```

测试进程会在系统临时目录生成仅含占位规则的完整合成 WritingPack，不读取
维护者本机的 `ba-writing`、人物资料或官方语料。因而全量测试不要求设置
`HALOCUE_BA_WRITING_SKILL_DIR`，也不会因协作者电脑上的 Skill 版本不同而改变结果。
生产运行不使用这份合成夹具，仍按上文要求显式注入真实规则源并失败闭合。
