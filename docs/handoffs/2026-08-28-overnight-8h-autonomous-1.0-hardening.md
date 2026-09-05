# HaloCue 1.0 夜间 8 小时无人值守加固任务

## 给下一对话的执行指令

读取本文件后，建立一个持续约 8 小时的执行目标并直接开始工作。用户夜间不会参与，不要等待确认、不要提出中途问题；在授权范围内采用最保守的合理默认值。如果某项连续三次仍被同一外部条件阻塞，记录证据并立即转入下一项，不要空等。任务结束时只提交一份可复查的晨间报告。

## 任务目标

把当前 `feature/1.0-runtime` 工作树推进到“可作为 HaloCue 1.0 候选版本继续人工验收”的状态：

1. 全量自动测试和浏览器验收有可复查结果。
2. 当前已知的确定性代码回归得到修复和回归测试。
3. 写作、冻结、生产、编译、隔离 AA 安装的闭环再次通过。
4. 纯旁白和普通人物卡两条路径都保持正确门禁。
5. 所有无法在无人值守环境验证的外部项被准确隔离，不伪造成功。

这是一项 1.0 稳定性与验收工作，不是 1.1/1.2 新功能开发，也不是重构项目架构。

## 当前起点

- 仓库：HaloCue。
- 分支：`feature/1.0-runtime`，开始本任务时相对远端 ahead 2。
- 当前工作树很脏，且多个目标文件在本任务之前就已有未提交修改。
- 上一份修复交接：`docs/handoffs/2026-08-27-production-embed-and-narrator-only.md`。
- 最近已验证：
  - 198 项相关测试通过。
  - 4 个视口、5 类边界的质量回归通过。
  - 真实 `gemini-3.7-flash` 返回 `narrator_only=true`、空人物卡，并成功确认。
  - 隔离 AAP 已成功生成并安装。
- 现有最终质量报告：`.scratch/clean-final-loop-20260827-01/report-final/report.json`。

## 开始前必须读取

1. `AGENTS.md`
2. `.agents/skills/halocue-session-governance/SKILL.md`
3. `docs/product-direction-1.x.md`
4. `CONTEXT-MAP.md`
5. `contexts/client/CONTEXT.md`
6. `contexts/backend/CONTEXT.md`
7. `contexts/ai-galgame/CONTEXT.md`
8. `docs/agents/long-term-memory.md`
9. `docs/agents/remote-collaboration.md`
10. `docs/handoffs/2026-08-27-production-embed-and-narrator-only.md`

随后运行 `git status --short --branch`，把起始状态记录到晨间报告。不得清理、重置或覆盖现有修改。

## 不可突破的安全边界

- 禁止 `git reset --hard`、`git clean`、强制 checkout、强推或批量删除。
- 不得把整个脏工作树直接提交；除非能证明提交只含本轮独立且已审查的补丁，否则不 commit、不 push、不建 PR。
- 不得写入用户正式 AA 工作区；所有 AA 测试使用新的 `.scratch/overnight-20260828-*` 隔离目录。
- 不得输出、复制或提交 Gemini API key、DPAPI 密钥文件、正式用户数据和授权素材。
- 不得安装系统级软件、插件、Spine、未知依赖或修改系统设置。
- 不得故意向真实 Gemini relay 制造 429/504、并发洪泛或长时间重试。
- 不得修改产品方向、ADR、公开协议版本或扩大到 1.1/1.2 功能。
- 不得把模拟结果、缺失费用 receipt、缺失缓存数据或外部工具缺失写成“已通过”。

## 8 小时工作队列

按顺序执行。前一项完成或明确阻塞后继续下一项，不等待用户。

### A. 基线与证据目录（约 20 分钟）

1. 建立新的 `.scratch/overnight-20260828-01/`，只保存日志、截图、隔离运行数据和报告。
2. 记录 Python、Node、pytest、Playwright/Chromium 可用性。
3. 检查上一份质量报告和隔离 AAP 是否仍可读取，但不要修改旧证据。
4. 运行 `git diff --check`；只记录现有 LF/CRLF 提示，不做机械换行重写。

### B. 全量测试盘点（约 1.5 小时）

依次运行并记录精确结果：

1. 根目录全量 `pytest -q`。若范围过大，按 root、writing、production、integrated 分组，但最终必须给出每组通过/失败/跳过数量。
2. 对所有本轮涉及的 JavaScript 入口运行 `node --check`，至少包括：
   - `services/halocue/writing/web/app.js`
   - `services/halocue/writing/web/writing-workbench.js`
   - `services/halocue/writing/web/production-embed.js`
   - `services/halocue/writing/web/shell.js`
   - `services/halocue/integrated/static/integration-shell.js`
   - `services/halocue/production/ui/app.js`
3. 单独运行 `services/halocue/writing/tests/test_provider_http_recovery.py`，确认受控 429/504 恢复仍通过。
4. 对任何失败先判断是代码回归、环境缺失、旧测试预期还是测试数据污染，不要直接改测试让它变绿。

### C. 浏览器与界面验收（约 1.5 小时）

1. 使用全新的隔离 writing/production/AA 目录启动集成服务。
2. 运行 `tools/quality_regression.py`，覆盖 4 个视口和全部加载、失败、缺失深链边界。
3. 运行可用的 writing browser acceptance phase 1、2、3、5；每个脚本使用独立数据目录。
4. 检查浏览器控制台错误、页面错误、超时、主线程卡死、不可见工作台和重复请求。
5. 对界面缺陷保存截图；对通过项保存 `report.json`，不要只写口头结论。

### D. 修复确定性失败（最多约 3 小时）

只修复在 B/C 中稳定复现、属于 HaloCue 1.0 且可通过自动测试证明的缺陷。

每个缺陷必须遵循：

1. 建立最小、可重复的失败信号。
2. 写或确认现有回归测试先失败。
3. 做最小补丁，保留当前工作树原有修改。
4. 重跑最小测试，再重跑受影响服务测试。
5. 检查并移除调试日志、临时脚本和无关格式变化。

优先级：

1. 数据完整性、发布冻结、幂等和重复安装。
2. 生产工作台无法打开、主线程卡死或严重可访问性问题。
3. 纯旁白/普通角色门禁错误。
4. 429/504、超时、取消和晚到结果污染状态。
5. 其他会阻断 1.0 闭环的确定性问题。

不要为了填满 8 小时进行推测性重构、视觉重设计、依赖升级或新功能扩展。

### E. 最终隔离闭环（约 1 小时）

在所有本地测试稳定后，执行一次新的干净闭环：

1. 新建隔离 writing、production 和 AA 目录。
2. 使用纯旁白两句短场景，不建立占位人物卡。
3. 完成 Brief、StoryBlueprint、场景候选、人工接受、场景审查、连续性审查、发布审查、冻结、生产交接、映射、逐卡批准、校验、编译和隔离安装。
4. 验证重复 handoff 幂等、重复 install 被阻止、正式 AA 目录没有被写入。
5. 计算最终 AAP 的大小和 SHA-256。

Provider 策略：

- 先用模拟/测试 Provider 完成全流程。
- 只有模拟流程全绿、现有 DPAPI 配置可安全读取且无需用户输入时，才允许额外执行一次真实 Gemini 闭环。
- 真实调用最多一条完整闭环；不得打印密钥，不得因失败无限重试。
- Provider 不提供费用或缓存 receipt 时记录“不可用”，不得估造。

### F. 剩余时间的安全利用

如果前述任务提前完成：

1. 将全量测试再运行一遍，检查偶发失败。
2. 将质量回归连续运行 3 次，确认生产工作台不存在竞态复发。
3. 审查本轮修改的差异，只清理本轮产生的死代码和调试内容。
4. 核对所有失败路径是否留下结构化错误而不是假成功。

仍不得启动新功能、正式 AA 写入、系统安装或真实服务压力测试。

## 遇阻处理

- 同一外部阻塞最多尝试三次，包括首次失败。
- 环境缺少 Playwright、Chromium、Spine、正式 AA 或费用 receipt 时，记录检测命令和结果，然后继续其他任务。
- 测试需要用户登录、弹窗确认、购买、授权或选择正式目录时，跳过并列为人工验收项。
- 发现当前修改与已有用户改动无法安全分离时，不覆盖、不提交；保留最小补丁并在报告中标出重叠文件和具体标记。
- 发现可能破坏数据、协议或产品方向的选择时，停止该分支工作，但继续执行其他安全测试和文档整理。

## 晨间交付物

任务结束前必须创建：

`docs/handoffs/2026-08-28-overnight-8h-result.md`

内容至少包括：

1. 实际运行时长和完成的阶段。
2. 起始与结束分支/工作树状态。
3. 修改文件以及每处修改的根因。
4. 所有测试命令、通过/失败/跳过数量和耗时。
5. 浏览器报告、截图、AAP 的仓库相对路径和 SHA-256。
6. 真实 Gemini 是否调用、调用次数、可用 token 统计；不得包含密钥。
7. 尚未解决的问题，区分代码缺陷、环境缺失和需要用户决定。
8. 是否创建提交；若没有，明确说明避免混入脏工作树的原因。
9. 下一位开发者可以直接执行的单一步骤。

同时把机器可读证据保存到：

`.scratch/overnight-20260828-01/final-report.json`

## 完成标准

满足以下任一条件即可结束夜间目标：

1. 全量测试、浏览器质量回归和新的隔离闭环全部通过，晨间报告完成；或
2. 所有可安全执行的工作完成，剩余项均明确依赖外部软件、正式数据、费用 receipt 或用户决策，且晨间报告完整记录证据。

不得仅因某一项困难而提前结束，也不得为了耗满时间扩大授权范围。
