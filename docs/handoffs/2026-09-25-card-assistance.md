# 定向资料助手 — 2026-09-25

- kind: handoff; scope: 1.0 / writing；status: implementation and isolated acceptance complete; live backend restart pending
- 用户明确批准继续深化资料助手；本轮不扩展剧情沙盘或跨章检查。
- 当前分支：`codex/1.0-release-readiness-20260914`；没有提供专属 Issue，沿用当前用户任务，不擅自发布 Issue/PR。
- 依据：`docs/product-direction-1.x.md`、`contexts/backend/CONTEXT.md`、`contexts/ba-editor/CONTEXT.md`、ADR-0006。
- 保留全部既有脏改动；不提交、推送或清理历史文件；不修改正式用户资料。

## 实施计划
1. 编辑器内折叠的定向调整：修改意图、允许修改字段、草稿带入讨论和返回。
2. 在既有对话/Proposal 契约内增加可选版本化 `card_assistance` 上下文：锁定当前作品内稳定卡片 ID、基准修订和字段白名单。
3. 候选复用字段级 Diff、影响预览、人工部分采纳。服务端保持身份、来源和确认状态；过期卡片不能被旧草稿覆盖。
4. 测试合成作品的完整讨论/候选/部分采纳/返回草稿，内部浏览器验收桌面与390px；真实参考库只读。

## 本轮落地
- 既有人物卡／世界观卡编辑器内增加折叠的“和助手定向调整”，填写意图、限定可改字段后进入现有创作讨论；不会自动调用模型或保存正式卡片。
- 同标签页保留未保存表单，支持返回后继续；再次带入时只能替换本次自动生成且未经手改的未发送说明，不覆盖其他对话草稿。
- `card-assistance/1.0` 随消息、固定运行输入快照和候选保存，后端检查作品归属、稳定 ID、基准修订和字段白名单；排队前、转向取消旧运行前及 worker 执行时重复检查。旧后端通过能力握手禁用新入口，避免静默忽略约束。
- 整理时绑定具体 assistant preview 与前置用户请求，不能由模型名称或后来的草稿换目标；即使模型返回“待命名”仍以选中正式卡片身份为准。
- 未保存表单作为可查看的非确认草稿传递；未选择的草稿字段不保存。模型提供的来源标为待核对线索；正式身份、来源、导入元数据、采用状态保持原值。
- 复用已有字段 Diff、影响摘要、显式部分采纳和修订历史。世界观无效关联在生成候选前拒绝；定向采纳不再把集合的原来源类型自动混为 custom。
- 新修订出现后返回显示已保存版本，旧草稿只供查看；空意图提示、过期提示、暗色/浅色和390px布局均已检查。
- 无主导航扩张、无第二个聊天界面、无新增外部依赖、无数据库迁移。旧记录缺少新字段时继续原流程。

## 变更边界
新增：
- `services/halocue/writing/src/halocue_writing/card_assistance.py`
- `services/halocue/writing/web/card-assistance.js`
- `services/halocue/writing/docs/card-assistance.md`
- `services/halocue/writing/docs/contracts/card-assistance-1.0.schema.json`
- `services/halocue/writing/tests/test_card_assistance.py`
- `services/halocue/writing/tests/in_app_browser_card_assistance_server.py`
- `services/halocue/integrated/tests/test_card_assistance_ui.py`

叠加修改（均保留本轮之前的已有改动）：
- `services/halocue/writing/src/halocue_writing/service.py`
- `services/halocue/writing/web/app.js`
- `services/halocue/writing/web/index.html`
- `services/halocue/writing/web/authoring-ui.css`（本轮开始前即为未跟踪文件）
- `services/halocue/writing/docs/contracts/conversation-knowledge-proposal-1.2.schema.json`：可选 versioned 子上下文，兼容旧候选。

## 回归证据
1. 最终定向功能、合成 HTTP/UI、契约和影响回归：
   ```text
   python -X utf8 -m pytest services/halocue/integrated/tests/test_card_assistance_ui.py services/halocue/writing/tests/test_card_assistance.py services/halocue/writing/tests/test_knowledge_proposal_normalization.py services/halocue/writing/tests/test_proposal_impact.py services/halocue/writing/tests/test_agent_async.py -q --tb=short
   ```
   **40 passed in49.24s**。覆盖1280/390px人物和世界观、部分采纳、未保存草稿返回、空输入、老后端禁用、来源保留、错误/过期/跨作品目标、未允许字段过滤、无效世界关联、固定消息恢复和旧契约；运行中转向保持同一卡片约束，过期转向不会取消原运行。
2. 相关对话、纵向业务和提交投影：
   ```text
   python -X utf8 -m pytest services/halocue/writing/tests/test_conversation_slice.py services/halocue/writing/tests/test_vertical_slice.py services/halocue/writing/tests/test_commit_projection.py -q --tb=short
   ```
   **156 passed in170.29s**。
3. 资料/反馈、工作台、响应式及变更审查回归：
   ```text
   python -X utf8 -m pytest services/halocue/integrated/tests/test_reference_feedback_ui.py services/halocue/integrated/tests/test_experience_surface_matrix.py services/halocue/writing/tests/test_reference_details_ui.py services/halocue/writing/tests/test_shared_chrome_and_library_defaults.py services/halocue/writing/tests/test_writing_responsive_shell.py services/halocue/writing/tests/test_change_review_ui.py -q --tb=short
   ```
   **58 passed in141.06s**。
4. `node --check`（app.js、card-assistance.js）；新增4个Python文件的 `ruff check`、`ruff format --check`；服务与助手模块 `compileall`；本轮跟踪文件 `git diff --check`：通过。

本轮没有运行整个仓库全量测试，也没有声称既有全套断言全部修复。前序基线的6项旧静态HTTP/UI字符串断言失败不属于本轮已修复范围。中途新增测试的选择器、label定位、预先已有projection job计数问题均修正后重新运行，不将失败尝试计为通过。

## 内部浏览器实际验收（不是仅 headless 测试）
- 使用 Codex 内部浏览器 web control，桌面1280x900与390x844。
- 隔离临时目录 + 合成 Provider，未调用付费或外部模型。人物“白露”与世界卡“档案室”均为合成数据。
- 桌面：修改未保存职责→填写意图→进入讨论（尚未发送、作品版本不变）→返回看到原草稿→更新说明再次进入→发送→指定草稿整理→取消其他3个字段仅采纳职责→新修订可见→返回不会用旧草稿覆盖；声音、知情边界、来源和采用状态保留。
- 390px：世界卡空意图校验→限定“本作定义与限制”→发送→只出现1项Diff→显式采纳→返回显示新定义、原来源和待决定状态。浅色/深色截图检查通过，DOM宽度390且scrollWidth390，浏览器error/warn日志为空。
- 最终后端另启隔离实例复核 capability 握手开启入口；旧服务能力缺失由集成UI测试与正式7179页面只读检查共同验证：定向按钮disabled，手动保存按钮仍enabled。
- 正式参考作品 `work-3c40d9c813ae` 只读检查：版本29、28项人物卡正式修订保持不变。未保存、归档、删除或测试修改真实人物资料。

## 当前预览与交接限制
- `7179` 的既有后台进程仍加载本轮之前的Python代码。已确认无运行中的Agent任务，并准备复用原启动脚本/数据目录重启，但进程重启命令被执行策略拒绝；没有换工具绕过，也没有终止原进程。
- 新前端显式检查 `card_assistance/1.0` 能力：旧后端上新入口不可用，并提示正常重启服务；手动编辑与普通讨论不受影响。不会在旧后端上假装有字段锁。
- 后续正常关闭并重新启动原本地 HaloCue 服务，即可加载当前后端并开放新入口；不需要迁移数据。真实模型的建议质量仍需实际模型环境另行验收，本轮只证明交互、数据边界和修订链路。
- 没有commit/push/PR或发布；保留其他会话全部未提交改动。实现可进入小范围人工代码审查，不代表全产品发布验收完成。

## 收尾
- 最终相关回归合计254项通过（40 +156 +58，非全仓库发布验收）。
- 额外修复运行中转向丢失 `card_assistance` 的上下文传递，新增真实异步服务回归；最终候选在内部浏览器复核仅含1项获准的职责修改。
- 正式参考库前后版本号和全部28项当前修订ID逐项对比一致。
- 内部浏览器临时390px视口已重置；隔离测试页关闭，两个自建合成服务进程已停止；未终止7179正式预览。
- JS语法、Python静态检查和本轮跟踪文件diff空白检查再次通过。未创建提交或PR。
