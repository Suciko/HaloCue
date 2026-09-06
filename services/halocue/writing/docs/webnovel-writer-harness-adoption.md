# Webnovel Writer Harness 参考与 HaloCue 采用边界

## 研究基线与许可证

- 仓库：`lingfengQAQ/webnovel-writer`
- 研究提交：`2041abad78211e29a67a2f0c64b2a97a747dce57`
- 研究版本：`6.2.1`
- 许可证：GPL-3.0

GPL-3.0 会对直接复制和组合发布带来传播义务。HaloCue 本阶段只研究可观察行为、状态机、数据合同和交互层级，代码保持独立实现；没有复制该仓库的 Python、Skill、Dashboard 或文件模板。

## 值得采用的 Harness 原则

### 一份当前状态

`project-status`、`doctor`、写章流程和 Dashboard 使用同一套阶段判断。HaloCue 对应为 `WritingHarness` Module：从持久的 Artifact/Revision、Proposal、AgentRun、WorkItem、Gate 和 ScriptRelease 推导作者视角状态，前端不再自行猜测下一步。

### 固定输入与可信恢复

参考项目通过步骤账本、文件签名和 `write-resume` 找到第一个失效步骤。HaloCue 已有更适合产品域的 AgentRun 输入快照和 SHA-256：只有快照仍完整、最新运行确实失败时，Harness 才公开 `agent.retry`；真正重试仍由现有版本、作用域和上下文指纹检查决定是否允许。

### 提交与投影分离

参考项目以 accepted `CHAPTER_COMMIT` 为写后真源，再投影到状态、索引、摘要和记忆。HaloCue 不引入相同文件模型，而保留：

- 正文和资料以 Artifact/Revision 为事实源；
- Agent 只产生 Proposal；
- 用户决定后才建立新 Revision 或长期记忆；
- Gate 是发布判断；
- ScriptRelease 是交给 AA 制作的不可变交付物。

当前已增加独立 `CommitProjection`：场景正文、人物卡、WorldBible 或 WorkCanon 形成正式 Revision 后，系统为固定 Revision 建立 `summary / search / memory_followup / review_followup` 四个派生步骤。每步独立保存输入摘要、尝试次数、输出引用与哈希、错误或跳过决定；局部失败不会回滚 Revision，也不会重跑已完成项。资料 Revision 的场景记忆与场景审查步骤明确记为 `skipped/not_applicable`，不伪装成执行成功。

投影执行使用持久 Dispatcher，进程重启会把中断项标为可重试失败。启动期调和会幂等补登记既有作品的当前正式 Revision，并以完整 payload 合并重复的 active job。完成写入使用 attempt CAS，旧进程迟到结果不能覆盖新的补跑结果。摘要与检索默认使用确定性算法，不为了维护投影额外消耗四次模型调用；真正的长期记忆提取和审查仍进入 BA WritingPack、Provider、Proposal 与 Gate 边界。

### 作者报告与系统诊断分离

普通界面只显示：当前结论、阻塞原因、一个主操作。模型参数、缓存、原始工具参数和完整错误留在运行或 Doctor 视图。`WritingHarness.doctor` 当前只读检查数据库、Revision、待决定 Proposal、失败 AgentRun 快照、持久队列、Provider、BA WritingPack 和 Dispatcher，不自动修复数据。

## HaloCue 的独立实现

`writing-harness-status/1.0` 固定返回：

- `outcome`：`ready / in_progress / needs_user / blocked / completed`
- `phase` 与一句作者可理解的 `headline`
- 五段高层 `progress`
- `blockers` 与非阻塞 `warnings`
- 唯一 `primary_action` 和少量 `secondary_actions`
- 仅在可信快照存在时返回 `resume`

`writing-harness-doctor/1.0` 是只读体检，不改变作品、运行或队列状态。它也校验当前 Revision 的 CommitProjection 输出哈希，并区分“正文可信、派生维护部分失败”。正式工作台左栏的推荐行动读取同一 Harness 投影；普通后台同步不打断创作，只有当前 Revision 的投影失败时才显示一个“只重试未完成项”操作。

`commit-projection/1.0` 的稳定接口为：

```text
GET  /api/v1/works/{work_id}/commit-projections/{revision_id}
POST /api/v1/works/{work_id}/commit-projections/{revision_id}:ensure
POST /api/v1/works/{work_id}/commit-projections/{revision_id}:run
POST /api/v1/works/{work_id}/commit-projections/{revision_id}:retry
POST /api/v1/works/{work_id}/commit-projections/{revision_id}/items/{kind}:skip
GET  /api/v1/works/{work_id}/projection-search?q={query}&kind={artifact_kind}
```

`commit-projection-search/1.0` 只读取各 Artifact 当前 Revision 对应的 `done` 检索输出，并同时校验派生输出和正式 Revision 的 SHA-256。命中结果返回固定 Revision、Hash 和正式结构化内容；旧 Revision 不进入当前结果。Agent 的人物、世界观和作品事实工具已经使用该读模型，投影缺失、尚未完成或损坏时回退到正式 Revision，因此派生维护失败不会让 Agent 丢失事实。

CharacterCard 已进入连续性与发布审查包，并作为 `dependency_refs` 固定到 Gate。人物卡的当前 Revision 或 Hash 变化时，旧审查不再有效；这属于正式依赖失效，和可补跑的 CommitProjection 状态严格分开。

## 明确不采用

- 不复制 GPL-3.0 实现代码或文件模板。
- 不把作品事实源改成 `.story-system` 或 Markdown 目录。
- 不把 Chapter 当成唯一原子单位；HaloCue 保留 Scene 的稳定 ID 与场景级 Proposal/Diff。
- 不让 Data/Memory Agent 直接写正式资料。
- 不因为使用“托管权限”而跳过 Proposal、版本检查或 Gate。
- 不在作者主界面展示原始日志、缓存统计或模型内部思考链。
- 不为 Dashboard、作品页和写作页分别维护状态算法。

## 下一阶段

下一阶段应让场景上下文装配按需消费当前 Revision 的检索读模型，并把人物卡、世界观和 WorkCanon Revision 纳入审查快照的依赖失效判断。特别是人物卡变化必须使相关 OOC/发布审查失效，不能用 CommitProjection 状态代替正式依赖校验。
