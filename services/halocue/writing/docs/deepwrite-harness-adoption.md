# DeepWrite Harness 参考与 HaloCue 采用边界

## 判断

DeepWrite 值得参考的不是 Electron 或 Markdown 文件布局，而是它把 Agent 运行拆成四层：

1. 对话层：用户消息、助手回复、Thinking 摘要、工具活动和子 Agent 活动。
2. 运行层：一次运行的输入快照、工具调用、重试、取消、用量和失败状态。
3. 提案层：Agent 只能产生不可变的 Proposal，Proposal 带基准版本、前序提案、审批模式和决定令牌。
4. 提交层：先生成影响预览，再按用户决定执行原子写入；版本或影响发生变化时拒绝提交。

HaloCue 已经有更合适的领域边界：SQLite 持久化、Artifact/Revision、WorkCanon、WritingPack、Gate 和 ScriptRelease。因此采用职责和协议，不复制 DeepWrite 的存储模型。

## 直接采用

### 1. 影响预览是 Proposal 的一等输出

人物卡、世界观卡和作品事实 Proposal 都返回 `proposal-impact/1.0`：

- 基准作品版本和基准 Revision；
- create/update 操作与变更字段；
- 直接目标（人物卡、世界观条目或作品事实）；
- 可能读取该资料的后续消费者（场景上下文、连续性审查、发布审查）；
- 冲突摘要和需要用户决定的项目；
- 对应的稳定摘要哈希。

“可能影响”表示运行时依赖关系，不表示 Agent 已经静默修改了这些对象。

### 2. 预览和采纳必须分开

前端可以先读取 Proposal 及其影响预览。采纳时仍由服务端重新检查作品版本、目标 Revision、冲突和候选文件哈希。影响预览只是用户决策依据，不是写入授权。

### 3. 运行轨迹保持可折叠

工具调用、模型 Thinking 摘要、缓存用量、重试和子 Agent 运行属于运行轨迹；正式资料、正文和长期记忆仍分别存储。聊天消息只显示简短状态，详情通过 AgentRun 查询恢复。

## 改造成 HaloCue 领域模型

| DeepWrite 概念 | HaloCue 对应 | 处理方式 |
| --- | --- | --- |
| `AgentEditProposal` | `Proposal + Revision` | 保留不可变候选和基准修订，不让聊天组件直接写 Artifact |
| `baseRevision` | `base_revision_id` 与作品 `version` | 采纳时双重校验 |
| `approvalMode` | `authorization_policies.mode` | `review` 与受限 `managed` 都不能越过 Gate |
| `expectedImpact` | Proposal 内的 `impact_preview.digest` | 作为用户看到的确切预览；高风险操作可要求回传摘要哈希 |
| `toolCalls / processingSteps` | `agent_tool_calls + AgentRun policy/failure` | 服务端产生权威记录，Provider 自报不能冒充执行成功 |
| `subagentRuns` | 后续 `AgentRun` 子运行 | 子 Agent 只返回受限交接摘要，不递归创建子 Agent |
| 文件写入 | Artifact/Revision 原子替换 | 不引入 DeepWrite 的本地文件作为事实源 |

## 不采用

- 不把所有人物、世界观和正文变成一组 Markdown 文件。
- 不让 Agent 因为使用 `managed` 权限而直接写入 WorkCanon、人物卡、世界观或 ScriptRelease。
- 不把模型内部思考链当作长期记忆；产品只保存可展示的思考摘要和运行状态。
- 不把“影响预览”当成全局图数据库的自动更新；它只描述当前 Proposal 的可推导影响。
- 不复制 DeepWrite 代码。仓库使用 Apache-2.0，只作为架构和交互研究来源；HaloCue 保持独立实现。

## 当前实现顺序

1. 为知识 Proposal 建立 `proposal-impact/1.0` 结构和读取接口。
2. 在采纳前再次验证候选文件、目标 Revision、冲突和作品版本。
3. 把 AgentRun 的轨迹投影为可折叠的用户摘要，缓存用量放到轨迹详情，不塞进聊天正文。
4. 在真实模型接入后，再增加受限子 Agent 运行和可取消的交接摘要。

