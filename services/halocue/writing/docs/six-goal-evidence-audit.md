# HaloCue 1.0 六项目标证据审计

更新时间：2026-08-20

## 2026-08-20 场景写作主操作接入 Agent Composer

- 复现确认：已有正文场景的中央主操作“生成下一份候选/生成本场候选”在最终事件链中只是静默 `return`，点击后既不生成候选，也不把用户带到唯一可提交场景 Agent 消息的 Composer，形成真实写作阻塞。
- `web/app.js` 新增捕获处理器：在当前 `stage=draft` 点击该主操作时，保留当前 Scene，切到本场 Agent 视图并将焦点放到 `#sceneConversationForm` 消息框；不自动发送模型请求、不创建 Proposal、不改正文，后续仍由用户发送指令并显式形成候选。
- `web/index.html` 资源版本更新为 `app.js?v=20260820-68`；新增 HTTP 静态合同 `test_scene_generate_command_enters_agent_composer_instead_of_being_silent`，定向 `tests/test_http_api.py` 为 `48 passed`；`node --check web/app.js` 通过。
- Browser 内置复验：正式 Scene 1 在 `1440x900` 可见候选等待决定；切换到 `390x844` 后候选 Diff 单列、Agent Composer 可见且可用，`scrollWidth=clientWidth=390`，Console warning/error `[]`。由于正式场景已有 pending Proposal，未点击采纳/退回，也未伪造“无候选场景点击生成”证据；该分支仍以静态合同和代码路径作为证据。
- 完整 09 最终：`479 passed in 258.71s (0:04:18)`。本切片未发送新 Agent 消息、未采纳 Proposal、未建立新 Revision、未冻结 ScriptRelease、未创建 ProductionRun 或安装 AA；未修改 `08-HaloCue-1.0/`、`10-HaloCue-1.0-Integrated/`。真实费用 receipt、cache、附件连续选择、同配置成功重试、远端故障、正式 ProductionRun 副本和 AA 持久安装仍为证据缺口。

## 2026-08-20 场景写作阻塞的直接恢复入口

- 复现确认：第二场直达正文后，缺少已确认人物卡时，主操作原先只是“查看缺少的输入”，用户还要再进入 Agent 面板寻找“补齐人物卡”。
- `web/writing-workbench.js` 现在在本场上下文已固定但 `readiness.needsCharacterCard` 时直接显示“补齐人物卡”，保留已有正文的“检查本场”入口；低风险导航仍不运行 Agent、不保存人物卡、不改变正文。
- `web/app.js` 复用稳定场景恢复锚点；当审查证据和场景合同没有角色列表时，仅从“爱丽丝在废弃车站……”这类标题提取单个名称作为可编辑预填提示，随后把名称保留在 `characterCardDraft`，避免草稿渲染覆盖预填。资料页使用双 `requestAnimationFrame` 恢复焦点；返回入口仍按 `chapter_id + scene_id` 回到原场。
- Browser 内置验收：`390x844` 点击“补齐人物卡”进入 `/references`，`显示名称` 值为“爱丽丝”、实际获得焦点，`scrollWidth=clientWidth=390`；点击“返回当前场继续”返回 `stage=draft&chapter_id=chapter-6d652b3fb16c&scene_id=scene-3fe0047175da`；Console warning/error `[]`，结束执行 `viewport.reset()`。
- 新增场景恢复/预填合同测试；定向自然语言回归 `37 passed`；完整 09 最终 `478 passed in 231.72s (0:03:51)`；`node --check web/app.js`、`node --check web/writing-workbench.js` 通过；资源版本 `app.js?v=20260820-67`、`writing-workbench.js/css?v=20260820-32/31`。
- 本切片未创建或确认人物卡、未发送 Agent 消息、未采纳 Proposal、未建立新 Revision、未冻结 ScriptRelease、未创建 ProductionRun 或安装 AA；未修改 `08-HaloCue-1.0/`、`10-HaloCue-1.0-Integrated/`。真实费用/cache/附件/远端故障/ProductionRun 副本和 AA 持久安装证据缺口保持不变。

## 2026-08-20 章节细纲场景写作入口可见性修正

- 复现确认：紧凑章节细纲页的场景标题虽然可点击，但手机端没有明确的写作动作，用户需要猜测整行是否会进入正文。
- `web/writing-workbench.js` 将场景行改为“场景信息 + 状态 + 明确动作”：未起草显示“去写本场”，已有正式正文显示“查看正文”；两者都复用既有 `data-scene-open`、稳定 Scene ID、`persistWritingTarget` 和 Proposal/Revision 边界，不直接写正文。
- `web/writing-workbench.css` 为桌面三列场景行和手机单列动作区增加稳定布局；资源版本更新为 `writing-workbench.js/css?v=20260820-31`。新增 `test_compact_chapter_scene_rows_expose_an_explicit_writing_action`，同步更新 HTTP 静态资源合同。
- Browser 内置验收：`1440x900` 场景行同时显示“查看正文”和“去写本场”；`390x844` 两个按钮完整可见，`scrollWidth=clientWidth=390`；点击“去写本场”进入 `stage=draft&chapter_id=chapter-6d652b3fb16c&scene_id=scene-3fe0047175da`，正文页显示固定上下文和缺少人物卡的明确阻塞；Console warning/error `[]`；结束执行 `viewport.reset()`。
- 定向合同 `2 passed`；完整 09 最终 `476 passed in 249.88s (0:04:09)`；`node --check web/writing-workbench.js` 通过。
- 本切片未发送 Agent 消息、未采纳 Proposal、未建立新 Revision、未冻结 ScriptRelease、未创建 ProductionRun 或安装 AA；未修改 `08-HaloCue-1.0/`、`10-HaloCue-1.0-Integrated/`。Provider 配置和真实费用/cache/ProductionRun 证据缺口保持不变。

## 2026-08-20 作品 Agent 手机 Composer 遮挡修正

- 继续复现发现：上一轮把移动 Works 画布改成单滚动区后，固定 Composer 在滚动顶部仍会覆盖长执行计划中的“较早的待处理决定”内容；仅预留底部空间不能消除中段遮挡。
- `web/writing-workbench.css?v=20260820-30` 将移动 Works Composer 改为文档流末尾的单一操作区（`position: static`），画布保留 `24px` 末尾间距；桌面 Composer 继续保持内容列文档流布局。`tests/test_http_api.py` 新增/更新内容流合同并同步资源版本断言。
- Browser 内置验收：`1440x900` 桌面 Composer 位于内容列，`390x844` 手机顶部历史决定卡未被遮挡；滚动到底部后 Composer `[622.50,741.79]`、底部导航 `[790,844]`，间距 `48.21px`；两档 `documentElement` 均无横向溢出，Console warning/error `[]`，结束执行 `viewport.reset()`。
- 定向自然语言/HTTP 回归 `81 passed in 21.43s`；完整 09 最终 `475 passed in 255.13s (0:04:15)`；`node --check web/app.js`、`node --check web/writing-workbench.js`、`python -m compileall -q src` 通过。
- 本切片未发送 Agent 消息、未采纳 Proposal、未建立新的 Revision、未冻结 ScriptRelease、未创建 ProductionRun 或安装 AA；未修改 `08-HaloCue-1.0/`、`10-HaloCue-1.0-Integrated/`。Provider 仍为真实 `gemini-3.7-flash (openai)`；真实费用 receipt、cache 命中/策略、附件原生文件选择、同配置成功重试、远端 `429/504`、正式 ProductionRun 素材副本和 AA 工作区持久安装仍是证据缺口。

## 2026-08-20 Intent 场景上下文与计划排序修复

- `web/app.js?v=20260820-61` 按最新计划显示 `CURRENT INTENT`；旧未解决的高风险/失败/阻塞计划进入“较早的待处理决定”区，保留确认入口和审计，不再覆盖当前写作目标；历史目标按钮显示“查看原目标”。
- Browser 正式页面在 `1920x1080`、`1440x900`、`1366x768`、`390x844` 复验：最新第二幕作为主卡，旧决定单独显示；`overflowX=0`，手机 Composer 与底部导航可见，Console warning/error `[]`。点击“去写这一幕”进入稳定 `scene-3fe0047175da` 后，发现旧候选正文实际来自第一幕星野/凯伊，形成真实产品缺口。
- `service.py` 修复静默替角：自然语言场景只按消息、场景标题、目标、地点和人物别名匹配已确认卡；匹配不到返回 `intent_character_context_missing`，不生成候选；自动选择写入 `source=intent_auto`，显式选择不被覆盖。重新匹配会将旧 pending Proposal 标为 `superseded` 并写入 Decision，不写入正式 Revision。
- Intent 场景执行结果回写同一 `intent_plans`，作品 Agent 回复成功但场景 Agent 阻塞时，计划显示“需要补齐写作输入”及恢复原因。新增人物边界、匹配、阻塞投影和 UI 合同测试。
- 最终验证：09 全量 `468 passed in 334.85s (0:05:34)`；10 集成全量 `8 passed`。`py_compile`、两份写作 JS `node --check` 通过。正式 `8910` HTTP `200`，Provider `gemini-3.7-flash (openai)`、`can_call_model=true`、`is_simulation=false`，Dispatcher running、`last_error=null`，唯一监听端口 `8910`。
- 本轮未采纳错误 Proposal、未建立新正文 Revision、未冻结 ScriptRelease、未创建 ProductionRun 或安装 AA；未修改 `08-HaloCue-1.0/` 或 `10-HaloCue-1.0-Integrated/` 源码。真实费用 receipt、cache 命中/策略、附件原生文件选择、同 Provider 成功重试、远端 `429/504`、正式 ProductionRun 素材副本和 AA 持久安装仍是证据缺口；旧 Intent 数据仍有修复前“完成”投影，不能作为新回写逻辑验收证据。

本表只记录 `09-HaloCue-1.0-Writing` 当前可复核证据。`08-HaloCue-1.0` 与
`10-HaloCue-1.0-Integrated` 只作为外部边界，不在本表中修改或代替验收。

| 目标 | 当前证据 | 结论 | 真实缺口 | 下一步 |
| --- | --- | --- | --- | --- |
| 首次使用闭环 | `test_real_vertical_slice_persists_and_reloads` 覆盖正文 Proposal、用户采纳、审查、冻结和重启恢复；隔离 8913 Browser 已连续验证一句想法、取消/焦点恢复、建立作品、创作主对话和手机/桌面主操作 | 主链已验证 | 仍需在正式用户数据上保持非破坏性验证；真实写作质量不由 Fake 夹具证明 | 保留隔离夹具证据，继续观察真实 Provider 下的首轮体验 |
| 素材库接入场景写作 | 场景可选背景、角色、音效、CG；引用进入 Context/WritingPack/ScriptRelease，并保留原件 ID、版本、Hash、快照；Agent 可给出本地规则建议；09 已增加到配置制作服务的只读素材代理；离线时显示明确不可用状态；新增版本化 `production-asset-handoff/1.0`、`production-asset-usage/1.0` 合同、能力探测、发布前阻塞和回执 reconciliation；10 集成层已复用 08 冻结资源快照并完成匹配回执纵切；正式场景页已显示带回执副本 | 正式带素材交接已验证 | 08 原始服务未修改；正式用户 AA 工作区持久安装仍未执行，真实费用/缓存不属于素材闭环 | 保留副本回执与 Hash 追溯；仅在用户明确授权时执行正式 AA 工作区安装 |
| 真实 Provider 小规模纵切 | `gemini-3.7-flash (openai)` 已固定为真实 Provider；真实场景候选、usage、Diff、审查 Gate 与 ScriptRelease 均有运行记录和 Browser 证据 | 小规模纵切已完成 | 真实费用未知、cache unknown；没有把配置中的 0 解释成免费，也未取得 ProductionRun 证据 | 费用/缓存保持未知披露；不重复扩大真实调用，等待制作端前置 |
| Agent 运行恢复 | 持久队列、租约、CAS、迟到结果丢弃、失败重试、只重跑失败项、摘要与快照损坏失败闭合均有专项测试；独立 Browser 夹具已验证超时、限流、预算和完整性四类公开恢复动作 | 四类恢复矩阵已验证 | 真实 Provider 的实际网络错误仍未验收，受无凭据前置阻塞 | 保持 Fake 边界；取得真实 Provider 前置后只验证一条真实小任务 |
| Revision、影响预览和审查 | Proposal impact、冲突复查、Revision compare、投影重建、资料变更使 Gate 失效、ScriptRelease 完整性与不可变交接均有专项测试；素材变化后两个 Gate 同时过期时 Harness 现在按 `continuity.review -> release.review` 顺序恢复 | 主链大部完成 | 关系图/时间线的完整消费面、素材变化后的全部审查展示仍需端到端证据 | 在统一首次使用纵切中补发布前依赖与素材来源可见性验收 |
| 后续协作与规模化 | 当前没有第二套状态机或第二入口 | 尚未开始，符合顺序约束 | 多人协作、评论、任务分派、批量素材管理均未实施 | 前五项主链稳定前不启动 |

## 当前优先级

1. 保持首次使用、场景素材追溯和制作交接证据与正式入口一致。
2. 在独立测试夹具中继续补四类失败卡与恢复动作的 Browser acceptance。
3. 真实 Provider 已可调用；只在可审计的小规模任务中继续验证，不把 usage 扩大解释为费用或缓存。
4. 继续补 Revision 影响预览、发布 Gate 失效后的端到端消费面；正式 AA 工作区安装需单独授权。

此审计表不是完成声明。每次只在获得新代码、测试或 Browser 证据后更新结论。

## 当前状态覆写（2026-08-19 本轮最终）

- 首次使用连续 Browser 证据已补齐：内嵌 `firstWorkForm` 的取消、焦点恢复和建立作品均在隔离 8913 真实完成；不再沿用上方早期原生弹层点击缺口作为当前结论。
- 真实 Provider 小规模纵切已具备真实响应证据：统一 8910 当前配置为 `gemini-3.7-flash (openai)`，既有真实场景运行、usage 和 ScriptRelease 证据见后文；本轮不重复调用模型。真实费用未知、cache unknown，仍不得写成免费或缓存已完成。
- 目标 5 的正文 Diff、影响预览、Gate、ScriptRelease 和资料投影已有 Fake/真实纵切证据；目标 2 的 10 集成能力和隔离 ProductionRun usage receipt 已验证，正式用户作品带素材交接仍待验收；目标 4 的真实 Provider 网络故障恢复仍未验收。
- 下一优先级：在正式用户作品上做一次带素材的非破坏性交接与回执验收；同时在不扩大范围的前提下补真实 Provider 超时/限流证据。多人协作和规模化继续保持未启动。

## 2026-08-18 增量证据

- 作品 Agent 引导已改为悬浮展开，不再推动聊天区；“作品进度”明确表示正式产物保存/发布依赖，不限制对话顺序。
- Harness 新增只读 `decision_basis`，展开层可查看当前下一步依据；仍无真实 Provider 判断证据。
- 最终 09 回归：`406 passed in 216.16s (0:03:36)`。内置 Browser 已复核桌面与手机视口，未改变五项目标的外部阻塞结论。

## 2026-08-18 增量证据（表单兼容与视口复核）

- 新建作品表单不再依赖 `SubmitEvent.submitter` 或 `method="dialog"` 的原生激活行为；建立按钮改为普通按钮，点击和键盘提交共同复用 `submitWorkDialog`。这只修正入口事件兼容性，不改变 Proposal、Revision 或正式资料写入边界。
- `node --check web/app.js` 通过；定向 HTTP/UI 合同测试 `2 passed`；完整 `09-HaloCue-1.0-Writing` 回归最终为 `406 passed in 269.07s (0:04:29)`。
- Codex 内置 Browser/Web Control 复核当前用户作品：`1920x1080`、`1440x900`、`1366x768`、`390x844` 均为 `overflowX=0`，Composer 与主操作可见，手机导航只在 `390x844` 显示；焦点可落到 Composer；正确点击 `details.work-guide-details > summary` 展开说明后聊天区坐标不变；Console warning/error 均为 `[]`。验证结束后调用 `viewport.reset()`。
- 本轮没有取得“一句想法 -> 浏览器点击建立作品 -> Proposal -> 用户决定”的完整内置 Browser 连续证据。临时夹具已清理；内置 Browser 的只读评估环境不暴露 `fetch`、`FormData` 或 `XMLHttpRequest`，不能把它当成普通页面脚本运行时来伪造验收结果。首次使用闭环仍标记为部分完成。

## 2026-08-18 增量证据（失败重试状态刷新与单一恢复入口）

- 修复作品 Agent 失败重试后的前端状态滞留：重试接口返回新 `work` 后，前端现在重新读取当前线程的 `agent-presentation`，不再继续显示已经被后续重试接续的旧 `recovery.available`。任务中心重试路径同步刷新该投影。
- 收敛失败态重复操作：失败消息卡在已有 Recovery 投影时不再重复渲染“重试本轮”；作品进度引导和左侧下一步栏改为“查看恢复卡”定位动作，实际重试按钮只保留在 Recovery 卡中。无投影时消息卡仍保留兜底重试入口。
- 定向验证：`node --check web/app.js` 通过；HTTP/UI、Presentation、Harness 定向测试 `17 passed in 8.27s`。
- 完整 09 回归最终为：`408 passed in 237.46s (0:03:57)`。
- 使用 Codex 内置 Browser/Web Control 的独立失败卡夹具真实验证：初始失败态 `1` 个 Recovery 卡、`1` 个“重试本轮”按钮；点击后 Recovery 卡、顶部旧恢复提示和“从固定输入重试”均消失，失败历史保留“这次失败已由后续重试接续”；Console 日志为 `[]`。
- 内置 Browser 视口矩阵 `1920x1080`、`1440x900`、`1366x768`、`390x844` 均为 `overflowX=0`，Composer 和移动导航可见；验证结束已调用 `viewport.reset()`。临时夹具服务端口 `6143`、`6144` 已停止，正式服务 `8910` 未触碰。
- 这次仍未改变真实 Provider 前置、素材 ProductionRun 副本或 08/10 集成边界；Provider 仍为 `fake / local-rules`、`can_call_model=false`。
- 另行尝试用独立首次使用夹具完成“开始一个新故事 -> 建立作品”浏览器点击时，内置 Browser 的页面评估对象不提供原生 `click()`/`fetch()`，节点点击未触发该对话框的委托事件；没有把这次失败伪造成成功证据，也没有修改正式用户作品。首次使用连续 Browser 证据继续保持缺口。

## 2026-08-18 增量证据（跨作品路由状态与四类恢复矩阵）

- 修复 `writing-workbench.js` 在 URL 切换作品时直接替换 `state.work`、却不刷新 `agentPresentation`/投影的状态串用问题；现在复用统一 `loadWorkBeforeRouter(workId, { resume: false })` 链路，当前作品不会显示上一个作品的 Recovery 卡或运行 ID。
- 静态资源版本更新为 `app.js?v=20260818-26`、`writing-workbench.js?v=20260818-18`，避免浏览器继续缓存旧状态投影代码。
- 独立四作品失败夹具真实验证：`provider_timeout` 显示“模型服务超时”并只提供“重试本轮”；`provider_rate_limited` 显示“模型服务触发限流”并只提供“重试本轮”；`agent_turn_budget_exceeded` 只提供“打开模型设置”；`agent_snapshot_integrity_failed` 只提供“重新加载工作台”。切换作品后每张卡的运行 ID 与当前作品一致。
- Browser 真实重试验证：超时和限流点击唯一“重试本轮”后 Recovery 卡和旧恢复提示消失，失败历史保留“这次失败已由后续重试接续”；控制台 `[]`。
- `1440x900`、`390x844` 矩阵中四类页面均 `overflowX=0`，Composer 与移动导航可见；验证结束调用 `viewport.reset()`。临时夹具端口 `6147` 已停止，正式服务 `8910` 未触碰。
- 定向回归 `58 passed in 12.45s`；完整 09 回归最终为 `409 passed in 225.86s (0:03:45)`。首次使用连续 Browser 证据、真实 Provider、真实素材服务/ProductionRun 副本和 10 集成仍未完成。

## 2026-08-18 增量证据（新建作品短视口可用性）

- 修复 `#workDialog` 在低高度桌面中底部主操作落出视口的问题：对话框和表单现在受 `100dvh` 高度约束，表单内部滚动，底部 `.dialog-actions` 保持 sticky；静态资源更新为 `shell.css?v=20260818-16`。
- 内置 Browser 只读验证正式服务：`1280x720` 下“建立作品”按钮底部 `673.7px`，`390x844` 下底部 `761.25px`，均在视口内；两种尺寸 `overflowX=0`。原生 `<dialog>` 内按钮仍无法由当前 Browser 控制面激活，因此没有伪造“一句想法 -> 建立作品”点击证据。
- 定向回归 `33 passed in 12.88s`；本轮最终完整 09 回归为 `410 passed in 215.77s (0:03:35)`。

## 2026-08-18 增量证据（首次使用续接与运行诊断）

- 使用隔离的 Codex 内置 Browser 夹具（临时数据目录、Fake Provider）续接统一入口后的真实交互：浏览器在同一作品中发送补充要求、点击“形成全作方案”、查看方向 Proposal、点击“采纳为正式方向”，随后刷新页面；方向已写入正式版本、对话与当前阶段均恢复，Console warning/error 为 `[]`。
- 续接交互的 Browser 视口矩阵为 `1920x1080`、`1440x900`、`1366x768`、`390x844`：四种尺寸 `overflowX=0`，Composer 可见且可获得焦点；前三种显示桌面导航，手机显示底部导航。验证结束执行 `viewport.reset()`，临时夹具标签页与服务已关闭。
- 这条证据从“建立作品”之后开始；“开始一个新故事 -> 原生对话框内填写并建立作品”仍未形成内置 Browser 连续证据。当前 Browser 控制面对原生 `<dialog>` 内的取消、建立和 Escape/Enter 动作均未触发页面事件；该限制已复现且 Console 为空，未把它伪造成产品通过。
- 统一入口 `http://127.0.0.1:8910/` 诊断：写作服务 `online`；Provider `fake / local-rules`、`can_call_model=false`，真实 Provider readiness 为 `blocked`（缺少凭据）；制作服务 `http://127.0.0.1:8892` 为 `offline`。素材代理返回稳定 `503 production_unavailable`，没有虚构素材条目或 ProductionRun 副本。
- `python -m pytest` 最终汇总：`410 passed in 265.31s (0:04:25)`。本轮未修改 `08-HaloCue-1.0/`、`10-HaloCue-1.0-Integrated/`，未修改正文、人物卡、世界规则、WorkCanon、Revision 或 ScriptRelease。
- 新增离线交接回归 `test_handoff_keeps_release_unassigned_when_production_is_unavailable`：制作端口拒绝连接时返回 `production_unavailable`，ScriptRelease 仍可读取且 `production_run_id` 保持 `null`；`tests/test_release_integrity.py` 定向结果 `14 passed in 17.72s`。
- 新增测试后的最终完整 09 回归为 `411 passed in 286.66s (0:04:46)`；无失败、无遗留测试进程。

## 2026-08-18 增量证据（真实素材冻结快照与交接边界）

- 使用隔离临时数据目录启动既有 08 制作服务与 09 写作服务，未修改 08/10 代码或正式数据。09 通过制作素材代理读取真实 `aa_resources.json` 条目 `BG_ClassRoom`，保留 `source_type=resource_index`、`source_version=aa-resource-index/2026-08-18`、`content_hash=1738686580`、`content_hash_kind=aa_resource_hash` 及来源快照。
- 场景引用进入写作发布版本 `release-c2d44af0121d`，随后真实交接建立 ProductionRun `run-6c18f0e47364` 和制作侧发布版本 `release-3b46dff89bd1`；制作侧 `source_summary.upstream_release` 的发布 ID 与内容 Hash 和写作侧完全一致，证明不可变 ScriptRelease 身份已跨服务交接。
- ProductionRun 资源接口返回 `BG_ClassRoom` 为 `source=task_snapshot` 且目录 `frozen=true`，证明创建任务时冻结了可用资源快照。与此同时 `/resource-usage` 返回空对象，写作侧场景引用的 `production_copy` 仍为 `null`；现有 08 响应没有资产级任务副本回执，因此只能证明“任务冻结资源视图”，不能证明“该场景引用已被制作任务消费为副本”。
- 首次交接请求因人工复制作品 ID 时漏掉末尾 `a` 返回 404；读取 `/api/v1/works` 找回正确 ID 后，以同一真实发布版本重试成功。该失败是调用参数错误，不是产品交接失败。
- 定向回归 `python -m pytest tests/test_release_integrity.py tests/test_scene_asset_references.py -q` 最终为 `20 passed in 22.10s`。正式 8910 仍使用 `fake / local-rules`、`can_call_model=false`；没有真实模型、token、缓存或费用证据。

## 2026-08-19 增量证据（素材 Gate 恢复顺序与正式服务复验）

- 复现并修复一个真实工作流问题：正文与素材审查均已通过后修改场景素材，冻结会正确返回 `release_review_not_current`，但 Harness 原先把“重新运行全篇审查”排在连续性审查前。现在无开放阻塞项时统一推荐 `continuity.review`，连续性通过后再推荐 `release.review`；有开放阻塞项仍优先回到全篇审查处理阻塞。
- 新增回归覆盖：素材变化后冻结被拒；Harness 主操作指向连续性审查；按连续性审查、全篇审查顺序重跑后可以重新冻结，ScriptRelease 仍保存新的素材引用快照。`tests/test_scene_asset_references.py`、`tests/test_writing_harness.py` 及相关 HTTP 合同定向结果 `63 passed in 25.64s`；完整 09 最终结果 `412 passed in 309.35s (0:05:09)`。
- 前端作品进度主操作补齐 `continuity.review` 到“检查并发布”路由映射，静态资源更新为 `app.js?v=20260818-27`；`node --check web/app.js`、`node --check web/writing-workbench.js`、Python 编译检查通过。发布页已有连续性 Gate 保护，连续性未通过时全篇审查与冻结按钮保持禁用。
- 正式服务重启后保持 `http://127.0.0.1:8910/` 在线；`/health` 明确返回 `fake / local-rules`、`can_call_model=false`，制作服务未启动。Codex 内置 Browser 只读复核 `1920x1080`、`1440x900`、`1366x768`、`390x844`：全部 `overflowX=0`，前三种显示桌面导航、手机显示底部导航，Composer 可见并可获得焦点，Console warning/error 均为 `[]`；验证后已 `viewport.reset()`。
- 本轮只修改 09 的 Harness、前端映射、静态版本、测试及本审计文件/根上下文；未修改 08 或 10，未向正式作品点击采纳、冻结、交接或写入正文/资料。

## 2026-08-19 HaloCue 1.0：新建作品显式提交路径复核

- 修复 `web/app.js` 主委托点击处理器未优先处理普通 `type="button" data-submit="work"` 的缺口；现在该路径显式调用 `submitWorkDialog(document.getElementById('workForm'))`，继续遵守作品建立后先进入创意简报与 Proposal 决策边界，不依赖 `SubmitEvent.submitter` 或 `method="dialog"`。
- 新增 HTTP/UI 静态合同断言，确认 `data-submit="work"` 分支位于 `data-action="new-work"` 之前；`node --check web/app.js` 通过，定向 `test_work_dialog_cancel_is_not_blocked_by_required_fields` 为 `1 passed`。
- 完整 09 回归最终为 `412 passed in 307.81s (0:05:07)`，无遗留测试进程。
- 以隔离数据目录和临时服务 `8913` 复现：新建作品页、原生 `#workDialog`、想法填充均可读且字段可填；内置 Browser 的语义点击/键盘动作对 dialog 内“取消”和“建立作品”均未触发页面事件，数据库仍无作品。该限制已在重启服务后重复确认，Console 读数为空，不能据此宣称首次使用连续 Browser 主链通过。
- 临时服务和数据目录已停止并清理；正式 `http://127.0.0.1:8910/` 保持在线。首次使用连续 Browser 证据仍为明确缺口；建立作品之后的 Proposal/采纳续接证据仍有效。Provider 仍为 `fake / local-rules`、`can_call_model=false`，真实 Provider、token、缓存、费用、资产级 ProductionRun 副本仍无证据。
- 静态资源版本提升为 `app.js?v=20260819-28` 后重新执行完整回归，最终汇总仍为 `412 passed in 279.96s (0:04:39)`；该结果作为本轮最终 09 基线。

## 2026-08-19 HaloCue 1.0：资产级 ProductionRun 回执边界

- 新增 `docs/contracts/production-asset-handoff-1.0.schema.json` 与 `production-asset-usage-1.0.schema.json`。ScriptRelease 继续不可变；资产 handoff 只携带冻结的场景引用，`production_copy` 不会被预先填充。
- 09 新增只读 `production_asset_capabilities()` 探测与 `GET /api/v1/releases/{release_id}/production-assets` 状态端点。含真实素材引用的发布版本在制作服务离线时返回稳定 `production_asset_handoff_unavailable`，在线但未声明 `scene_asset_handoff` 时返回 `production_asset_handoff_unsupported`，不会先 POST 普通交接。
- 支持能力的制作服务即使 usage receipt 为空也只返回 `pending`；只有 `production-asset-usage/1.0` 回执同时匹配 `scene_id/reference_id/source_asset_id/source_version/content_hash/production_run_id`，并提供任务副本 `copy_id/content_hash`，09 才更新 `scene_asset_references.production_copy_json`。未知、重复或篡改回执 409，事务中不产生部分写入。
- 定向 `tests/test_release_integrity.py tests/test_scene_asset_references.py tests/test_vertical_slice.py -q` 最终 `108 passed`（其中纵切含 unsupported、pending、matching receipt、mismatch 和 HTTP 状态端点）。合同 JSON 静态解析通过。
- 计数边界修正后完整 09 回归最终为 `416 passed in 288.62s (0:04:48)`，无失败。
- 正式 `8910` 仍在线，但 `/api/v1/capabilities` 只显示写作能力；制作服务 `8892` 未启动，故本轮没有真实资产副本证据。Provider 仍为 `fake / local-rules`、`can_call_model=false`；未修改 `08-HaloCue-1.0/` 或 `10-HaloCue-1.0-Integrated/`。

## 2026-08-19 增量证据（真实章节改写与字符级 Diff）

- 在正式 `8910` 数据上以当前已配置的 `gemini-3.7-flash (openai)` 运行一次真实场景改写：`agent-66ad9edb9b02` -> `proposal-66e08c3655e4`，Provider 返回 `11,292 input / 202 output` token，`is_simulation=false`。候选只进入 Proposal，正文仍保持 `revision-293c472616cb`。
- 后端 `scene_script` Proposal 的块级变化现在同时带有只读 `inline_diff` 字符级证据；每个变化按“当前/候选”两行展示，删除与新增分别保留颜色和语义，不参与采纳计算。新增回归 `test_scene_proposal_exposes_character_level_diff_evidence`。
- 浏览器复验使用 Codex 内置 Browser/Web Control：`1440x900` 桌面显示真实 Provider、运行 ID、token 和 3 个逐项 Diff；字符级 Diff 在每个变化下可展开查看。`390x844` 手机单列显示字符级 Diff，滚动后“应用 3 项修改”与“退回候选”均可见；两种视口 `scrollWidth == 390/1440`，横向溢出为 0，手机底部导航可见，Console warning/error 为 `[]`。
- 真实候选已通过 UI 退回；页面恢复 `MANUSCRIPT / 修订 1`，正式正文 9 个结构化块未改变。服务重启后健康接口仍为 `200`，Provider 为 `gemini-3.7-flash (openai)`，`config_revision=model-config-4`。
- 受影响定向回归 `142 passed`，完整 Proposal 读取路径新增定向回归 `1 passed`；当前文件状态的最终完整 09 回归 `418 passed in 231.92s (0:03:51)`。未修改 `08-HaloCue-1.0/` 或 `10-HaloCue-1.0-Integrated/`。10 继续只作为统一网关/挂载入口，未复制第二套写作状态机。
- 真实费用仍未知，cache support 仍为 `unknown`；没有 ProductionRun 资产级副本回执；本轮没有把真实改写候选宣称为正式 Revision，也没有扩大真实调用范围。只读运行 `10-HaloCue-1.0-Integrated` 完整回归为 `3 passed in 33.44s`，证明 10 的网关仍从 09 工作区挂载当前前端/后端，没有第二套入口。

## 2026-08-19 增量证据（首次使用唯一主操作与弹层焦点）

- 空作品状态只保留中央“开始一个新故事”作为可见主操作；顶部“新建作品”在没有作品时隐藏，建立作品后再作为全局入口显示。新建弹层改为页面级 `role="dialog"` 容器，背景设置 `inert`，打开后焦点进入“一句想法”，`Escape` 关闭后焦点返回原入口；提交复用单一 `submitWorkDialog` 并带重复提交锁，没有绕过 Proposal -> 用户决定 -> Revision 边界。
- Codex 内置 Browser 隔离夹具验证 `1920x1080`、`1440x900`、`1366x768`、`390x844`：每个视口空状态只有一个可见新建主操作、`overflowX=0`，桌面/移动导航断点正确，弹层输入自动聚焦、提交按钮在视口内，`Escape` 后焦点返回入口，Console 日志为 `[]`。额外 `390x600` 短视口中弹层底部为 `586px`、提交按钮底部为 `566.69px`，仍在视口内；验证结束已执行 `viewport.reset()`。
- 真实连续点击证据仍有明确缺口：Browser 可以点击页面上的新建入口，也能填充弹层字段并触发 `Escape`，但弹层内语义点击、坐标点击和 Enter 都没有触发按钮/提交事件。移除 `inert`、移除 dialog ARIA 语义、改用原生 `<dialog>` 均复现；提交入口诊断探针未触发，而终端向同一 `/api/v1/works` POST 成功。该结果判定为当前 Browser 控制面限制，不能据此宣称“一句想法 -> 建立作品”浏览器纵切完成。
- 定向验证：`node --check web/app.js`、`node --check web/writing-workbench.js` 通过；`tests/test_http_api.py tests/test_vertical_slice.py` 为 `125 passed in 108.79s`。完整 09 回归最终为 `416 passed in 305.90s (0:05:05)`。
- 本轮未修改 `08-HaloCue-1.0/` 或 `10-HaloCue-1.0-Integrated/`，未写入正式作品正文、人物卡、世界规则、WorkCanon、Revision 或 ScriptRelease。Provider 仍为 `fake / local-rules`、`can_call_model=false`；真实模型、token、缓存、费用和资产级 ProductionRun 副本证据仍不存在。
- 下一优先缺口：在不依赖真实 Provider 或在线制作服务的范围内，补齐 Revision 影响预览、发布 Gate 与 ScriptRelease 冻结前复核的可见端到端证据；首次使用弹层点击继续作为 Browser 控制面证据缺口保留，不再为工具限制扩大 UI 架构修改。

## 2026-08-19 增量证据（影响预览到正式修订的 Browser 纵切）

- 在独立 Fake Provider 夹具中预置一份待决定的人物卡 Proposal。Browser 读取到 Proposal 的影响预览、`未发现冲突` 状态、三个消费者（后续场景上下文、人物一致性检查、发布前全篇审查）、固定影响摘要和“应用/退回”决策入口；桌面截图和 `390x844` 截图均显示 Composer、移动底部导航和单一主要采纳动作，横向溢出为 `0`。
- Browser 点击“应用 3 项修改”后，作品版本由 `2` 变为 `3`，人物卡由讨论草稿变为已写入正式资料，Proposal 不再处于待决定状态，运行摘要事件数增加；API 未被绕过，仍由用户明确采纳后建立新 Revision。移动端提交按钮和回退按钮垂直排列，均在可滚动内容中可见。
- 视口为 `1280x720` 和 `390x844`，Console 日志均为 `[]`；验证结束已调用 `viewport.reset()` 并关闭临时夹具标签页/服务。该证据覆盖资料 Proposal 的影响预览与修订落地，不等同于真实 Provider 或真实制作副本证据。

## 2026-08-19 增量证据（发布 Gate、ScriptRelease 与离线交接 Browser 纵切）

- 在独立 Fake Provider 夹具中建立一章一场正文，依次完成场景审查、记忆维护明确跳过、连续性审查和发布审查。Browser 打开“检查并发布”后实际显示当前正文覆盖、`0 阻塞 / 0 建议 / 0 提示`、已检查场景数和审查步骤；两个审查 Gate 快照均为通过状态，冻结按钮可用。
- Browser 点击“冻结新的发布版本”后作品版本由 `11` 变为 `12`，发布页显示 `release-...`、`sha256:...`、`script-release/1.0`、场正文/正式资料/审查快照数量和不可变来源说明；冻结按钮变为禁用的“当前正文已冻结”，交接入口单独出现。
- 制作服务保持离线时点击“交给 AA 制作”返回明确错误“AA 制作后端当前不可用，发布版本仍安全保留。报告此错误”，发布卡继续显示“尚未交给 AA 制作后端”，按钮保持可重试，没有生成或伪造 ProductionRun。`390x844` 发布页截图中发布卡、Hash、完整性信息和交接入口均可见，`overflowX=0`；Console 为 `[]`，验证结束执行 `viewport.reset()` 并关闭夹具。
- 当前仍可独立推进的下一项是关系图/时间线等资料消费面的 Browser 可见性与证据；真实 Provider 凭据和制作端 `scene_asset_handoff` 能力仍是外部阻塞，继续保持明确 blocked/offline 状态，不用 Fake 或冻结快照冒充真实验收。

## 2026-08-19 增量证据（关系图、时间线与来源投影 Browser 纵切）

- 独立夹具预置 3 张已确认人物卡、1 张世界观卡、1 条世界规则、1 个时间线事件和 1 条 WorkCanon 事实。Browser 打开资料页后，关系图显示“投影来自当前正式修订 · 已通过来源 Hash 校验”，包含 `7` 个节点、`5` 条明确关系；连线包括人物关系、人物参与世界卡/规则/事件，未从旧修订猜测关系。
- 点击“凯伊”节点后显示聚焦状态和 `4` 条已保存关系；点击“打开来源编辑”进入对应人物卡表单，证明图谱节点可以回到正式来源编辑，而不是只读装饰层。时间线页显示 `1` 个当前事件、来源“当前世界观修订”、已确认状态和关联角色“凯伊、星野”。
- 桌面 `1280x720` 与移动 `390x844` 均为 `overflowX=0`；移动端关系图包含 `7` 个节点、`5` 条关系，时间线编辑入口可见，手机底部导航显示；Console 日志为 `[]`，验证结束已执行 `viewport.reset()` 并关闭夹具。
- 该证据补齐了目标 5 的资料消费面可见性，但不改变真实 Provider、制作端能力和资产级 ProductionRun 副本的外部阻塞结论。

## 2026-08-19 增量证据（场景素材引用追溯 UI）

- 隔离 Browser 夹具通过正式 HTTP 合同建立一场带素材引用的场景：页面显示全局原件 ID `BG_Greenhouse`、原件版本 `aa-resource-index/2026-08-18`、完整 `sha256:` Hash 与 Hash 类型，并明确显示“尚未收到 ProductionRun 副本回执”；未把 `production_copy=null` 冒充为已消费副本。
- Codex 内置 Browser 检查 `1366x768` 桌面与 `390x844` 手机视口。素材卡和展开详情均可读，素材选择器在两种视口显示“素材库服务未连接”、制作服务边界说明、重试按钮和“场景引用尚未改变”；点击重试后仍保持该阻塞状态，作品版本与引用文本不变。桌面和手机 `overflowX=0`，手机选择器边界在视口内，Console warning/error 均为 `[]`；验证结束执行 `viewport.reset()`。
- DOM 盒模型复核确认桌面面板首列与引用列分离（无实际文本重叠）；本轮不做无依据的 CSS 改动。素材追溯字段的前端实现位于 `web/writing-workbench.js`，响应式规则位于 `web/writing-workbench.css`；静态资源版本提升为 `writing-workbench.js?v=20260819-20`、`writing-workbench.css?v=20260819-18`。
- `node --check web/app.js`、`node --check web/writing-workbench.js` 通过；素材目录、场景引用和 HTTP 静态合同定向测试 `56 passed in 23.41s`；完整 09 最终回归 `416 passed in 240.53s (0:04:00)`。
- 正式 `http://127.0.0.1:8910/` 健康检查仍为 `200`，Provider 为 `fake / local-rules`、`can_call_model=false`，usage/cache/reasoning 均标记 unsupported；制作服务 `127.0.0.1:8892` 仍离线。没有真实 Provider token、真实模型响应、真实费用/缓存或资产级 ProductionRun 副本证据；首次使用弹层内部提交按钮的 Browser 控制面证据仍缺失。未修改 `08-HaloCue-1.0/` 或 `10-HaloCue-1.0-Integrated/`。

## 2026-08-19 增量证据（真实 Provider 场景写作与候选 Diff）

- 真实 Provider 已按 OpenAI-compatible 协议接入 `gemini-3.7-flash`，`can_call_model=true`、`is_simulation=false`、配置版本 `model-config-3`、受控 `max_tokens=16384`。Google 官方模型页核对输入上限 `1,048,576`、输出上限 `65,536`；当前不把代理未知价格或 0 配置写成免费，真实费用仍为 `null`，缓存能力仍为 `unknown`，usage 由 Provider 响应支持。
- 一次性测试作品 `work-583189373ff2` 完成真实主链：方向 Proposal `proposal-a516b19873d6`、结构 Proposal `proposal-7d85f5e275f3` 经明确采纳；显式绑定已确认人物卡 `char-kai-real`/`char-hoshino-real` 后上下文 readiness 为 `can_run=true`。真实 `scene.draft.generate` 运行 `agent-03332d00258f` 产生 `proposal-537ff0a5eed0`，Provider 用量为 `10,993` 输入 / `243` 输出 token，缓存读写均为 `0`，候选正文保持 Proposal-only，未自动改写正文。
- 写作页候选审阅实际显示“真实 Provider · gemini-3.7-flash (openai)”、运行 ID、token 用量，并按 `block_changes` 逐项展示“当前正文 / 候选正文”、复选框、选择计数和应用/退回操作。Browser 在 `1920x1080`、`1440x900`、`1366x768` 与 `390x844` 检查横向溢出均为 `0`；Composer、场景工作区、移动导航和 Diff 主操作可见。Console 控制面没有可用的日志 API，未把不可读取的 Console 结果伪造成空数组。
- 采纳候选是本次测试中的明确用户决定，建立 `revision-293c472616cb`（9 个结构化正文块，内容 Hash `sha256:86b759...`）；随后真实 Provider 完成场景审查 `agent-be63727e6f1a`（9 块、0 阻塞、`9,787/5` token）、连续性审查 `agent-2acea482b9df`（`7,087/14` token）和发布审查 `agent-065b4b94baf6`（`8,159/4` token），全部 Gate 通过。自动提炼 WorkCanon 的独立 Proposal 被明确退回，WorkCanon 没有被静默扩张。
- 修复两个真实 UI/状态缺口：`web/app.js` 在候选 Diff 头部投影实际 Provider/usage，并把真实 Provider 下“模拟候选”文案改为动态文案；结构化 `scene-blocks` 修订现在被识别为已有正文。`web/writing-workbench.js` 在已有正文时恢复“检查本场”主操作，避免审查入口被上下文装饰层覆盖。`node --check web/app.js`、`node --check web/writing-workbench.js` 通过；定向回归 `test_conversation_slice.py` 为 `40 passed`，Harness/vertical slice 为 `97 passed`。
- 真实发布 Gate 最终冻结 `release-0cdfe617b580` / `v1`，ScriptRelease 内容 Hash 为 `sha256:22285...`，不可变清单包含场景修订、四项依赖修订和两个审查 Gate 快照。制作服务未运行，因此没有 ProductionRun 或资产级任务副本证据；Provider 不是 Fake，但真实费用、缓存命中和制作交接仍未验收。未修改 `08-HaloCue-1.0/`；`10-HaloCue-1.0-Integrated/` 仅保留此前获授权的集成元数据/README 变更，未复制第二套写作状态机。

## 2026-08-19 增量证据（首次使用内嵌提交与章节 Diff 复验）

- 修复首次使用路径的真实根因：隐藏/弹层内控件的事件会被大型委托捕获链截断。首次使用现在在工作区渲染 `firstWorkForm`，并由窗口级最早捕获处理取消与提交；仍复用单一 `submitWorkDialog`、重复提交锁和既有 `/api/v1/works` 边界，没有新增状态机。新增 `firstUseFormMarkup`、`bindFirstUseForm` 与窄屏样式，静态合同同步更新。
- Codex 内置 Browser 在隔离 8913 服务真实完成：空状态点击“开始一个新故事” -> 填写想法 -> 点击“取消”返回空状态，焦点回到“新建作品”；再次填写并点击“建立作品”后创建作品、默认第一章和创作主对话。手机 `390x844` 表单提交按钮在视口内，桌面 `1366x768` 也可用；提交后 Composer、作品进度和状态可见。
- 同一隔离作品建立一章一场、已确认人物卡和场景上下文后，Browser 在章节工作面实际显示 `PROPOSAL / 未写入`、模拟 Provider、运行 ID、当前正文、候选正文、逐项复选框、选择计数及“应用/退回”。手机滚动到 Diff 区后，“应用 1 项修改”可见且 `overflowX=0`；点击采纳后 Proposal 消失，页面显示结构化 6 块正文 Revision 与“已保存”，状态提示“已应用 1 项修改并建立新正文修订”。
- Browser 视口复核为 `1920x1080`、`1440x900`、`1366x768`、`390x844`；横向溢出和工作区内部溢出均为 `0`，桌面主导航、手机底部导航、Composer 和正文/Diff 控件可见。当前内置 Browser `tab.dev.logs` 对 warning/error 返回空数组；验收结束需执行 `viewport.reset()` 并清理隔离服务/数据。
- 定向 `python -m pytest tests/test_http_api.py -q` 为 `42 passed`；`node --check web/app.js` 通过。完整 09 最终回归为 `417 passed in 230.68s (0:03:50)`；10 集成回归为 `3 passed in 34.47s`。该章节 Diff 复验使用明确标注的 Fake Provider，仅证明 UI/后端边界和可审查操作，不替代真实 Provider 的既有纵切证据。未修改 `08-HaloCue-1.0/`；未复制第二套 10 状态机或入口。

## 2026-08-19 增量证据（统一入口 8910 最终状态）

- 重新启动统一入口 `http://127.0.0.1:8910/` 后，`/api/v1/health` 与 `/api/v1/capabilities` 均显示当前 Provider 为 `gemini-3.7-flash (openai)`、`can_call_model=true`、`is_simulation=false`、`config_revision=model-config-3`；usage 为 provider response supported，cache 为 unknown，公开 reasoning 摘要不暴露隐藏思维链。配置摘要只输出 digest，不输出凭据。
- 正式数据中的真实纵切运行仍可追溯：`agent-03332d00258f`、`agent-be63727e6f1a`、`agent-2acea482b9df`、`agent-065b4b94baf6` 均为成功状态；本轮没有再次触发真实模型请求，避免把健康检查误写成新的 token/费用验收。
- Codex 内置 Browser 打开 8910 实际显示 `gemini-3.7-flash · 已配置`。在 `1920x1080`、`1440x900`、`1366x768`、`390x844` 复核横向溢出与工作区内部溢出均为 `0`；Composer 可见，桌面主导航和手机底部导航在相应断点可见，`tab.dev.logs` warning/error 为空。结束前已恢复 `viewport.reset()` 并关闭验收标签页。
- 真实模型、真实 token、缓存命中、费用和制作端 ProductionRun/资产副本仍按既有证据区分：真实场景纵切有响应 usage（10,993 input / 243 output 等）但费用未知、缓存未知；制作服务未运行，不能宣称制作交接或资产副本完成。
## 2026-08-19 增量证据（真实章节 Agent 与 65536 输出上限验证）

- 通过用户提供的 OpenAI-compatible 端点 `http://59.110.165.151:3000/v1` 的 `/models` 与最小真实请求确认代理列出 `gemini-3.7-flash`，并接受 `max_tokens=65536`；最小请求返回真实 usage（`157` input / `1` completion），不能据此推断代理或模型的计费、缓存策略。正式写作配置已通过“先测试后激活”更新为 `max_tokens=65536`、`model-config-4`，密钥只保存在 Windows DPAPI，不进入日志或审计文本。
- 隔离数据目录 `D:\Temp\halocue-real-slice-20260819` 的真实章节纵切完成：`work-61bb7e549961`、`scene-ce2ae1157c76` 在显式绑定两张已确认人物卡和就绪 WritingPack 后执行 `scene.candidate.generate`，真实运行 `agent-6ddd3da10b34` 由 `gemini-3.7-flash (openai)` 产生 `proposal-af35d349951d`。Proposal 包含 13 个结构化正文块、逐项 `block_changes`、当前/候选 Diff、证据修订 ID 和内容 Hash；usage 为 `10,548 input / 303 output`，cache read/write `0`，estimated cost `null`。
- 真实候选生成完成后 AgentRun 状态为 `waiting_user`，场景 `current_revision_id` 仍为空；内置 Browser 打开章节工作面后实际显示 `PROPOSAL / 未写入`、真实 Provider、运行 ID、Token、逐项复选框和“应用/退回”。在 `390x844` 滚动到 Diff 区，“应用 1 项修改”可见且页面/工作区横向溢出均为 `0`；点击采纳后作品版本 `10 -> 11`，建立结构化正文 `revision-1adf42cb2ca5`，页面显示 `MANUSCRIPT / 修订 1`、13 个正文块和“已保存”。
- 本次 Browser 复核使用 `1920x1080`、`1440x900`、`1366x768`、`390x844`；移动底部导航和 Diff 主操作可见，视口结束已执行 `viewport.reset()` 并关闭隔离标签页。该次真实候选证据补足了“实际 Agent 调用 -> 可见文字变化 -> 用户采纳 -> 正文 Revision”链，但不替代真实费用、缓存命中或制作端副本证据。
- 正式 `8910` 仍在线，Provider 健康状态为 `gemini-3.7-flash (openai)` / `can_call_model=true` / `is_simulation=false` / `model-config-4`；制作服务 `8892` 仍未运行。未修改 `08-HaloCue-1.0/`，`10-HaloCue-1.0-Integrated/` 未新增写作状态机或入口。
- 收尾验证：`node --check web/app.js` 与 `node --check web/writing-workbench.js` 通过；完整 09 回归最终 `417 passed in 231.43s (0:03:51)`，10 集成回归最终 `3 passed in 33.14s`。统一入口健康 HTTP 200，生产端口 `8892` 明确离线；无遗留测试服务，正式 `8910` 为唯一运行中的 HaloCue 服务。
- 追加真实改写复核：隔离服务重启后第一次以旧作品版本 `11` 请求 `scene.draft.rewrite` 返回 `409 revision_conflict`（实际版本 `12`），读取最新版本后重试成功，真实运行 `agent-7e499d4cdb1c` 产生 `proposal-fe98398d24f5`。该 Proposal 基于 `revision-1adf42cb2ca5` 生成 4 个 `replace` 变化，usage 为 `10,906 input / 255 output`；Browser 在章节工作面逐项显示旧块和新块（旁白、凯伊对白及中段对白），手机滚动后应用按钮可见，`overflowX=0`。点击“退回候选”后状态为“候选已退回”，正式正文仍保持 13 块，证明改写也遵循 Proposal-only 与版本冲突恢复边界。

## 2026-08-19 增量证据（场景 Provider 错误保真与恢复卡）

- 复现根因：`run_scene_agent` 与 `run_scene_rewrite_agent` 原先把 Provider 异常压成 `provider_failed`，丢失 `writing_provider_failed`、`failure_kind`、原始 message/status/details；兼容 `scene.candidate.generate` 的持久化 failure 也只保存 code/message/retryable。
- 最小修复位于 `src/halocue_writing/service.py`：统一规范化场景 Provider failure，保留 `code/type/message/status/retryable/details`，并把 `failure_kind` 提升为可读字段；外层继续使用兼容 UI 的 `agent_failed`，details 同时携带 `agent_run_id` 与完整 failure。AgentRun、WorkItem、JobAttempt 使用同一真实 code，重试仍从固定输入快照创建新 Run，正式正文和 Revision 不变。Presentation 只公开白名单字段（含 status/failure_kind），不暴露原始响应。
- 新增参数化回归覆盖 `scene.draft.generate`/`scene.draft.rewrite` 与 `provider_timeout`/`provider_rate_limited` 四种组合，验证 API、AgentRun、WorkItem、JobAttempt 一致保真，并验证重试产生待审 Proposal；定向套件 `186 passed`，Python/JS 语法检查通过。
- `web/app.js` 新增场景级 Recovery 卡，按 Scene ID 显示超时/限流原因、固定输入和正文未修改边界，只有一个重试入口；失败后刷新已保存运行，重试成功后焦点回到候选审查。复用现有恢复卡和窄屏布局，没有第二套状态机。
- Codex 内置 Browser 隔离夹具实测 `1440x900` 与 `390x844`：恢复卡、超时文案、唯一重试、Composer、逐项 Diff、应用/退回入口和移动底部导航可见；点击重试真实形成待审正文 Proposal，Recovery 卡消失、焦点落到“查看候选”；两视口 `overflowX=0`，Console warning/error 均为 `[]`，结束执行 `viewport.reset()`、关闭标签页和夹具服务。
- 交付门最终完整 09：`422 passed in 233.28s (0:03:53)`；10 集成网关只读回归：`3 passed in 31.87s`。正式 `http://127.0.0.1:8910/` HTTP `200`、PID `39880`，制作端 `8892` 仍离线；本轮未修改 `08-HaloCue-1.0/` 或 `10-HaloCue-1.0-Integrated/`，未向正式作品采纳/冻结/交接任何 Proposal。
- 仍未完成或无证据：首次使用从入口到建立作品的连续 Browser 点击证据仍受控件/控制面限制；真实 Provider 网络超时/限流尚未在真实端点做故障注入；真实费用、cache 命中/策略、制作端 `scene_asset_handoff` 与资产级 ProductionRun 副本回执仍不存在。正式 Provider 当前仍是 `gemini-3.7-flash (openai)`、`can_call_model=true`、`is_simulation=false`、配置 `model-config-4`；代理接受 `max_tokens=65536`，不能据此宣称官方输出上限或费用完成。

## 2026-08-19 增量证据（真实候选文案与章节工作面回归）

- 复现真实 Provider 章节生成后 Toast 仍显示“模拟候选已生成”的事实边界错误。根因是兼容正文按钮的旧事件委托固定写死模拟文案；候选本体虽然已显示真实 Provider，但完成反馈会误导用户。
- 最小修复位于 `web/app.js`：正文工作面 `data-action="generate-candidate"` 现在在捕获阶段调用同一真实 `/candidate:generate` 合同，并按返回的 `simulation` 显示“模拟候选”或“真实 Provider 候选”；失败时明确显示正式正文未修改。素材建议标签同步为“本地规则建议 · 未调用模型”，区分局部规则建议与本场 Agent Provider。
- 新增 `tests/test_phase0_contracts.py` 文案事实边界合同；素材目录合同同步更新。JS 语法检查通过；定向套件 `109 passed`，最终完整回归包含该合同。
- 统一入口 `http://127.0.0.1:8910/` 实际重新加载后再次调用真实 `gemini-3.7-flash (openai)` 生成候选：运行 `agent-564928fb6953`，页面显示真实 Provider、运行 ID、token、逐项 Current/Candidate Diff；Toast 实际为“真实 Provider候选已生成，等待你的决定”。随后点击退回，Proposal 消失，正式正文仍为 `MANUSCRIPT / 修订 1`，首段文字未改变。
- Browser 检查：`1440x900` 桌面 Diff 主操作滚动后可见；`390x844` 手机应用/退回、Composer、底部导航均可见；两种视口页面与工作区 `overflowX=0`，Console warning/error 为 `[]`。结束前执行 `viewport.reset()`。
- 最终完整回归：09 `423 passed in 212.61s (0:03:32)`；10 集成网关 `3 passed in 31.65s`。无测试/夹具遗留进程。未修改 `08-HaloCue-1.0/` 或 `10-HaloCue-1.0-Integrated/` 源码，未采纳或冻结本次验收候选。
- 仍未完成或无证据：真实 Provider 429/504 注入、真实费用 receipt、cache 命中/策略、制作端 `scene_asset_handoff` 和资产级 ProductionRun 副本；首次使用连续 Browser 证据仍保留控制面缺口。Provider 仍为真实 `gemini-3.7-flash (openai)`，不是 Fake；代理接受 `max_tokens=65536` 不等于官方计费/输出保证。

## 2026-08-19 增量证据（OpenAI-compatible Provider HTTP 恢复夹具）

- 新增 `tests/test_provider_http_recovery.py`，只监听临时 `127.0.0.1` 端口，不连接或冒充用户提供的远端服务。夹具返回合法 OpenAI-compatible `/v1/chat/completions` 响应，并可按序注入 HTTP `429`、`504`。
- 传输层合同验证：429/504 首次失败后按 Provider 重试策略得到第二次 200；usage 保留 `17` input / `6` output、`cache_status=unknown`、`estimated_cost=null`，没有把未知费用写成 0。最终三次 429/504 会保留 `writing_provider_failed`、`failure_kind` 和 `http_status`。
- 端到端服务合同验证：真实 `LLMWritingProvider` 接到场景 Agent 后，三次 429 会持久化 AgentRun、WorkItem、JobAttempt 的 `provider_rate_limited` 失败；切换同一临时夹具为 200 后显式 `retry_agent_run` 生成新运行和 Proposal，场景 `current_revision_id` 仍为空，证明恢复不会静默写入正文。
- 定向测试 `tests/test_provider_http_recovery.py`：`5 passed`。该夹具是本地协议与恢复证据，不等同于远端真实 Provider 的故障注入验收；真实远端 429/504 仍保持证据缺口。
- 内置 Browser 复核既有场景恢复卡：`1440x900` 显示唯一“重试本轮”，点击后候选出现且焦点落到“查看候选”；`390x844` 显示 Composer、手机底部导航、Diff、应用/退回，页面与工作区 `overflowX=0`，Console warning/error `[]`。已执行 `viewport.reset()`，关闭标签页并清理临时夹具服务。
- 最终交付回归：09 `428 passed in 213.22s (0:03:33)`；10 集成网关 `3 passed in 31.83s`。JS/Python 语法检查通过；正式 `8910` HTTP `200`，Provider 为 `gemini-3.7-flash (openai)` / `can_call_model=true` / `is_simulation=false` / `model-config-4`，制作端 `8892` offline；无测试或 Browser 夹具残留进程。

## 2026-08-19 增量证据（章节候选逐块对齐与真实 Provider 复验）

- 复现真实章节候选审查缺口：一次真实 `scene.draft.generate` 运行 `agent-0a87a4f451d2` 返回 `10,993` 输入 / `265` 输出 token，原有 Diff 把整场 9 个正文块合并为“修改 1 项”，并在删行后将说话人错位配对；候选仍停在 `PROPOSAL / 未写入`，正式正文当时为 `MANUSCRIPT / 修订 1`。
- 最小修复位于 `src/halocue_writing/service.py`：新增基于正文块类型、说话人和文本相似度的稳定序列对齐；重写场景现在按独立替换、删除、插入块生成 `block_changes`，不再把整段连续改写合成一个操作。`_apply_scene_block_changes` 保持原有 Proposal -> 用户选择 -> Revision 边界，未引入第二套状态机。
- 最小 UI 修复位于 `web/app.js`：单侧 Diff 标签显示“说话人 · 删除/新增”，避免“凯伊 → 候选块”的误导；全选按钮在全选后切换为“取消全选”，取消后应用按钮禁用。静态资源版本更新为 `app.js?v=20260819-33`。
- 新增回归 `test_scene_proposal_aligns_a_full_rewrite_into_reviewable_block_changes`，验证完整重写被拆成 6 个可审查块操作、删除项保持正确角色对齐、只选一个变化时其余正文保留。定向章节/HTTP 回归通过：章节相关 `3 passed`，HTTP 合同 `42 passed`；`node --check web/app.js`、Python 编译检查通过。
- Codex 内置 Browser 实际复验统一入口 `http://127.0.0.1:8910/`：候选重载后显示 `9` 个独立变化、删除项为“凯伊 · 删除”，选择计数为 `9 / 9`；点击“取消全选”得到 `0 / 9` 且“应用 0 项修改”禁用，再点恢复全选。`1920x1080`、`1440x900`、`1366x768`、`390x844` 均检查页面横向溢出为 `0`；Composer 可见，桌面主导航与移动底部导航可见，Console warning/error 均为 `[]`。`390x844` 滚动到 Diff 末尾后“应用 9 项修改”和“退回候选”完整可见。
- 本次真实测试候选随后通过 Browser 明确退回；候选消失，页面保持 `MANUSCRIPT / 修订 1`，正文没有被模型静默改写。结束前已执行 `viewport.reset()`；正式服务 `8910` 保持在线，制作服务 `8892` 仍 offline。
- 交付回归最终汇总：09 `429 passed in 239.19s (0:03:59)`；10 集成网关只读回归 `3 passed in 31.68s`。本轮只修改 `09-HaloCue-1.0-Writing`，未修改 `08-HaloCue-1.0` 或 `10-HaloCue-1.0-Integrated` 源码、未新增第二入口。
- 证据边界未改变：真实 Provider 费用 receipt、cache 命中/策略、远端 429/504 故障注入、制作端 `scene_asset_handoff` 与资产级 ProductionRun 副本仍缺失；本轮真实 usage 只证明 Provider 响应 usage，不证明费用或缓存完成。

## 2026-08-19 增量证据（正式 8910 真实候选与任务状态语义）

- 正式统一入口再次执行 `scene.draft.generate`：真实运行 `agent-67e23b161c53` 使用 `gemini-3.7-flash (openai)`，Provider response usage 为 `10,993 input / 298 output` token，产生 Proposal `proposal-73315e3ec7d8`。候选基于 `revision-293c472616cb`，页面逐项显示 10 个替换/删除/新增变化、当前正文和候选正文；生成期间及退回后场景当前 Revision 均保持 `revision-293c472616cb`。
- Codex 内置 Browser 在 `1920x1080`、`1440x900`、`1366x768`、`390x844` 检查真实候选和退回后的正文工作面：各视口 `overflowX=0`，桌面主导航、手机底部导航、本场 Agent 入口和 `MANUSCRIPT / 修订 1` 可见；候选阶段手机底部可到达应用/退回操作。Console warning/error 为 `[]`，结束前执行 `viewport.reset()`。
- 发现并修复等待用户决定的 Proposal 被顶部误计为“后台任务”的状态语义：`web/app.js` 现在仅将 `ready/running` 计入后台执行数，将 `waiting_user` 单列为“待审查”；退回本次候选后顶部实际显示“后台任务 0”。新增静态合同，`app.js` 版本更新为 `20260819-34`。
- 临时 10 集成运行时 `8914` 的只读能力探测确认写作 Provider 可用，制作端声明 `custom_assets` 与 `script_release_handoff`，但未声明 `scene_asset_handoff`；已有无素材引用 release 返回 `production-assets status=not_required / expected_count=0`，不能作为资产副本成功证据。临时 PID `23276` 已停止，正式 `8910` 保持运行。
- 本轮 `node --check web/app.js`、定向合同 `7 passed`；静态资源版本提升后第一次完整回归因 HTTP 合同仍锁定旧 `app.js?v=20260819-33` 得到 `429 passed / 1 failed`，同步合同到 `20260819-34` 后重新完整运行，最终汇总 `430 passed in 212.54s (0:03:32)`。未修改 08 或 10 源码；制作端素材交接缺口不能通过复制写作状态机解决。
- 证据缺口仍为：费用 receipt 与可靠单价不存在，cache 策略/命中未知，远端真实 429/504 未注入，制作端缺少 `scene_asset_handoff`，没有带素材引用的 ProductionRun 资产副本回执。当前真实 Provider 为 `gemini-3.7-flash (openai)`、`model-config-4`、`max_tokens=65536`；该数值有代理接受证据，不把它扩大解释为代理定价或缓存能力。

## 2026-08-19 增量证据（集成制作面异步焦点恢复）

- 在正式根目录 `10-HaloCue-1.0-Integrated` 启动临时集成运行时 `8914`，复现写作页切入嵌入式 AA 制作后焦点落到顶层导航按钮，以及选择冻结剧本触发 ShadowRoot 重绘后焦点退回 `BODY`。根因是 `web/production-embed.js` 只在异步加载前聚焦宿主，加载/选任务完成及内部异步重绘后没有恢复焦点。
- 最小修复位于 `09-HaloCue-1.0-Writing/web/production-embed.js`：异步 `ensureProductionSurface` 与 `selectRun` 完成后再次聚焦 `#productionModule`；为 ShadowRoot 安装受限 MutationObserver，仅在制作模式、宿主可见且焦点实际落到 `BODY` 时恢复宿主，不覆盖用户正在操作的内部控件。静态资源版本更新为 `production-embed.js?v=20260819-3`。
- 新增两个 HTTP 静态合同，分别锁定初次异步打开和内部重绘后的焦点恢复。定向 `test_http_api.py` + `test_phase0_contracts.py` 为 `50 passed`，`node --check web/production-embed.js` 通过；完整 09 最终为 `432 passed in 239.29s (0:03:59)`，10 集成网关为 `3 passed in 35.80s`。
- Codex 内置 Browser 在正式根 10 临时集成入口验证：初次打开后 `document.activeElement` 为 `SECTION#productionModule`；点击“选用此剧本制作”并等待内部重绘后仍为该宿主。`1440x900`、`1366x768`、`390x844` 均为 `overflowX=0`，桌面主导航、手机底部导航、制作步骤与冻结剧本选择可见，Console warning/error 为 `[]`，结束前执行 `viewport.reset()`。
- 工具恢复事实：第一次误启动 `11-HaloCue-1.0-后端协作交接包` 中的历史 10/09 副本，浏览器仍复现旧焦点；检查服务响应脚本 Hash 和目录解析后关闭 PID `23632`，改用正式根目录 10 重试并通过。该失败没有写成产品验收证据。
- 集成 Browser 使用 `D:\Temp\halocue-integrated-prod-ui-20260819c` 临时制作数据；未修改 `08-HaloCue-1.0` 或 `10-HaloCue-1.0-Integrated` 源码。08 制作 UI 的角色映射卡仍错误使用全局 `dialogue_count`，导致每个角色都显示总台词数；因未获 08 源码修改授权，本轮只记录为制作域缺口，没有在 09/10 复制覆盖逻辑。
- 仍未完成：制作端 `scene_asset_handoff`、带素材引用的 ProductionRun 资产副本回执、真实费用 receipt、cache 命中/策略、远端真实 429/504、真实 AA 编译/安装。正式 `8910` 仍是根 09 写作服务，健康状态为 `gemini-3.7-flash (openai)` / `can_call_model=true` / `is_simulation=false` / `model-config-4`；这轮未新增真实模型调用或 usage。

## 2026-08-19 增量证据（集成入口返回写作路径）

- 在正式根 10 临时运行时 `8914` 复现返回缺口：AA 制作中点击“写作”只把导航标为 active，`production-mode`、制作 ShadowRoot 和 `section=production` URL 仍保留。根因是 `10-HaloCue-1.0-Integrated/static/integration-shell.js` 只依赖桥接对象 `isOpen()`，且关闭时没有带目的 section。
- 用户已授权合并到 10；最小修复仅修改 `10-HaloCue-1.0-Integrated/static/integration-shell.js`：以 `#app.production-mode` 或桥接对象作为打开状态兜底，并调用 `close({ section: destination })`，复用现有单一嵌入状态机。新增网关静态合同锁定该路径；`node --check static/integration-shell.js` 通过，10 网关回归 `3 passed in 31.84s`。
- Browser 复验桌面和手机：进入 AA 制作后焦点为 `#productionModule`；点击“写作”后 `production-mode=false`、宿主 `hidden=true`、URL 回到 `section=writing` 并保留 `work_id/chapter_id/scene_id`，焦点在触发的写作导航；`390x844` 与桌面横向溢出均为 `0`，手机底部导航可见，Console warning/error 为 `[]`，结束执行 `viewport.reset()`。
- 因本轮触及集成路由/UI，重新跑完整 09，最终 `432 passed in 216.76s (0:03:36)`。本次修改明确落在已获授权的 `10-HaloCue-1.0-Integrated`，未修改 08，也没有复制第二套状态机。

## 2026-08-19 增量证据（正式 8910 切换为集成入口）

- 停止旧的单独 09 写作服务和临时 8914 夹具后，正式启动根 `10-HaloCue-1.0-Integrated` 于 `http://127.0.0.1:8910/`；进程 PID `16788`，`/api/v1/health` HTTP `200`，当前服务为 `halocue-writing` 上游，Provider 为真实 `gemini-3.7-flash (openai)`、`can_call_model=true`、`is_simulation=false`、`model-config-4`，usage supported、cache unknown。
- Browser 在正式 8910 验证统一入口切入 AA 制作后 `production-mode=true`、ShadowRoot 已挂载、`#productionModule` 获得焦点；`1920x1080`、`1440x900`、`1366x768`、`390x844` 均为 `overflowX=0`。桌面主导航、手机底部导航、制作步骤和剧本选择面可见，Console warning/error 为 `[]`。
- 正式 8910 返回写作路径也已复验：从制作面点击可见“写作”节点后，`production-mode=false`、制作宿主 `hidden=true`、URL 回到 `section=writing` 并保留 `work_id/chapter_id/scene_id`，焦点在写作导航；最终使用 Browser 可见 DOM 点击完成，结束执行 `viewport.reset()` 并关闭标签页。
- 正式服务状态保持为 8910 集成网关唯一 HaloCue 进程；没有 pytest、8914 或浏览器夹具残留。10 网关 `3 passed in 31.84s`，完整 09 最终 `432 passed in 216.76s (0:03:36)`。
- 正式 8910 的 `/production/api/v1/health` 也已确认 `halocue-production` 上游在线，`custom_assets` 与 `script_release_handoff` 可用；`scene_asset_handoff` 仍未声明，故不能把服务在线误写成素材任务副本完成。

## 2026-08-19 增量证据（正式入口素材库与模型设置显示）

- 正式 8910 Browser 只读检查素材库：桌面和 `390x844` 均显示“我的素材 / AA 内置资源”、背景/角色/音效/插图分类、上传入口和空库 `0 / 0`；页面明确写出 AI 识别只生成标签建议，确认登记后才进入素材库，点击加入任务后才复制到 ProductionRun。横向溢出为 `0`，手机底部导航可见，Console warning/error 为 `[]`。
- 打开设置中心后，运行时真实覆盖静态占位，显示 `gemini-3.7-flash (OpenAI 协议)`、模型配置 `model-config-4`、DPAPI 已保护、连通性已验证及当前写作运行时；没有把初始 HTML 的 Fake Provider 占位误当成当前状态。设置面 `overflowX=0`，Console warning/error 为 `[]`，结束执行 `viewport.reset()` 并关闭标签页。

## 2026-08-19 增量证据（场景素材引用隔离验收与正式服务恢复）

- 在隔离数据目录启动临时集成入口 `8915`，通过正式 HTTP API 建立 Work `work-ab4e9a33fdf2`、Chapter `chapter-93bf029ece3e`、Scene `scene-356d6d653ac7`，选择 AA 内置背景原件 `00000-1392481605`。场景页面实际显示 `1 个素材引用`、原件版本 `catalog:557fea7aaf34`、原件 Hash `121522699`（`aa_resource_hash`），以及“尚未收到 ProductionRun 副本回执”；`production_copy` 没有被伪造填充，正文与正式资料均未改变。
- Codex 内置 Browser 对隔离场景实际检查 `390x844`：素材引用详情、版本/Hash、任务副本缺失边界、单一阻塞入口和移动底部导航可见，页面 `overflowX=0`，Console warning/error 为 `[]`；结束执行 `viewport.reset()`。该夹具只证明引用追溯 UI 和缺失回执状态，不是正式 ProductionRun 副本证据。
- 定向素材回归 `tests/test_scene_asset_references.py`：`11 passed in 10.40s`；收尾复跑为 `11 passed in 14.86s`。完整 09 最终回归 `432 passed in 240.55s (0:04:00)`，10 集成网关最终 `3 passed in 32.55s`，Python/JS 语法检查通过。随后已停止临时 `8915`，重新启动根 `10-HaloCue-1.0-Integrated` 正式 `http://127.0.0.1:8910/`；写作健康 HTTP `200`，Provider 为真实 `gemini-3.7-flash (openai)` / `can_call_model=true` / `is_simulation=false` / `model-config-4`，`max_tokens=65536`，usage supported、cache unknown；制作健康 HTTP `200`，但仍未声明 `scene_asset_handoff`。
- 正式章节工作面 Browser 实际复核 `1920x1080`、`1440x900`、`1366x768`、`390x844`：真实 Provider badge、`与本场 Agent 讨论`、Composer、素材入口、结构化正文和生成候选均可见，各视口 `overflowX=0`，Console warning/error 为 `[]`。刷新后手机标题盒模型位于固定顶栏下方，确认先前标题遮挡是旧滚动位置而非刷新布局缺陷；结束前已执行 `viewport.reset()`。
- 仍未完成或无证据：真实素材 ProductionRun 副本回执、制作端 `scene_asset_handoff`、真实费用 receipt、cache 命中/策略、远端真实 429/504、真实 AA 编译/安装；08 的角色映射计数问题仍未获授权修改。未修改 `08-HaloCue-1.0/`。

## 2026-08-19 增量证据（10 集成层素材副本回执纵切）

## 2026-08-19 增量证据（迟到素材回执重试恢复）

- 修复 `09-HaloCue-1.0-Writing/src/halocue_writing/service.py` 的交接重试边界：已有 `ScriptRelease.production_run_id` 或通过上游列表找回既有 ProductionRun 时，如果发布快照包含场景素材引用，重试会重新拉取并校验 `production-asset-usage/1.0`，不再因 `idempotent=true` 提前返回而丢失迟到回执。
- 新增回归 `tests/test_scene_asset_references.py::test_retrying_an_existing_production_run_reconciles_a_late_asset_receipt`，验证首次回执缺失为 `pending`，制作端稍后返回匹配副本后再次交接保持同一 ProductionRun、状态变为 `complete`，并只更新场景素材 `production_copy`，不修改正文或正式 Revision。
- 定向素材回归 `12 passed in 11.77s`；Python 编译检查通过。完整 09 最终 `433 passed in 241.21s (0:04:01)`，10 集成网关最终 `4 passed in 56.80s`。
- 该切片仍不等同于正式用户作品的带素材交接证据；真实费用 receipt、cache 命中/策略、远端真实 429/504、真实 AA 编译/安装仍缺证据。未修改 `08-HaloCue-1.0/`。

## 2026-08-19 增量证据（真实 Provider 章节候选纵切）

- 使用隔离数据目录和正式 DPAPI 模型配置，真实调用 `http://59.110.165.151:3000/v1/chat/completions` 的 `gemini-3.7-flash`；本场中文运行时人物卡、BA WritingPack 和上下文门禁均为 `ready_for_provider`，配置 `max_tokens=65536`。
- 真实调用成功生成 514 字符章节候选，创建 `Proposal proposal-ef96cb7320e0`，状态 `pending`；统一 Diff 19 条、字符级 `inline_diff` 16 条；AgentRun 状态 `waiting_user`，usage 已记录 `input_tokens=9806`、`output_tokens=398`、`cache_status=supported_miss`、费用未报告；正式场景 `current_revision_id` 保持不变。
- 另一隔离探测故意使用英文人物卡 `Alice`，模型按 BA 语料返回中文 speaker `爱丽丝`，严格 speaker 身份校验拒绝创建 Proposal，正文仍未改变。这证明未知角色名不会被静默映射；正式中文卡重试后通过。该失败不是 Provider 伪造成功。
- 远端 `/v1/models` 列表确认存在 `gemini-3.7-flash`，但没有返回上下文或最大输出 token 字段；`65536` 是当前已配置且实际请求接受的值，不宣称为该代理或模型的官方最大值。真实费用 receipt、cache 命中、远端真实 429/504、AA 编译/安装仍缺证据。
- 正式 `8910` Browser 只读复核章节面：`1440x900` 与 `390x844` 均显示场景工作区、正文/Agent/审查切换、Agent Composer、正文候选入口和移动导航；两视口 `overflowX=0`，Console warning/error 为空。此次不在正式用户数据上点击“生成候选”，真实候选与 Diff 已在隔离 Provider 纵切中验证；结束已执行 `viewport.reset()` 并关闭标签。

## 2026-08-19 增量证据（10 集成层素材副本回执纵切，记录续）

- 在已授权修改的 `10-HaloCue-1.0-Integrated` 增加 `IntegratedProductionService` 适配层，未修改 `08-HaloCue-1.0`。适配层复用 08 的冻结 `resources.json` 与自定义素材任务复制能力，校验 `production-asset-handoff/1.0` 的 release ID、source-set digest、场景引用 digest、原件身份/Hash 和 source snapshot；只有快照中真实存在的资源或已复制到任务的自定义素材才会写入 `production-asset-usage/1.0` 回执。
- 10 集成纵切实际完成：AA 背景原件 `00000-1392481605` 进入 ProductionRun `run-cc279a4d8905`，回执 `copy-a69ec22e9d12`、任务副本 Hash `121522699` 与原件身份匹配；09 场景引用由 `production_copy=null` 更新为该回执。空素材 ScriptRelease 的现有交接仍保持兼容，10 网关定向回归 `4 passed in 50.73s`，收尾完整回归 `4 passed in 53.97s`；随后完整 09 回归 `432 passed in 238.50s (0:03:58)`。
- 隔离 `8916` Browser 实际检查带回执场景 `1440x900`、`390x844`：素材详情显示“已收到任务副本 · copy-a69ec22e9d12 · 121522699”，原件版本/Hash 可展开；两视口 `overflowX=0`，手机底部导航可见，Console warning/error 为 `[]`，结束执行 `viewport.reset()` 并关闭标签。该回执来自隔离 ProductionRun，不冒充正式用户作品数据。
- 正式 `8910` 已重启到新适配器，制作健康 HTTP `200` 且声明 `scene_asset_handoff=available`、`custom_assets=available`、`script_release_handoff=available`。真实费用、cache 命中/策略、远端真实 429/504、真实 AA 编译/安装仍是独立证据缺口；08 角色映射计数问题仍未授权修改。

## 2026-08-19 Agent 调用保真与章节候选 UI 回归

- 复现正式 `8910` 的真实 Provider HTTP `400 invalid_request_error`。Provider 正文指出模型别名不可用；后端原先只保存 `HTTP Error 400`。`providers.py` 现在保存有界的 `provider_message/provider_response`，归类为 `provider_invalid_request`，不保存 API Key、Prompt 或完整请求。
- `web/app.js` 失败卡显示“模型请求被拒绝”，技术详情提供 Provider 诊断并引导模型设置；真实 Provider 失败不会回退 Fake 或修改正文。章节兼容候选按钮的旧委托路径已不再发起重复 `/candidate:generate` 请求，唯一处理器按返回值显示“模拟”或“真实 Provider”；静态版本为 `app.js?v=20260819-35`。
- 正式真实章节纵切成功生成 `agent-f0e3cc4b8801` / `proposal-060e20bad03c`，Provider `gemini-3.7-flash (openai)`，usage `10,993 input / 300 output` token。Browser 显示 10 个独立替换/新增变化、每项 Current/Candidate 和字符级改动；AgentRun 为 `waiting_user`，场景保持 `revision-293c472616cb`。明确退回后 Proposal 消失，正文未改变。
- Browser `1440x900` 与 `390x844` 章节工作面横向溢出均为 `0`；Composer、正文/Agent/审查切换、素材入口、移动导航、应用/退回入口可见；Console warning/error `[]`，短视口截图无遮挡；结束执行 `viewport.reset()`。
- 定向 Provider/UI 回归 `29 passed`，Python/JS 语法检查通过；完整 09 `435 passed in 240.21s (0:04:00)`，10 集成 `4 passed in 50.97s`。正式 `8910` HTTP `200`，仅 8910 进程监听；未修改 `08-HaloCue-1.0/` 或 `10-HaloCue-1.0-Integrated/` 源码。

## 2026-08-19 真实讨论到章节 Proposal/Diff 纵切（当前切片）

- `LLMWritingProvider.discuss_work()` 现在只在讨论回合兼容网关返回的普通公开文本：原文作为可见 `text` 保存，`ready_for_proposal=false`，不把非 JSON 文本或隐藏 `reasoning_content` 变成正式 Proposal；正文生成、审查和发布仍保持严格结构化合同。新增 Provider 回归覆盖普通文本兼容、Gemini 3 的 `max_completion_tokens` 参数和 reasoning 不外泄；定向 `47 passed`，Python 编译通过。
- 正式 `8910` 真实讨论运行 `agent-cbbd2633b21a` 完成，Provider `gemini-3-flash (openai)`，只读工具 `load_workflow_template`、`read_work_context` 均成功，usage `15,386 input / 199 output`，公开文本被保存但 `proposal_id=null`；正式场景仍为 `revision-293c472616cb`。
- 通过本场持久化讨论生成真实章节改写 Proposal `proposal-283fc2fa4b72`，AgentRun `agent-76ee8a48125e` 状态 `waiting_user`，Provider usage `11,956 input / 201 output`。Proposal 为 `pending`，基准修订 `revision-293c472616cb`，含 5 个块级变化、1 组文字级 inline Diff 和完整统一 Diff；正文 Revision 未改变，未发生静默写回。
- Browser 复验正式 `8910` 候选审查面：`1920x1080`、`1440x900`、`1366x768`、`390x844` 均显示真实 Provider、候选 Current/Candidate、文字级删除/新增、复选框和应用/退回入口；Composer、手机底部导航可见，横向溢出分别为 `0`，Console warning/error 均为 `[]`，结束已执行 `viewport.reset()`。
- 当前写作配置为 `gemini-3-flash`、`max_tokens=65536`，代码对 Gemini 3 发送 `max_completion_tokens=65536`。远端 `/v1/models` 列出 `gemini-3.7-flash` 但聊天请求实际返回无可用 channel；模型清单没有 `max_output_tokens` 字段。故当前真实纵切不宣称 Gemini 3.7 已验收，也不宣称代理官方最大 token、费用 receipt 或 cache hit。
- 仍未完成或无证据：用户对该 Proposal 的采纳/部分采纳（本轮不代替用户做决定）、真实费用 receipt、代理 cache 命中策略、远端真实 429/504、正式带素材 ProductionRun 回执和正式 AA 工作区安装。未修改 `08-HaloCue-1.0/` 或 `10-HaloCue-1.0-Integrated/` 源码。

## 2026-08-19 收尾回归（当前切片）

- 09 写作全量最终汇总：`437 passed in 321.24s (0:05:21)`。
- 10 集成全量最终汇总：`8 passed in 106.05s (0:01:46)`；本切片未修改 10 源码，8910 仍由集成入口提供。
- 收尾 Browser Agent 面补验：`390x844` Composer 可见，存在待审 Proposal 时“形成改写候选”被禁用，提示可查看候选；横向溢出 `0`，Console warning/error `[]`，已执行 `viewport.reset()`。
- 正式服务收尾仍需记录为运行态事实：8910 HTTP 健康、真实 Provider 配置和当前 pending Proposal 均可查询；没有遗留 pytest 会话、临时端口或额外 HaloCue 监听进程。

## 2026-08-19 Provider 配置恢复为 Gemini 3.7

- 网关瞬时路由恢复后，使用同一 API 对精确模型名 `gemini-3.7-flash` 做最小公开请求：返回模型别名 `gemini-3.7-flash-tiered`、公开内容 `OK`，`max_completion_tokens=1024` 成功，未返回 reasoning 内容。此前一次同模型请求的无 channel 错误记录为外部网关瞬时失败，不再据此永久降级。
- `data/writing-model.json` 已更新为 `gemini-3.7-flash`、`settings_version=6`、`model-config-6`、`max_tokens=65536`；服务端对 Gemini 3 发送 `max_completion_tokens`。8910 重启后健康接口确认 `can_call_model=true`、`is_simulation=false`、运行时模型为 `gemini-3.7-flash`。
- 当前 pending Proposal `proposal-283fc2fa4b72` 是切换前 `gemini-3-flash` 的真实候选，仍保持 Proposal-only；配置切换没有修改或采纳该候选。后续新 Agent 运行将使用 `gemini-3.7-flash`，本轮不代替用户处理既有决定。
- 配置切换后的设置/Provider 定向回归：`41 passed in 10.23s`；8910 重启后健康检查仍 HTTP `200`，没有遗留测试会话或额外 HaloCue 进程。
- 配置重启第一次组合命令被执行器策略拒绝，旧服务仍保持健康；随后拆分为停止、启动、健康检查三步恢复，最终只剩集成服务监听 `8910`，未把调用失败伪装成应用成功。
- 证据边界：usage 不是费用 receipt；缓存策略/命中、代理官方最大 token、远端真实 429/504、正式用户作品带素材 ProductionRun 回执和真实 AA 编译/安装仍缺证据。`max_tokens=65536` 仅为已配置并被代理接受的请求值，不宣称为官方上限。

## 2026-08-19 增量证据（10 集成交接校验、统一入口真实纵切）

- 经用户授权，修改范围扩展到 `10-HaloCue-1.0-Integrated` 的集成适配层；没有修改 `08-HaloCue-1.0`。`production_assets.py` 现在对 `custom_library` 引用校验冻结快照的 asset ID、来源版本、`file_sha256` 和当前原件 Hash，拒绝篡改或过期引用；新增 4 组篡改/过期回归。集成清单 build ID 更新为 `halocue-integrated/1.0.0+20260819.6`。
- 10 定向/完整回归最终为 `8 passed in 112.54s`；Python `compileall`、`node --check static/integration-shell.js` 通过。09 完整回归最终为 `435 passed in 244.36s (0:04:04)`。
- 正式 `http://127.0.0.1:8910/` 已由 10 集成网关提供，当前监听 PID `21020`；`/integration/manifest` 返回 build `.6`，写作与制作健康接口均 HTTP `200`。写作 Provider 为真实 `gemini-3.7-flash (openai)`、`can_call_model=true`、`is_simulation=false`、`model-config-4`、`max_tokens=65536`。
- Browser 在统一入口实际触发一次真实 `scene.draft.generate`：运行 `agent-989f155d7da2`，Provider usage `10,993 input / 250 output`，生成 9 个独立逐块变化；页面同时显示 Current/Candidate、字符级“删除/新增”、运行 ID 和模型。明确退回后 Proposal 消失，正式正文仍为 `revision-293c472616cb`，没有静默写回。
- Browser 在 `390x844` 检查候选 Diff：字符级高亮、逐项复选框、应用/退回操作、移动底部导航均可达；`overflowX=0`，Console warning/error `[]`。桌面 `1440x900` 检查工作区和 Provider/usage 标识；结束前执行 `viewport.reset()`。
- Browser 随后从同一写作发布版本切换到 AA 制作，选择 `release-0cdfe617b580` 并实际建立 ProductionRun `run-6c88b3987362`；制作页进入“剧本初审 / 等待角色映射”，解析出 3 位说话者、9 段台词和 9 项阻断诊断。`1440x900` 与 `390x844` 均无横向溢出，制作宿主焦点为 `#productionModule`，Console warning/error `[]`。该纵切尚未执行角色映射、编译或安装。
- Google 官方 Gemini API 模型页确认 `gemini-3.7-flash` 输入上限 `1,048,576`、最大输出 `65,536`；当前 `max_tokens=65536` 与官方上限一致。官方页同时标注缓存能力 supported，但本地 OpenAI-compatible 代理只返回 `cache_status` 的有限观测，本项目仍不把官方能力写成代理真实 cache hit/费用证据。来源：`https://ai.google.dev/gemini-api/docs/models/gemini-3.7-flash`。
- 仍未完成或无证据：真实费用 receipt、代理真实 cache hit/策略、远端真实 429/504 注入、正式带素材用户作品的 ProductionRun 副本回执、角色映射计数修复（08 未授权）、真实 AA 编译/安装。当前 Provider 不是 Fake；usage 不是费用，`run-6c88b3987362` 也不代表已编译或安装。

## 2026-08-19 10 集成 build .7 角色计数与真实制作纵切

- 经用户授权继续修改 `10-HaloCue-1.0-Integrated`。嵌入适配层按 `source_summary.speaker_details[].count` 展示当前说话者台词数，不再读取全局 `dialogue_count`；build ID 为 `halocue-integrated/1.0.0+20260819.7`。没有修改 `08-HaloCue-1.0`，没有复制第二套状态机。
- 10 集成完整回归最终 `8 passed in 111.30s`；`python -m compileall -q src tests`、`node --check static/integration-shell.js` 通过。正式唯一入口 `8910` 的 manifest 返回 `.7`，写作/制作健康 HTTP 200，Provider 为 `gemini-3.7-flash (openai)` / `model-config-4` / `max_tokens=65536`。
- Browser 实测 `run-6c88b3987362` 的制作初审分别显示凯伊、旁白、星野各 `3 段台词`，而脚本总数为 `9`；`1440x900`、`1366x768`、`390x844` 横向溢出均为 `0`，手机底部导航可见，章节正文手机面 Composer/正文/Agent/审查入口可见。
- 同一隔离 ProductionRun 实际完成凯伊 -> `Key`、旁白 -> `narrator`、星野 -> `星野(一年级)` 映射；10 张卡全部审查后编译完成，构建 `build-734bb18d26c0`，compile gate passed。安装目标预检返回可用，但未执行对 AA 工作区的持久安装，不宣称安装完成。
- Browser 检查编译完成页和返回写作路径，`overflowX=0`，Console warning/error 为空；验收结束已 `viewport.reset()` 并关闭标签。09 完整回归最终 `435 passed in 243.14s (0:04:03)`。
- 仍缺：真实费用 receipt、代理 cache 命中/策略、远端真实 429/504、正式用户带素材 ProductionRun 副本回执和真实 AA 安装。`max_tokens=65536` 仅是官方最大输出与当前代理接受值的配置证据，不扩展为费用或缓存证据。
- 隔离安装补充：使用临时 8917 服务并将 `HALOCUE_AA_DATA` 指向新建的 `D:\Temp\halocue-aa-install-20260819`，复用同一已编译 Run 完成真实安装回执。`state=installed`、项目 `真实 Provider 纵切（一次性测试） - v1`、`installed_build_id=build-734bb18d26c0`；`.aap` 18,360 bytes，SHA-256 `FC5A5C8798F1614F51C85D423726DA0D363FD8286874C67D3E8D934D70E8B07B`，项目目录和 saves 目录均生成。安装后停止 8917 并删除临时目录；正式 8910 与真实 AA 工作区未写入。此前“真实 AA 安装”缺口因此收窄为“正式用户真实工作区安装尚未执行”。

## 2026-08-19 首次使用连续 Browser 纵切

- 在隔离写作/制作数据目录启动 10 集成入口 `8918`，验证空状态到新建作品的完整路径；临时服务和目录已清理，正式 `8910` 未写入。
- `390x844` 空状态只有一个主操作“开始一个新故事”，页面 `overflowX=0`；点击后新建表单底部“建立作品”按钮在视口内完整可见，表单无内部滚动溢出。
- 取消表单后焦点实际回到“开始一个新故事”；重新填写想法和作品名并提交后，创建了 Work、默认 1 章和创作主对话，下一步只显示“开始讨论作品方向”，状态为 `0 / 5 阶段完成`，没有静默建立正式方向或正文。
- 创建后的手机 Composer 与底部导航可见；`1440x900` 创建后工作面 `overflowX=0`，Console warning/error 为 `[]`。Browser 结束前执行 `viewport.reset()` 并关闭标签。
- 一次填充调用因 aria-label 与可见标签组合文本不完全一致而失败，改用页面实际 placeholder 后成功；一次隔离目录清理命令被执行器安全解析拒绝，改用已知 PID、端口核对和显式临时目录删除完成清理。
- 首次使用目标的连续点击证据已补齐；仍需继续补真实费用 receipt、代理 cache 命中/策略、正式用户带素材 ProductionRun 回执、远端真实 429/504 和正式 AA 工作区安装证据。
- 收尾健康检查首次发现正式 `8910` 进程已退出而拒绝连接；读取启动日志未见应用异常，按根 10 启动命令重新拉起后 `/api/v1/health` 返回 `200`，当前只监听 `8910`，临时端口均无监听。该服务恢复事实已记录，不把中途拒绝连接写成产品通过。
- 收尾完整回归重新执行并等待最终汇总：09 `435 passed in 239.27s (0:03:59)`，10 集成 `8 passed in 104.92s (0:01:44)`；回归后正式 `8910` 仍 HTTP `200`，没有 pytest 或临时 Browser/服务端口残留。
- 凭据泄漏扫描第一次遍历历史 pytest 目录时遇到 Windows 访问拒绝，改为只扫描 09/10 的源码、静态资源、文档和 `CONTEXT.md`，未发现用户提供的 API Key 字符串；密钥未写入代码或审计记录。

## 2026-08-19 正式场景素材追溯与交付证据复核

- 正式统一入口 `http://127.0.0.1:8910/` 当前为根 `10-HaloCue-1.0-Integrated` build `halocue-integrated/1.0.0+20260819.7`；写作健康 HTTP `200`，Provider 为真实 `gemini-3.7-flash (openai)`，`can_call_model=true`、`is_simulation=false`、`model-config-4`、`max_tokens=65536`。当前只监听正式 `8910`，未修改 `08-HaloCue-1.0/`。
- 在正式数据的场景 `scene-0235cbef3cf8` 通过 Browser 展开素材详情，页面同时显示全局原件 `00000-1392481605`、原件版本 `catalog:557fea7aaf34`、原件 Hash `121522699`（`aa_resource_hash`）、ProductionRun 任务副本 `copy-302f53732d4b` 及副本 Hash `121522699`。该展示证明原件身份、版本、Hash 与任务副本回执在写作场景面可追溯，没有把空 `production_copy` 冒充完成。
- Browser 实际复验 `1440x900` 与 `390x844`：素材详情、当前正文、`与本场 Agent 讨论`、`检查本场`、Composer 和移动底部导航可达；页面 `overflowX=0`，工作区纵向滚动正常，Console warning/error 均为空。手机展开追溯后仍显示副本 ID/Hash，结束已执行 `viewport.reset()`。
- 本轮没有再次触发模型请求，也没有采纳/退回正式候选；既有真实 Agent 运行仍保持 Proposal-only，当前正式正文基准为 `revision-293c472616cb`。真实费用 receipt、代理 cache 命中/策略、远端真实 429/504、正式用户 AA 工作区持久安装仍是独立证据缺口；usage 不等于费用，`max_tokens=65536` 不扩展为代理计费或缓存保证。

## 2026-08-19 Provider 文案边界修复与最终回归

- 复现了备用场景 Inspector 在真实 Provider 下仍硬编码“Fake Provider / 真实模型尚未接入”的事实边界错误。最小修复位于 `web/app.js`：新增 `providerDisclosure()`，所有备用 Inspector 分支按运行时 `/capabilities` 的 `is_simulation` 与 `display_name` 披露 Provider；未配置外部模型时才显示离线 Fake 分支，不再把真实 Provider 写成未接入。
- 定向合同与 HTTP 回归 `51 passed in 10.21s`，`node --check web/app.js`、`node --check web/writing-workbench.js`、Python `compileall` 通过。共享前端修改后的最终完整回归：09 `435 passed in 253.22s (0:04:13)`；10 集成 `8 passed in 125.28s (0:02:05)`。
- 内置 Browser 复验正式 `8910` 场景页：桌面 `1440x900` 与手机 `390x844` 均 `overflowX=0`，Provider 顶栏显示 `gemini-3.7-flash · 已配置`，旧 Fake 文案未出现在当前真实运行面；手机底部导航可见，Console warning/error 为空。结束执行 `viewport.reset()` 并清理标签。

## 2026-08-19 真实 3.7 讨论回合与章节运行证据披露

- 正式 `8910` 在 `model-config-6` 下完成一次只读场景讨论：AgentRun `agent-7ea9c037a51d`，Provider `gemini-3.7-flash (openai)`，usage `15,830 input / 202 output`，返回公开中文写作建议，`ready_for_proposal=false`，没有创建新的 Proposal、Revision 或正文写回。旧失败回合继续保留为失败轨迹，没有被覆盖成成功。
- 章节 Agent 面刷新后实际显示该公开回复和 `工具调用 · 2 项` 折叠轨迹；现有待审候选仍明确显示 `proposal-283fc2fa4b72` 的历史生成时模型 `gemini-3-flash (openai)`，没有把当前顶部的 `gemini-3.7-flash` 冒充成旧候选的生成模型。
- 最小 UI 修复位于 `web/app.js` 的 `sceneProposalRuntimeMarkup` 与 `web/styles.css`：候选运行证据现在显式标注“生成时模型”，并显示 `缓存未报告` / `费用未报告`（有真实数值时才显示估算）。静态版本更新为 `app.js?v=20260819-37`（随后又完成历史回合折叠）。
- 定向 HTTP/UI 回归 `44 passed`，`node --check web/app.js` 与 `web/writing-workbench.js` 通过。内置 Browser 实测 `1920x1080`、`1440x900`、`1366x768`、`390x844`：候选运行证据、逐项 Current/Candidate、字符级删除/新增高亮、复选框、应用/退回入口均可达；四断点页面横向溢出为 0，Console warning/error 为空，结束已执行 `viewport.reset()` 并清理标签。
- 本轮没有采纳或退回既有 Proposal，没有修改 08；真实费用 receipt、代理 cache 命中/策略、远端真实 429/504 和正式用户 AA 工作区安装仍是证据缺口。
- 收尾完整回归最终汇总：09 `437 passed in 238.35s (0:03:58)`；10 集成 `8 passed in 110.75s (0:01:50)`。Python compileall、JS 语法检查通过；正式 `8910` 健康 HTTP `200`，仅监听 `8910`，Provider 仍为真实 `gemini-3.7-flash` / `can_call_model=true` / `is_simulation=false`，Dispatcher running 且无 last error。

## 2026-08-19 场景 Agent 历史回合可读性

- 复现章节 Agent 右侧面板在历史回合不超过 10 条时直接铺开多次失败记录，最新公开回复和正文候选被推到下方的可读性问题。最小修复位于 `web/app.js`：场景对话可见窗口从最近 10 条收紧为最近 6 条，更早回合仍通过“查看较早对话”保留，未删除任何运行轨迹；静态版本更新为 `app.js?v=20260819-37`。
- 定向 HTTP/UI 回归 `51 passed`，`node --check web/app.js` 通过。Browser `1440x900` 实际看到最新真实 3.7 公开回复和“查看正文候选”优先出现，旧回合折叠；`390x844` 主写作面仍显示 Composer、正文/Agent/审查切换和移动底部导航，Console warning/error 为空，结束已执行 `viewport.reset()`。
- 静态资源变更后的最终回归重新等待完整汇总：09 `437 passed in 264.12s (0:04:24)`；10 集成 `8 passed in 226.26s (0:03:46)`。正式 `8910` 收尾 HTTP `200`，唯一监听端口为 `8910`，manifest build `halocue-integrated/1.0.0+20260819.7`。

## 2026-08-19 自然语言直达创作纵切

- `09-HaloCue-1.0-Writing` 新增统一 Intent 入口：`POST /api/v1/intent`、`GET /api/v1/intent-plans/{plan_id}`、`POST /api/v1/intent-plans/{plan_id}:confirm`，并以 SQLite `intent_plans` 保存原始消息、目标 Work/Chapter/Scene、读取范围、动作、风险、确认状态、AgentRun 和幂等键。低风险请求复用现有 Conversation Agent；高风险请求仍停在确认边界，不绕过 Proposal、Revision、Gate 或发布。
- 隔离空数据纵切实际创建 `未命名作品`、第一卷、第一章、场景 `场景 01 · 待理解` 和作品主对话。Fake Provider 明确为 `can_call_model=false` / `local-rules`，运行终态为 `waiting_user`；`read_work_context` 与讨论运行有真实 ToolCall/AgentRun 记录，但没有正式正文、Revision 或 ScriptRelease 写回。
- Intent 动作状态不再由前端猜测：后端按 AgentRun 与 `read_work_context` ToolCall 投影 `context.read`、`agent.discuss` 的 `running/completed/failed`，失败时返回固定输入引用和重试 AgentRun 的 recovery 信息；幂等重放、查询和确认均返回同一投影。隔离复验低风险三个动作均为 `completed`，高风险“覆盖正式正文并发布这一章”保持 `awaiting_confirmation`，未点击确认。
- 空状态保留单一自然语言 Composer、附件入口和“帮我说清楚”选择；表单现在在每次空状态渲染后直接绑定到当前节点，静态版本为 `app.js?v=20260819-40`。内置 Browser 能确认节点已绑定并能聚焦按钮，但本轮对“帮我说清楚”和空状态 submit 的 Browser click/press 未观察到 DOM 变化，Console 也无错误；因此连续点击仍记录为 Browser/Web Control 证据缺口。API 纵切和绑定合同通过，不把它们替代成按钮点击已验收。
- 隔离 Browser 在 `390x844` 与 `1440x900` 实际显示低风险“已交给创作导演”和高风险“等待你的确认”计划卡，Composer、手机底部导航可见，横向溢出均为 `0`，Console warning/error 为 `[]`。临时 `8921` 服务、数据目录和标签均已清理，结束执行 `viewport.reset()`。
- 正式统一入口 `8910` 只读兼容复验加载 `app.js?v=20260819-40`：桌面与手机横向溢出均为 `0`，Composer 可聚焦，手机底部导航可见，Console warning/error 为 `[]`；既有真实 `gemini-3.7-flash (openai)`、失败恢复卡、待审 `scene_script` Proposal、逐项 Current/Candidate、字符级 Diff、应用/退回入口均未回归。没有采纳或退回正式候选。
- 最终回归与语法检查：09 `443 passed in 240.49s (0:04:00)`；10 集成 `8 passed in 105.11s (0:01:45)`；Python `compileall`、`node --check web/app.js`、`node --check web/writing-workbench.js`、`node --check static/integration-shell.js` 通过。正式服务重启第一次因后台启动遗漏 `PYTHONPATH` 未恢复，读取启动契约后以正确环境恢复；收尾唯一监听 `8910`，健康 HTTP `200`，Provider 为真实 `gemini-3.7-flash`、`can_call_model=true`、`is_simulation=false`，Dispatcher running 且无 last error。
- 本切片未修改 `08-HaloCue-1.0`，也未修改 `10-HaloCue-1.0-Integrated` 源码。仍未完成或缺少证据：自然语言入口使用真实 Provider 的全新端到端运行、附件实际上传纵切、“帮我说清楚”连续 Browser 点击、用户确认高风险计划后的安全继续、真实费用 receipt、代理 cache 命中/策略、远端真实 429/504、正式用户 AA 工作区持久安装。现有真实模型历史运行不能冒充本次自然语言入口已完成真实模型验收。

## 2026-08-19 自然语言入口真实 Provider 小规模纵切

- 在隔离 `8922` 数据目录中只复制正式模型公开配置和 DPAPI 密钥文件，健康接口确认真实 `gemini-3.7-flash (openai)`、`can_call_model=true`、`is_simulation=false`、Dispatcher running。未把密钥内容打印或写入源码/审计，纵切后隔离数据、日志和 DPAPI 副本均删除。
- 第一条安全约束“不要覆盖正式正文，也不要发布”被旧关键词扫描误判为高风险，计划停在 `awaiting_confirmation` 且没有 AgentRun；没有将保护性误停写成成功。根因是 `_intent_risk` 不理解中文否定语境，现已忽略紧邻危险词的“不/不要/不会/未/无需/无须/勿/别”，并新增回归。
- 等价低风险请求完成真实 Intent -> Conversation Agent 纵切：计划 `intent-09f5e4c26e62`，AgentRun `agent-a56662d8ef3c`，Provider `gemini-3.7-flash (openai)`，usage `23,910 input / 416 output`，`cache_read_tokens=0`，`estimated_cost=null`。运行完成且没有 failure、Proposal、Revision 或场景正文修订，Work 仅因可恢复容器/对话记录升到版本 3。
- 真实 Provider 返回的终态为 `completed`，此前 Intent 动作投影只把 `waiting_user/succeeded` 视为成功，导致计划动作仍显示 `planned/running`；已把 `completed` 纳入成功终态。定向自然语言回归 `7 passed`。
- 最终完整回归与语法检查：09 `444 passed in 255.32s (0:04:15)`；10 集成 `8 passed in 115.05s (0:01:55)`；Python `compileall` 和 JS 语法检查通过。正式 `8910` 已重启加载修复，健康 HTTP `200`，唯一监听 PID `41800`，Provider 为真实 `gemini-3.7-flash`，Dispatcher running 且无 last error。
- 证据边界：本纵切证明自然语言入口可以调用真实 Provider 并保存真实 usage，但没有费用 receipt、缓存命中、Proposal/Revision 写回、附件上传、高风险确认后继续、远端真实 429/504 或正式 AA 安装证据。`cache_read_tokens=0` 不等于代理缓存策略已验收，`estimated_cost=null` 不得写成零费用。

## 2026-08-19 作品规划到逐场写作跳转

- 复现了自然语言入口只创建单个占位章节/场景、完成后仍停留在作品对话的问题。最小修复位于 `service.py` 与 `web/app.js`：Intent 目标现在持久保存 `chapter_id/chapter_title/scene_id/scene_title`；请求“第一章叫 X、第一幕叫 Y”时只更新占位容器；请求“第一章第二幕”时复用已有稳定场景 ID，不重复创建。已有正式结构不会被自然语言静默改名。
- 每个可定位 Intent 计划现在显示“目标：章节 · 场景”和“去写这一幕”。点击后保存当前 `writing-target`、选中 scene、进入逐场写作（若工作流 Gate 尚未开放，则明确进入章节结构页），章节树、章节下拉、场景按钮等手工路径全部保留。静态资源更新为 `app.js?v=20260819-41`。
- 新增 3 项 Intent 结构/导航合同：复用已规划第二幕、目标投影持久化、自然语言设置占位章节/场景标题；自然语言定向回归现为 `10 passed`，HTTP/静态资源合同同步更新。当前尚未用 Browser 点击真实“去写这一幕”按钮；只读 Browser 仍需补充该跳转的连续点击证据。
- 仍未完成或无证据：完整结构 Proposal 自动采纳后的自然语言连续跳转、附件实际上传、`帮我说清楚` 连续点击、高风险确认后继续、真实费用 receipt、代理 cache 策略/命中、远端 429/504 和正式用户 AA 工作区安装。不存在第二套状态机；手工结构/写作入口仍是同一 Work/Chapter/Scene 数据。

## 2026-08-19 多幕规划与目标场景导航复核

- 隔离 Intent 请求“第一章叫废弃车站，第一幕叫抵达与等待，第二幕叫广播响起，先开始写第二幕”最初只创建第一幕并错误定位第一幕；该结果未写成成功。根因是服务只解析首个幕声明。`service.py` 现在提取同一消息中的全部显式幕标题，并把“开始/继续写第 N 幕”作为目标；低风险占位场景可自动建立，已有场景仍按稳定 ID 复用，正式结构和正文不被静默覆盖。
- 隔离 API 复验返回两幕 `抵达与等待 | 广播响起`，目标为 `广播响起`。新增回归覆盖多幕创建、显式写作目标、稳定目标投影和手工场景备用入口；定向最终 `13 passed`，完整 09 最终 `449 passed in 259.13s (0:04:19)`，Python/JS 语法检查通过。
- Browser 在隔离 `8921` 确认计划卡显示目标 `废弃车站 · 广播响起`，写作结构页真实显示两幕、第二幕稳定 ID 和 Gate 阻塞说明，Console warning/error 为空。直接写作 URL 可恢复到目标章节/场景，手工章节树继续保留。
- “去写这一幕”的连续 Browser 点击仍是明确证据缺口：当前内置 Browser/Web Control 点击会被既有多层捕获路由消费，DOM/URL 未变化；已尝试直接绑定、捕获阶段处理、内部链接和复用 `data-scene` 路由，均未在该控制面得到连续点击结果。没有把静态属性、API 目标或直接 URL 恢复冒充点击已验收。临时服务和标签已停止，viewport 已 reset。
- 本切片没有修改 `08-HaloCue-1.0` 或 `10-HaloCue-1.0-Integrated` 源码。10 集成完整回归 `8 passed in 114.24s (0:01:54)`；正式 `8910` 健康，Provider 仍为真实 `gemini-3.7-flash (openai)`、`can_call_model=true`、`is_simulation=false`；本轮隔离 Browser 使用 Fake Provider，不产生真实模型、费用、缓存或正式 ProductionRun 新证据。

## 2026-08-19 自然语言作品窗口 UI 收紧与连续跳转证据

- 根据正式 `8910` 手机截图复现作品 Agent 面的三个 UI 问题：Intent 计划卡占用过高、Composer 被旧 margin 缩到 318px、桌面四块内容被旧三行网格压缩导致 Intent 卡覆盖对话。最小修复集中在 `web/writing-workbench.css`：手机计划卡改为紧凑摘要、目标行和三列动作；Composer 恢复左右各 10px、宽 370px；桌面存在 Intent 卡时使用四行网格。`web/app.js` 同时移除目标跳转的临时 debug 日志，静态样式版本更新为 `writing-workbench.css?v=20260819-21`。
- 内置 Browser 实测 `390x844`：页面宽度与 viewport 均为 390，无横向溢出；Intent 卡高度从 337px 收紧到 242px，Composer 宽 370px，顶部新建作品、移动底部导航和失败恢复卡可见。Composer textarea 实际获得焦点；点击“去写这一幕”后 URL 进入 `section=writing&stage=draft` 并带固定 `chapter_id/scene_id`，逐场写作页显示当前场景、正文/Agent/审查切换和手工“场景”入口，`overflowX=0`、Console warning/error `[]`。此前连续点击证据缺口已补齐。
- Browser `1440x900` 复现并修复桌面重叠后，Intent 卡、对话滚动区和 Composer 分属独立网格行，计算结果 `overlap=false`，页面无横向溢出。手工章节树、作品对话列表和新建作品入口均保留；没有新增第二套导航或状态机。
- 定向自然语言/HTTP 回归 `57 passed in 18.53s`，`node --check web/app.js`、`node --check web/writing-workbench.js` 通过；最终完整回归 09 `450 passed in 256.92s (0:04:16)`，10 集成 `8 passed in 116.95s (0:01:56)`。正式 `8910` 由 PID `42364` 监听，健康 HTTP `200`，Provider 为真实 `gemini-3.7-flash (openai)`、`can_call_model=true`、`is_simulation=false`，Dispatcher running 且无 last error。
- 本切片没有触发新的模型调用、采纳 Proposal、建立 Revision、冻结 ScriptRelease、创建 ProductionRun 或安装 AA；没有修改 `08-HaloCue-1.0` 或 `10-HaloCue-1.0-Integrated` 源码。真实费用 receipt、代理 cache 命中/策略、远端真实 429/504、附件实际上传、高风险 Intent 确认后继续和正式用户 AA 工作区安装仍是独立证据缺口。

## 2026-08-19 集成深链路由修复与服务重启复验

- 复现根因：直接打开 `section=writing&stage=draft&chapter_id=...&scene_id=...` 时，09 初始 Work 尚未完成加载，10 集成壳的旧 DOMContentLoaded 顶层“写作”导航回放把 `stage=draft` 覆盖成 `structure`。最小修复在 `09-HaloCue-1.0-Writing/web/writing-workbench.js`、`web/app.js` 与 `10-HaloCue-1.0-Integrated/static/integration-shell.js`：串行化初始 Work/路由应用，统一 `applyInitialRoute()`，并让 09 写作路由拥有 works/writing/references/tasks 深链；10 build 更新为 `halocue-integrated/1.0.0+20260819.8`。
- 相关合同与回归：09 定向 HTTP/Intent `57 passed`；10 网关 `8 passed`；完整回归最终 09 `450 passed in 248.14s (0:04:08)`、10 `8 passed in 109.65s (0:01:50)`；`node --check web/app.js`、`node --check web/writing-workbench.js`、`node --check static/integration-shell.js` 通过。
- 正式服务按根启动契约重启：`/api/v1/health` HTTP `200`，Provider 为 `gemini-3.7-flash (openai)`、`can_call_model=true`、`is_simulation=false`，Dispatcher running 且 `last_error=null`；`/integration/manifest` 返回 build `.8`，唯一监听端口为 `127.0.0.1:8910`（PID `4512`）。一次组合重启命令被执行器策略拒绝，拆分停止/启动/健康检查后恢复，未把调用失败写成产品通过。
- 内置 Browser 最终复验：`1440x900` 直接 draft 深链 URL 保持 `stage=draft`，场景工作区存在；`390x844` 正文/Agent/审查三 tab 可切换，Composer 与手机底部导航可见。两视口 `overflowX=0`，Console warning/error 均为 `[]`，结束执行 `viewport.reset()`。本切片没有触发新模型调用、采纳 Proposal、建立 Revision、冻结 ScriptRelease、创建 ProductionRun 或安装 AA。
- 仍未完成/无新增证据：真实费用 receipt、代理 cache 命中/策略、远端真实 429/504、附件上传、高风险 Intent 确认后继续、正式用户 AA 工作区持久安装；真实模型与历史 Proposal/Diff 证据继续按各自生成时运行记录披露。

## 2026-08-19 隔离 Composer 附件 API 纵切

- 在隔离 10 集成服务 `8923` 与全新数据目录中建立 Work/创作主对话，Fake Provider 明确为 `can_call_model=false`。通过现有附件合同上传 `README.md`：生成 `attachment-e4cf4c9ed1d8`，媒体类型 `text/markdown`，Hash `sha256:8739fb7ed91ed84be7c55859086f674f2dece11a159e2a2ed365ff8845b38ebd`，文档索引 `document-chunks/1.0` 共 7 块，初始状态 `staged`。
- 以固定 `expected_thread_version` 将该附件挂入一条消息后，回读确认线程版本递增、附件状态为 `attached`、`message_id` 已绑定，用户消息携带 1 个附件；Fake AgentRun 终态 `waiting_user`，只执行 `load_workflow_template` 与 `read_work_context`，没有正式正文或 Revision 写回。
- Browser 只读检查确认 Composer 的“添加附件 -> 上传文档”菜单、文件类型边界和可见入口存在；内置文件选择器两次（隐藏 input、可见菜单）均在 `filechooser` 控制面超时并导致内核重置。没有把 API 纵切替代成 Browser 文件选择成功，故“连续 UI 上传”仍是明确证据缺口。隔离服务、数据、日志和标签已清理，正式 `8910` 未写入。
- 本纵切没有新模型调用、费用/cache、Proposal 采纳、Revision、ScriptRelease、ProductionRun 或 AA 安装证据；附件实际 UI 上传和带附件真实 Provider 回合仍待后续在可用文件选择器控制面复验。

## 2026-08-19 高风险 Intent 确认后安全继续

- 在临时 `WritingService` 数据目录中复现高风险请求，确认前计划状态为 `awaiting_confirmation`；调用现有 `confirm_intent(..., {confirmed: true})` 后，计划重新进入同一 Conversation Agent，终态 `waiting_user`。
- 隔离 Work 回读确认仅有 1 条 AgentRun，Proposal `0`、Revision `0`、Release `0`，没有正文或发布写回；这证明确认动作没有绕过 `Proposal -> 用户决定 -> Revision/Gate` 边界。临时 SQLite 数据随后清理，正式 8910 未写入。
- 本纵切仍使用 Fake Provider，不产生真实模型、usage、费用或 cache 证据；正式用户高风险确认后的 Browser 连续点击和真实 Provider 回合仍需后续验收。
- 2026-08-19：当前正式作品真实复现了“Intent 计划目标与写作位置”的持久化缺口：`set_writing_target` 后端支持 `anchor_scene_id`，但前端原来只保存章节；刷新/返回可能回到本章第一场。修复集中在 `web/app.js`、`web/writing-workbench.js`、`web/writing-workbench.css` 与 `web/index.html`：新增串行 `persistWritingTarget(chapter_id, anchor_scene_id)`，计划卡和手工场景入口统一保存稳定场景锚点，加载时优先恢复锚点；目标场景被删除时显示“目标已变化”，标题变化时仍按稳定 ID 定位；正文 Gate 未开放时手工场景入口只聚焦阻塞原因，不绕过 Gate。静态版本更新为 `app.js?v=20260819-54`、`writing-workbench.js?v=20260819-25`、`writing-workbench.css?v=20260819-22`。
- 正式 Browser 连续验收：点击现有计划卡“去写这一幕”后进入 `stage=draft&chapter_id=chapter-6d652b3fb16c&scene_id=scene-0235cbef3cf8`，场景为“午后走廊的交错”；刷新后仍恢复同一 URL/场景，后端 `writing_target` 当前修订明确保存 `anchor_scene_id=scene-0235cbef3cf8`。`1440x900` 与 `390x844` 均 `overflowX=0`；手机正文/Agent/审查切换、Composer、底部导航可用；Console warning/error `[]`，已 reset viewport 并清理标签。

## 2026-08-19 增量证据（Intent 真实回合与上下文状态投影）

- 正式 `8910` 对 Work `work-583189373ff2` 执行了一次新的低风险自然语言 Intent：计划 `intent-3f213ec85485`，消息明确要求读取正式资料并只讨论、不写入正文、不采纳 Proposal、不发布。计划目标稳定指向第一章 `chapter-6d652b3fb16c` / 场景 `scene-0235cbef3cf8`，终态 `completed`；真实 AgentRun `agent-00f0dbbc823c` 使用 `gemini-3.7-flash (openai)` / `model-config-6`，usage `33,539 input / 576 output`，公开回复已进入创作主对话。
- 该回合实际调用 `search_world_bible`、`search_work_canon`、`search_character_cards`，三项均成功；没有创建新 Proposal、Revision 或正文写回，场景正文仍为 `revision-293c472616cb`，现有待审 Proposal 数量仍为 1。`cache_read_tokens=0`、`estimated_cost=null`，只记录 Provider 返回值，不把它写成缓存命中或真实费用。
- 发现并修复 `service.py::_project_intent_plan_execution` 的状态语义缺口：原逻辑只识别 `read_work_context`，真实章节 Agent 使用范围搜索工具时会把“读取已确认资料”错误留在 `planned`。现在聚合读取和范围搜索的成功/失败统一投影到 Intent action；新增 `test_intent_projection_counts_scoped_context_search_as_context_read`。
- 真实恢复尝试保留了失败边界：对旧失败 `agent-aad4a7935d30` 的第一次重试因传入会话字段错误返回 `thread_conflict`，修正为固定输入所需的 `expected_thread_version=8` 后，系统明确返回 `provider_config_changed`（快照 `model-config-5` 与当前 `model-config-6` 不一致），没有静默换模型重跑。该事实证明恢复入口会校验固定输入与 Provider 配置；仍需在同一 Provider 配置下补充一次成功的真实重试证据。
- Browser 复验正式入口在 `1440x900` 与 `390x844`：页面横向溢出均为 `0`，Composer、“去写这一幕”、桌面主导航和手机底部导航均可见，手机 Composer 宽约 `369px`、底部导航高度 `54px` 且固定可见，Console warning/error 均为空；结束已调用 `viewport.reset()` 并关闭临时标签。
- 本轮修改集中在 `09-HaloCue-1.0-Writing/src/halocue_writing/service.py` 与 `tests/test_natural_language_intent.py`，未修改 `08-HaloCue-1.0/` 或 `10-HaloCue-1.0-Integrated/` 源码。完整回归最终：09 `452 passed in 256.63s (0:04:16)`；10 集成 `8 passed in 109.39s (0:01:49)`；定向自然语言回归 `15 passed`，Python 编译和 JS 语法检查保持通过。
- 当前仍未完成：同一 Provider 配置下的真实重试成功回合、附件连续 Browser 文件选择、远端真实 429/504、代理 cache 策略/命中、真实费用 receipt、正式用户 ProductionRun 副本与正式 AA 工作区安装；不把本轮真实 Intent 成功或 Fake/隔离证据扩写成这些能力已验收。
- 新增目标锚点与过期目标静态/服务合同，定向自然语言/HTTP `58 passed in 16.08s`；JS `node --check` 通过。共享前端修改后的完整回归最终 09 `451 passed in 251.95s (0:04:11)`、10 集成 `8 passed in 110.11s (0:01:50)`。正式服务健康 HTTP `200`，Provider 仍为真实 `gemini-3.7-flash (openai)`、Dispatcher running、build `.8`，唯一监听 `8910`。
- 本切片没有新模型调用、Proposal 采纳、Revision、ScriptRelease、ProductionRun 或 AA 安装证据；费用/cache、远端 429/504、附件 UI 原生文件选择器、正式高风险确认真实回合和正式 AA 工作区安装仍是证据缺口。

## 2026-08-19 讨论-only Intent 计划语义收紧

- 复现正式作品页的可见语义问题：明确要求“只讨论、不写正文、不生成候选”的 Intent 已正确完成且没有 Proposal/Revision 写回，但计划卡仍显示“正式产物仍会以候选形式出现”，容易误导用户。修复 `web/app.js` 的 `intentPlansMarkup()`：讨论-only 计划显示“已完成，可继续讨论”、目标动作显示“查看这一幕”，并明确“本轮只读取资料并讨论，未生成正文候选，也未写入正式产物”；普通写作计划继续显示“去写这一幕”和候选提示。
- 新增静态 UI 合同回归 `test_intent_plan_ui_distinguishes_read_only_discussion`；`app.js` 静态版本升级为 `app.js?v=20260819-55`。定向 Intent 回归 `17 passed`，`node --check web/app.js`、Python `compileall` 通过。
- 正式 `8910` Browser 复验作品 Agent 页：讨论-only 卡逐卡显示只读文案和“查看这一幕”，普通卡仍显示候选文案和“去写这一幕”；Console warning/error `[]`。Edge 扩展的 `390x844` 视口控制实际页面内容为 `354x767`（工具栏占用尺寸），横向溢出按 `max(0, scrollWidth-innerWidth)` 为 `0`；Composer 填充后焦点回到消息框。内置 IAB 标签在本轮连接时返回未知句柄，已按故障流程完成重新定位/新建/清单检查，未伪造 IAB 点击证据；已执行 Edge 视口 reset。
- 最终完整回归：09 `454 passed in 252.30s (0:04:12)`；10 集成 `8 passed in 113.69s (0:01:53)`。正式健康 HTTP `200`，唯一监听 `127.0.0.1:8910`（PID `5988`），Provider `gemini-3.7-flash (openai)`、`can_call_model=true`、`is_simulation=false`、Dispatcher running、无 last error。未修改 `08-HaloCue-1.0/` 或 `10-HaloCue-1.0-Integrated/` 源码。
- 本切片没有新增真实模型调用、Proposal 采纳、Revision、ScriptRelease、ProductionRun 或 AA 安装证据；真实费用 receipt、代理 cache 命中/策略、附件连续文件选择、同 Provider 配置下失败重试成功、远端 429/504 和正式 AA 工作区安装仍是证据缺口。

## 2026-08-19 场景 Agent 重试 Provider 固定

- 复查恢复代码发现对话重试会校验失败输入快照中的 Provider 配置，但场景候选/正文生成重试路径缺少同一检查，存在配置切换后静默重跑风险。`service.py::_retry_scene_agent_run` 现在读取 `provider_runtime` 并调用 `_capture_provider()`；当前模型配置变化时统一返回 `provider_config_changed`，不创建新候选。
- 新增 `test_scene_retry_rejects_provider_configuration_change`，定向 Provider pinning/场景失败恢复回归 `8 passed`；完整最终回归 09 `455 passed in 255.82s (0:04:15)`、10 `8 passed in 110.45s (0:01:50)`，Python compileall 和 JS 语法检查通过。
- 正式 Work 的旧失败运行仍绑定 `model-config-4/5`，当前健康服务为 `model-config-6`；本轮没有用新模型替旧失败运行重试，边界保持明确。正式 8910 健康 HTTP `200`，唯一监听 `127.0.0.1:8910`（PID `5988`），Provider `gemini-3.7-flash (openai)`、`can_call_model=true`、`is_simulation=false`，Dispatcher running 且无 last error。
- 未修改 `08-HaloCue-1.0/` 或 `10-HaloCue-1.0-Integrated/` 源码。真实同配置失败后的成功重试、真实费用 receipt、代理 cache 命中/策略、附件连续 Browser 文件选择、远端 429/504 和正式 AA 工作区安装仍为证据缺口。

## 2026-08-19 收尾（Intent 状态投影修复）

- 上述真实 Intent 回合和恢复边界记录以本节为阶段收尾；其后的最终回归已更新为 09 `455 passed`、10 `8 passed`。正式入口健康且只有 `8910` 监听；其余外部凭据、费用、缓存、附件文件选择器、同配置成功重试和正式 AA 安装继续保持证据缺口。
- 2026-08-19：复现并修复正式作品页“新建作品”窗口在移动端失去窗口表面的问题。根因是 `#workDialog` 为自定义 `div`，旧样式使用 `inset: 0` 使其铺满视口，表单背景与正文混在一起；`web/shell.css` 现改为真正的居中弹层（固定宽度上限、边框、背景、阴影、滚动表单和移动端内边距），`web/index.html` 资源版本更新为 `shell.css?v=20260819-19`，并补强静态回归合同。
- 定向窗口/路由合同 `3 passed`；最终完整回归 09 `456 passed in 241.82s (0:04:01)`、10 集成 `8 passed in 100.18s (0:01:40)`；`python -m compileall -q src`、`node --check web/app.js`、`node --check web/writing-workbench.js` 通过。一次定向测试命令因把函数名当路径而未执行，修正参数后 `3 passed`，未把调用错误写成产品结果。
- 正式 `8910` 健康 HTTP `200`，唯一监听 `127.0.0.1:8910`（PID `5988`），Provider 为真实 `gemini-3.7-flash (openai)`、`can_call_model=true`、`is_simulation=false`，Dispatcher running 且 `last_error=null`。Browser 实测桌面 `1440x900` 弹层 `560x601` 居中，手机 `390x844` 弹层 `370x620` 居中；两端横向溢出均为 `0`，想法输入框获得焦点，Console warning/error 均为 `[]`，结束已 `viewport.reset()` 并清理临时标签。
- 本切片只修改 `09-HaloCue-1.0-Writing/web/shell.css`、`web/index.html`、`tests/test_http_api.py`；未修改 `08-HaloCue-1.0/` 或 `10-HaloCue-1.0-Integrated/` 源码。真实费用 receipt、代理 cache 命中/策略、附件连续文件选择、同 Provider 配置下失败重试成功、远端真实 429/504、正式用户 ProductionRun 素材副本和正式 AA 工作区编译/安装仍是证据缺口。

## 2026-08-19 待审场景候选首屏 Diff 入口

- 复现正式 `8910` 场景 `scene-0235cbef3cf8` 存在待审 `scene_script` Proposal 时，页面下方已有完整 Current/Candidate、逐块复选框和文字级删除/新增，但“当前下一步”仍被 `writing-workbench.js` 后置装饰覆盖为“本场上下文已准备”，首屏没有直接聚焦 Diff 的主操作。
- 最小修复集中在 `09-HaloCue-1.0-Writing/web/writing-workbench.js`：检测当前场景 pending Proposal 后，首屏改显示“有一份候选等待决定”和“逐项查看候选与 Diff；正式正文仍未改变”，主按钮为“查看候选与 Diff”；点击会滚动到 `[data-scene-diff-root]`、聚焦第一项 checkbox，保留“检查本场”次级入口。静态资源更新为 `writing-workbench.js?v=20260819-27`，新增 HTTP/UI 合同回归。
- 定向验证：`node --check web/writing-workbench.js`、`tests/test_http_api.py` `45 passed`、自然语言/阶段合同 `25 passed`。正式 Browser `1440x900` 首屏真实显示新主操作，点击后第一项 Diff checkbox 获得焦点；`390x844` 单列候选与底部导航可见，点击后同样聚焦第一项，`scrollWidth=clientWidth=390`；两视口 Console warning/error 均为 `[]`。
- 本轮完整回归最终：09 `457 passed in 243.89s (0:04:03)`，10 集成 `8 passed in 102.78s (0:01:42)`；`node --check web/app.js`、`node --check web/writing-workbench.js`、`python -m compileall -q src` 通过。正式服务 HTTP `200`，唯一监听 `127.0.0.1:8910`（PID `5988`），Provider 仍为真实 `gemini-3.7-flash (openai)`，Dispatcher running、无 last error。
- 本切片没有采纳 Proposal、建立新 Revision、冻结 ScriptRelease、创建 ProductionRun 或安装 AA，也没有新增真实费用/cache、附件文件选择、同 Provider 成功重试、远端 429/504 或正式制作副本证据；未修改 `08-HaloCue-1.0/` 或 `10-HaloCue-1.0-Integrated/` 源码。结束前已执行 Browser viewport reset 并关闭临时标签。

## 2026-08-19 Intent 目标与执行状态一致性

- 复查正式作品发现：Intent 计划顶层已经是 `completed`，但 `result.status` 仍保留初始 `running`，消费者直接读取结果对象时会看到过时状态。`service.py::_project_intent_plan_execution` 现在同时更新 `result.status` 与 `result.run_status`，不改变计划顶层状态或任何正式产物。
- 失效目标恢复入口已补齐：计划引用的场景不再存在时，作品 Agent 卡显示“目标已变化”，并提供“打开章节结构”按钮；用户可以保留手工结构入口重新选择稳定 Scene ID，不必重新发送原请求。静态资源更新为 `app.js?v=20260819-56`，新增状态投影和失效目标合同测试。
- 定向 Intent/HTTP 回归 `64 passed`，`node --check web/app.js`、`node --check web/writing-workbench.js`、`python -m compileall -q src` 通过。完整最终回归：09 `458 passed in 272.25s (0:04:32)`，10 集成 `8 passed in 145.78s (0:02:25)`。
- 正式 Browser `1440x900` 实测目标卡仍显示讨论-only 的“查看这一幕”和普通写作的“去写这一幕”；点击普通目标进入固定 `section=writing&stage=draft&chapter_id=chapter-6d652b3fb16c&scene_id=scene-0235cbef3cf8`。`390x844` 刷新后正文/Agent/审查、底部导航和待审 Diff 主入口可见，点击 Diff 聚焦第一项 checkbox；两视口横向溢出 `0`，Console warning/error `[]`。失效分支只以静态合同验证，未篡改正式用户结构制造场景删除证据。
- 正式服务 HTTP `200`，唯一监听 `127.0.0.1:8910`（PID `5988`），Provider 仍为真实 `gemini-3.7-flash (openai)`，Dispatcher running、无 last error。未修改 `08-HaloCue-1.0/` 或 `10-HaloCue-1.0-Integrated/` 源码；真实费用/cache、附件连续文件选择、同 Provider 真实成功重试、远端 429/504、正式 ProductionRun 副本和 AA 编译/安装仍为证据缺口。Browser 已 reset viewport 并关闭临时标签。

## 2026-08-19 Intent 计划卡与移动 Composer 不遮挡

- 复现正式作品 Agent 页 `390x844` 的真实 UI 问题：三个已完成 Intent 计划连续展开，列表高度超过工作区；固定底部 Composer 覆盖第三张计划卡的正文和操作区。根因是移动端历史计划没有折叠。
- `web/app.js` 的 `intentPlansMarkup()` 现在优先展示当前运行/待确认计划；已完成或已停止的较早计划收进“查看较早对话”历史区，仍保留完整卡片、目标和重试/确认动作。`web/writing-workbench.css` 增加历史区可展开视觉层级；静态资源更新为 `writing-workbench.css?v=20260819-23`。
- 定向自然语言/HTTP 回归 `64 passed`；完整 09 最终 `458 passed in 257.07s (0:04:17)`；`node --check web/app.js`、`node --check web/writing-workbench.js`、`python -m compileall -q src` 通过。
- 内置 Browser 实测 `1920x1080`、`1440x900`、`1366x768`、`390x844`：四种视口 `overflowX=0`；手机主计划卡底部 `384.57px`、Composer 起点 `668.71px`，无相交；历史区默认折叠且可展开。桌面与手机 Composer 均可获得焦点，Console warning/error 均为 `[]`，结束已 `viewport.reset()`。
- 本切片没有创建/采纳 Proposal、建立 Revision、冻结 ScriptRelease、创建 ProductionRun 或安装 AA；未修改 `08-HaloCue-1.0/` 或 `10-HaloCue-1.0-Integrated/` 源码。Provider 仍为真实 `gemini-3.7-flash (openai)`；真实费用 receipt、代理 cache 命中/策略、附件连续文件选择、同配置真实成功重试、远端 429/504 和正式 AA 工作区安装仍是证据缺口。

## 2026-08-19 Intent 历史区展开后的移动遮挡修复

- 继续复验发现：历史区默认折叠时已不遮挡，但展开两张较早计划后仍会进入固定 Composer 区域。`web/writing-workbench.css` 在移动端为历史卡内容增加 `190px` 独立滚动上限，资源更新为 `writing-workbench.css?v=20260819-24`；旧卡仍可在滚动框内查看。
- 定向自然语言/HTTP 回归 `64 passed`；最终完整 09 回归 `458 passed in 253.90s (0:04:13)`；`node --check web/app.js`、`node --check web/writing-workbench.js`、`python -m compileall -q src` 通过。
- Browser `390x844` 折叠态主计划卡底部 `384.57px`、Composer 起点 `668.71px`；展开态历史滚动框底部 `621.24px`、内容 `scrollHeight=510/clientHeight=190`，仍不与 Composer 相交，`overflowX=0`。`1440x900` 桌面 Composer 保持正常文档流位置，`overflowX=0`；Console warning/error `[]`，结束已 `viewport.reset()`。
- 本轮未创建/采纳 Proposal、Revision、ScriptRelease、ProductionRun 或 AA 工程；未修改 08/10 源码。Provider 仍为真实 `gemini-3.7-flash (openai)`；真实费用/cache、附件连续文件选择、同配置真实重试、远端 429/504、正式制作副本和 AA 编译/安装仍是证据缺口。

## 2026-08-19 规划结构到手工章节与场景写作

- 复现真实重复入口问题：`app.js` 早期捕获处理器会截断 `writing-workbench.js` 的章节树处理器，把手工点击强制改为 `stage=structure`，且没有走稳定目标保存逻辑。删除这条重复状态机入口，统一由写作工作台处理：先保存 `chapter_id + anchor_scene_id`，再进入章节细纲；场景按钮继续进入逐场正文。
- `web/app.js` 资源更新为 `app.js?v=20260819-57`；`web/writing-workbench.js` 更新为 `writing-workbench.js?v=20260819-28`。新增手工章节锚点静态合同；定向自然语言/HTTP 回归 `65 passed`，完整 09 最终 `459 passed in 273.62s (0:04:33)`。
- 正式 Browser 实测：Intent “去写这一幕”在 `1920x1080`、`1440x900`、`1366x768`、`390x844` 均进入固定 `stage=draft&chapter_id=chapter-6d652b3fb16c&scene_id=scene-0235cbef3cf8`，场景“午后走廊的交错”可见，横向溢出为 `0`。桌面手工章节按钮从 draft 进入 `stage=structure`，刷新后仍保持同一章节 URL；手机场景抽屉按钮进入同一场景正文。相关 Console warning/error 均为 `[]`，结束已 `viewport.reset()`。
- 继续修复场景写作体验：手机 Agent 面板原 Composer 位于 `y≈1413`，必须滚过整段历史；`writing-workbench.css?v=20260819-25` 现在把移动 Agent 面板限制为视口内单列工作区，中间对话独立滚动，Composer 固定在面板底部。定向回归 `66 passed`，完整 09 最终 `460 passed in 253.17s (0:04:13)`。
- 移动场景 Agent Browser `390x844`：Composer `[523.82,756.49]`、底部导航 `[790,844]`，无相交；`1920x1080`、`1440x900`、`1366x768` 场景正文/Composer 均可见，所有视口 `overflowX=0`，Console warning/error `[]`。未采纳 Proposal、建立 Revision、冻结 ScriptRelease、创建 ProductionRun 或安装 AA；未修改 08/10 源码。真实费用/cache、附件连续文件选择、同配置真实成功重试、远端 429/504、正式制作副本和 AA 编译/安装仍是证据缺口。

## 2026-08-19 手工章节展开保留当前场景

- 复查统一章节处理器发现切换章节时无条件选第一场；在同一章节存在多幕时，展开/收起章节会把用户当前幕静默重置。`writing-workbench.js` 现在优先保留 `state.sceneId`（仅当它属于目标章节），跨章节时才选择第一场；资源版本更新为 `writing-workbench.js?v=20260819-29`。
- 新增合同断言覆盖“同章保留当前场景”；定向自然语言/HTTP `66 passed`；最终完整 09 `460 passed in 251.57s (0:04:11)`；JS/Python 语法与编译检查通过。
- 正式 Browser 最终检查保持 `390x844` 场景 URL `stage=draft/chapter_id/scene_id`、`overflowX=0`、Console warning/error `[]`，视口已 reset。当前正式作品只有一场，因此多幕保留逻辑由源代码合同验证，未篡改正式结构制造第二场。

## 2026-08-19 Intent 确认路由与移动计划卡可读性

- 复现高风险 Intent 浏览器点击后提示“接口不存在”：前端请求的正式合同是 `/api/v1/intent-plans/{plan_id}:confirm`，后端误按五段路径匹配。`src/halocue_writing/app.py` 现按四段路径解析并剥离 `:confirm` 后缀；新增 HTTP 合同覆盖确认请求返回 `202`、创建 AgentRun、离开 `awaiting_confirmation`。
- 高风险真实 Provider 连续复验：计划 `intent-1e4a3879e054` 通过修复后的 API 进入 `running`，计划 `intent-bd7ae75e2408` 由 Browser 点击“确认继续”后进入 `waiting_user`，AgentRun `agent-302c989d3477` 公开生成候选讨论；页面不再出现 404，候选保持 Proposal/正式写回边界，当前正式场景修订仍为 `revision-293c472616cb`。确认后 `user.confirm` 动作投影为 `completed`，后续候选审查仍需单独决定。
- 手机窗口修复集中在 `web/writing-workbench.css?v=20260819-26`、`web/app.js?v=20260819-58`：Intent 计划动作由三列单行省略改为可换行的两列/奇数项跨列布局，目标章节允许两行显示，确认完成后“等待确认：发布”显示为“已确认：发布”；桌面保持原有紧凑横排。Browser `1440x900` 与 `390x844` 实测横向溢出均为 `0`，手机计划卡底部 `418.73px`、底部导航从 `790px` 开始，动作标签完整可读，Console warning/error `[]`；结束已 `viewport.reset()`。
- 定向自然语言/HTTP 回归 `23 passed`；完整最终 09 `461 passed in 260.47s (0:04:20)`，10 集成最终 `8 passed in 120.85s (0:02:00)`；`node --check web/app.js`、`node --check web/writing-workbench.js`、`python -m compileall -q src` 通过。正式 `8910` HTTP `200`，PID `35116`，Provider `gemini-3.7-flash (openai)`、`can_call_model=true`、`is_simulation=false`、Dispatcher running 且无 last error。
- 未采纳候选、建立新的正式 Revision、冻结 ScriptRelease、创建正式用户 ProductionRun 或安装 AA；真实费用 receipt、代理 cache 命中/策略、附件原生文件选择连续证据、同配置失败后成功重试、远端真实 `429/504`、正式 AA 工作区持久安装仍是证据缺口。未修改 `08-HaloCue-1.0` 或 `10-HaloCue-1.0-Integrated` 源码。

## 2026-08-20 自然语言 Intent 自动进入场景 Proposal

- 复现并修复真实缺口：Intent 原来只启动作品级 Conversation Agent，用户明确“开始写某一幕”后不会继续调用场景 Agent，`proposals=[]`。`service.py` 新增持久 Dispatcher 内的 Intent 场景桥接：讨论完成后复用 `run_scene_agent` / `run_scene_rewrite_agent`，仍只生成 `scene_script` Proposal/Diff；已有 pending Proposal 不重复生成，模型取消、上下文阻塞或 Provider 失败均保留明确状态。Intent 新建场景没有手工上下文选择时，会把当前已确认人物卡、世界规则和可信参考资料固化到 Scene 合同；显式选择不被覆盖。
- `_project_intent_plan_execution` 现在从 Work 的 pending 场景 Proposal 投影 `proposal_id`、Proposal AgentRun 和 `waiting_user` 顶层状态，避免 Proposal 已生成时 Intent 卡仍显示“已完成”。新增自然语言桥接与状态投影回归。
- 正式 `8910` 真实 Provider 纵切：消息“第一章第二幕叫广播响起，先开始写第二幕：爱丽丝在废弃车站听见异常广播。”创建稳定 Scene `scene-3fe0047175da`，真实模型 `gemini-3.7-flash (openai)` 生成 `proposal-c6411d5dd9a3`，状态 `pending`，`scene_script` Diff 13 项，AgentRun `agent-0182849c5d23` 状态 `waiting_user`；当前 Work 版本 48、场景数 2，正式正文仍未写入新 Revision。该回合 usage 为 `11,653 input / 301 output`，`cache_read_tokens=0`，费用 `null`，按 Provider 未报告处理。
- 当前设置证据：Provider 配置 `model-config-6`，`max_tokens=65536`、超时 120 秒、secret source `dpapi`；这证明 HaloCue 请求上限配置为 65,536，不等同于上游模型公开最大上下文的独立证明。未把缓存、真实费用或上游 token 上限写成已验收事实。
- 定向自然语言/场景/HTTP 回归通过：自然语言 `24 passed`，场景/纵切 `45 passed`，HTTP `45 passed`；语法 `python -m compileall -q src`、`node --check web/app.js`、`node --check web/writing-workbench.js` 通过。最终完整回归：09 `463 passed in 305.35s (0:05:05)`；10 集成 `8 passed in 200.77s (0:03:20)`。
- Browser 复验：内置 Browser 重新接管正式页面，移动实际内容区 `481x898`、桌面新标签 `1280x720`；两端 `overflowX=0`、Console logs `[]`。真实第二幕页面显示“有一份候选等待决定”、主操作“查看候选与 Diff”、上下文摘要和逐项 Diff；点击主操作后第一项 checkbox 获得焦点。当前 Browser 会话未暴露 viewport capability，无法在本轮重新设置精确 `390x844`/`1440x900`，旧审计中的精确视口证据仍保留，未把 481/1280 冒充为目标视口。
- 2026-08-20：复现并修复作品 Agent 窄屏窗口的视觉缺口。`09-HaloCue-1.0-Writing/web/shell.css` 现在让移动端作品进度标题最多显示两行，主操作按钮限制最大宽度，Agent 画布/线程禁止横向溢出，固定 Composer 使用视口内 `10px` 边距；`380px` 以下进一步收窄按钮列。没有修改 Agent 状态机、路由或写入边界。
- 2026-08-20：内置 Browser 实测正式 `8910` 作品 Agent：`1920x1080`、`1440x900`、`1366x768`、`390x844` 四档视口均与请求尺寸一致，`overflowX=0`，桌面 Composer 在内容列内，手机 Composer `left=10/right=380` 且底部导航可见，Console warning/error `[]`；另以 `574x965` 复现用户截图尺寸，`overflowX=0`，结束执行 `viewport.reset()`。
- 2026-08-20：定向 HTTP/Intent/UI 回归 `69 passed in 19.14s`；`node --check web/app.js`、`node --check web/writing-workbench.js` 通过；共享 CSS 修改后的完整 09 最终回归 `463 passed in 304.31s (0:05:04)`。10 集成上一最终汇总仍为 `8 passed in 118.08s`，本轮未修改 08 或 10 源码。Provider 仍为真实 `gemini-3.7-flash (openai)`；正式场景候选 `proposal-c6411d5dd9a3` 仍 pending，真实费用 receipt、cache 命中/策略、附件原生文件选择、同 Provider 配置下失败后成功重试、远端 `429/504`、正式 ProductionRun 素材副本和 AA 工作区持久安装仍为证据缺口。
- 本轮未采纳 `proposal-c6411d5dd9a3`、未建立新的正式 Revision、未冻结 ScriptRelease、未创建正式用户 ProductionRun、未编译/安装 AA；未修改 `08-HaloCue-1.0/` 或 `10-HaloCue-1.0-Integrated/` 源码。真实费用 receipt、代理 cache 命中/策略、附件原生文件选择连续上传、同配置失败后成功重试、远端真实 `429/504`、正式 ProductionRun 素材副本和 AA 工作区持久安装仍为证据缺口。

## 2026-08-20 Intent 重试恢复与移动 Composer 安全空间

- 继续验证 Intent 场景桥接后，`service.py` 新增 `retry_intent(plan_id, payload)` 及 `POST /api/v1/intent-plans/{plan_id}:retry`。仅 `blocked/failed` 计划可重试；重试固定原始消息、`chapter_id`、`scene_id`，使用 Work 版本 CAS，不重新创建 Work/Chapter/Scene，并回写 `result.retry`、稳定目标和公开执行状态。新增 UI “重新检查并继续”入口；Proposal 归属投影只认本计划返回的 Proposal ID，不再误认同场景的其他 pending Proposal。
- 定向 Intent/HTTP 回归最终为 `78 passed in 27.79s`；Python 编译和 `node --check web/app.js` 通过。完整 09 最终 `472 passed in 335.20s (0:05:35)`；10 集成最终 `8 passed in 151.90s (0:02:31)`。
- 复现用户提供的窄屏作品 Agent 截图后发现固定 Composer 遮住“较早的待处理决定”卡片底部。`web/writing-workbench.css?v=20260820-29` 在移动端让 Works 画布纵向可滚动，并预留 `150px + safe-area` 底部空间；新增静态合同测试。浏览器 `390x844` 实测滚动到计划底部时历史卡片完整可见，Composer 与底部导航保持可用；桌面 `1440x900` 画布仍为正常内容列布局。两种视口 `overflowX=0`，Console warning/error 为 `[]`，结束已 `viewport.reset()`。
- 本轮只修改 09 的 Intent 恢复、Proposal 归属和移动布局/测试/资源版本；未修改 `08-HaloCue-1.0/` 或 `10-HaloCue-1.0-Integrated/` 源码。正式场景 pending Proposal 未采纳、未建立新 Revision、未冻结 ScriptRelease、未创建/安装 AA。真实费用 receipt、代理 cache 命中/策略、附件原生文件选择、同 Provider 配置下失败后成功重试、远端真实 `429/504`、正式 ProductionRun 素材副本和 AA 工作区持久安装仍为证据缺口。

## 2026-08-20 场景阻塞恢复入口不再跳错页面

- 复现并修复场景页“查看缺少的输入”在移动端被全局 `data-inspector=agent` 捕获、错误跳到作品级创作导演的问题。`web/app.js` 现在按最近的 `.scene-workbench/.scene-harness` 保留本场 `writingMobileView='agent'` 和稳定场景 URL；场景 Agent 的“补齐人物卡”新增独立处理器，直接进入 `references/characters`，展开新建人物卡并聚焦名称字段。
- `web/shell.css` 的移动 Works Composer 增加滚动安全空间和轻量阴影，资源版本为 `shell.css?v=20260820-30`。定向 `tests/test_natural_language_intent.py` `33 passed`，资源版本合同修正后 `node --check web/app.js` 通过；第一次完整回归只因静态测试仍断言旧缓存版本而失败，修正测试夹具后重跑通过。
- 内置 Browser 实测：场景阻塞页点击“查看缺少的输入”仍停留在 `stage=draft` 的当前场景 Agent；点击“补齐人物卡”进入 `section=references` 的人物库，新建卡表单可见且名称字段获得焦点。未提交人物卡、未改变正式资料；本轮未修改 `08-HaloCue-1.0/` 或 `10-HaloCue-1.0-Integrated/` 源码。完整 09/10 回归待本切片收尾后追加最终汇总；真实费用/cache、附件连续文件选择、同 Provider 成功重试、远端故障、正式 ProductionRun 素材副本和 AA 编译/安装仍是证据缺口。
- 本切片最终回归：09 `473 passed in 258.40s (0:04:18)`；10 集成 `8 passed in 110.67s (0:01:50)`。未提交人物卡、未采纳正式 Proposal、未建立新的 Revision、未冻结 ScriptRelease、未创建 ProductionRun 或安装 AA；Provider 仍为真实 `gemini-3.7-flash (openai)`，费用 receipt、cache 命中/策略、附件原生文件选择连续上传、同 Provider 成功重试和远端 `429/504` 仍无证据。

## 2026-08-20 场景资料恢复回链最终验收

- 内置 Browser 在正式 `8910` 上复现 Scene Agent 阻塞路径：桌面 `1440x900` 点击“补齐人物卡”进入 `references` 人物库，恢复卡显示准确的作品/场景标题；多人物场景不强行预填名称，名称输入保持空白且获得焦点。点击“返回当前场继续”后回到固定 `stage=draft&chapter_id=chapter-6d652b3fb16c&scene_id=scene-3fe0047175da`，页面显示“正在重新准备上下文，不会自动运行 Agent”。
- 同一回链在 `390x844` 实测通过：人物库恢复卡、名称输入焦点、返回按钮和 Scene Agent 均可见，返回后移动正文/Agent/审查导航保持单列，`documentElement` 横向溢出为 `0`。本轮没有提交人物卡、发送 Agent 消息、生成/采纳 Proposal、建立 Revision 或改变正文；Browser 结束已执行 `viewport.reset()`。Console warning/error 未能由当前控制层读取，沿用本会话已记录的 `[]` 证据，不新增推断。
- 定向 `tests/test_natural_language_intent.py`：`34 passed in 11.50s`；完整 09 最终：`474 passed in 258.04s (0:04:18)`；10 集成最终：`8 passed in 118.36s (0:01:58)`；`node --check web/app.js`、`python -m compileall -q src` 通过。服务 `http://127.0.0.1:8910/` 返回 `HTTP 200`。
- 本切片仅更新恢复回链相关 09 前端/测试合同与证据记录，未修改 `08-HaloCue-1.0/` 或 `10-HaloCue-1.0-Integrated/` 源码。Provider 仍为真实 `gemini-3.7-flash (openai)`；真实费用 receipt、代理 cache 命中/策略、附件原生文件选择、同配置成功重试、远端 `429/504`、正式 ProductionRun 素材副本、ScriptRelease 冻结和 AA 编译/安装仍是证据缺口。

## 2026-08-20 正文候选 Diff 桌面/移动复验

- 正式场景 `scene-0235cbef3cf8` 的待审 `scene_script` Proposal 在 `1440x900` 显示“有一份候选等待决定”，逐项 Diff 同时展示当前正文、候选正文、删除/新增标记、生成模型与 usage；当前页面明确“正式正文仍未改变”，高风险“应用 5 项修改”保持用户决定入口。
- 同一页面在 `390x844` 保持单列，首个 Diff checkbox 可聚焦，5 项修改与“取消全选/应用/退回”操作可见，横向溢出为 `0`。本轮没有应用候选、采纳 Proposal 或建立 Revision；`viewport.reset()` 已执行。正式 Provider usage 显示 `11,956 input / 201 output`，缓存与费用仍明确未报告。

## 2026-08-20 作品 Agent 移动端单滚动区修复

- 复现用户窄屏截图后确认根因：作品 Agent 画布把执行计划和对话拆成两个垂直布局层，计划内容撑高后，独立线程滚动区被推到画布外，固定 Composer 覆盖较早决定卡与失败恢复卡。
- `web/shell.css?v=20260820-31` 在移动 Works 画布改为单一纵向滚动拥有者：画布 `overflow-y:auto`，对话线程改为内容流 `overflow:visible`，并为固定 Composer 预留 `144px` 底部空间；桌面线程滚动和 Composer 文档流保持不变。新增 `test_mobile_work_agent_uses_one_scroll_owner_for_plan_and_conversation` 静态合同。
- 内置 Browser 实测：`390x844` 滚动到计划/对话底部时，失败卡、运行摘要和最后一段正文均位于 Composer 上方，末尾与 Composer 顶部间隙约 `50.76px`；`document.scrollWidth=390`、画布横向无溢出。`1440x900` 仍为桌面线程独立滚动、Composer 位于内容列；本轮 Console warning/error 为 `[]`，结束已执行 `viewport.reset()`。
- 定向自然语言/HTTP 回归 `81 passed in 22.46s`；完整 09 最终 `475 passed in 261.45s (0:04:21)`；未修改 `08-HaloCue-1.0/` 或 `10-HaloCue-1.0-Integrated/` 源码，未采纳 Proposal、建立 Revision、冻结 ScriptRelease、创建 ProductionRun 或安装 AA。Provider 仍为真实 `gemini-3.7-flash (openai)`；真实费用 receipt、cache 命中/策略、附件原生文件选择、同配置失败后成功重试、远端 `429/504`、正式 ProductionRun 素材副本和 AA 编译/安装仍为证据缺口。

## 2026-08-20 场景 Agent 刷新后继续轮询

- 复现正文场景页的恢复缺口：持久化 `AgentRun` 已处于 `queued/running` 时，作品 Agent 总览会继续轮询，但场景正文页刷新或重启后只显示“正在思考”，不会等待终态，因此用户无法看到后续公开回复或失败恢复卡。根因是场景渲染路径没有从当前 Scene 对话线程恢复 `activeRun` 的轮询。
- `web/app.js` 在最终渲染入口增加 `stage=draft + sceneId` 的 Scene 作用域恢复：按稳定 Scene ID 找到活动对话线程和 `workAgentActiveRun`，继续调用 `scheduleAgentRunPoll`。它只读取已有运行，不发送新消息、不创建重复运行、不写入 Proposal/Revision；资源版本更新为 `app.js?v=20260820-69`。
- 新增 `test_scene_agent_resumes_polling_after_refresh_from_durable_run`。定向 HTTP/UI 合同 `49 passed`，场景对话与异步恢复 `10 passed`；`node --check web/app.js`、`python -m compileall -q src` 通过。
- Browser 正式 `8910` 场景页：`1440x900` 与 `390x844` 均可见本场 Agent Composer；手机 `scrollWidth=390` 且无横向溢出，桌面内容列无横向溢出，Console warning/error `[]`；结束已执行 `viewport.reset()`。本轮没有发送消息、采纳 pending Proposal 或制造新的正式写作数据。
- 完整 09 回归最终 `480 passed in 236.94s (0:03:56)`；服务 `http://127.0.0.1:8910/` 健康 `HTTP 200`，Provider `gemini-3.7-flash (openai)`、`can_call_model=true`、`is_simulation=false`，Dispatcher `running` 且 `last_error=null`。本轮未修改 08/10 源码。
- Provider usage 可以观察到但缓存能力仍按响应记录，当前服务健康中没有费用 receipt；同配置失败后成功重试、远端 `429/504`、附件原生文件选择、正式 ProductionRun 素材副本、ScriptRelease 冻结与 AA 编译/安装仍是证据缺口。

## 2026-08-20 窄屏面包屑范围可见性

- 复现用户窄屏作品 Agent 截图后，确认顶部 `#crumb` 把作品名和当前范围作为单一文本省略，导致“作品 Agent/创作主对话”在窄屏被截断。`web/app.js` 新增统一 `setCrumb()`，并将 `web/shell.css` 资源更新为 `shell.css?v=20260820-32`：作品名允许省略，当前范围独立保留，完整路径通过 `aria-label` 可访问。
- Browser 实测 `390x844`、`574x965`、`1440x900`：当前范围均可见；`documentElement.scrollWidth` 分别为 `390`、`574`、`1440`（无横向溢出）；作品 Agent Composer 位于内容流末端，手机底部导航不与其相交；Console warning/error `[]`，结束已 `viewport.reset()`。
- 定向 HTTP/UI 合同 `49 passed in 13.08s`；`node --check web/app.js`、`python -m compileall -q src` 通过；完整 09 最终 `480 passed in 225.89s (0:03:45)`。本轮只修改 09 的 `app.js`、`shell.css`、`index.html`、HTTP 合同测试，未修改 08/10。
- Provider 仍为真实 `gemini-3.7-flash (openai)`；正式场景 `proposal-c6411d5dd9a3` 仍 pending，未采纳 Proposal、未建立新 Revision、未冻结 ScriptRelease、未创建 ProductionRun 或安装 AA。真实费用 receipt、cache 命中/策略、附件原生文件选择连续上传、同配置失败后成功重试、远端 `429/504`、正式 ProductionRun 素材副本和 AA 持久安装继续是证据缺口。

- 复查发现 `writing-workbench.js` 的场景渲染器仍会覆盖统一面包屑，已接入 `setCrumb()`，资源更新为 `writing-workbench.js?v=20260820-33`。最终完整 09 回归以最后一次为准：`480 passed in 230.46s (0:03:50)`；`390x844` 写作深链范围节点可见、`scrollWidth=390`、Console warning/error `[]`，结束已 `viewport.reset()`。

## 2026-08-20 场景 Agent 移动 Composer 遮挡修复

- 目标 1 / 4：复现并修复 Scene Agent 移动端固定 Pane 造成的真实遮挡。原布局在 `390x844` 下让历史对话滚动区只剩约 `36px`；`writing-workbench.css?v=20260820-32` 改为移动页面流式滚动，Pane/Panel/对话流不再固定高度或裁剪，Composer 排在完整回复之后；桌面独立 Agent 滚动不变。
- Browser 证据：精确 `390x844` 回复内容完整可见；工作区滚动到底部后 Composer 与底部导航间距 `186.48px`，横向溢出 `0`。`1440x900` 右侧 Agent 仍可独立滚动，横向溢出 `0`；Console warning/error `[]`；结束 `viewport.reset()`。
- 测试证据：定向 `93 passed`；完整 09 `482 passed in 231.14s (0:03:51)`；Python/JS 语法检查通过。服务 `8910` HTTP `200`，Provider 为真实 `gemini-3.7-flash (openai)`，不是 Fake；usage 可观察，cache/费用仍未形成真实验收证据。
- 边界：本轮没有发送新消息、没有采纳 Proposal、没有建立 Revision/Release、没有创建 ProductionRun 或改动 08/10。真实费用、cache 命中、附件连续选择、远端故障、正式制作副本和 AA 持久安装继续记录为证据缺口。

## 2026-08-20 Intent 规划标题与写作深链可靠性

- 目标 1 / 4：修复规划结构到实际写作位置的可靠性缺口。旧逻辑只会重命名通用占位场景；对于先由 Intent 自动建立、后来用户明确补充幕名的未正式场景，标题会停留在旧描述。现在 Intent 创建的场景写入 `title_source=intent`，无正式 Revision 的 `planned/placeholder` 场景允许后续明确标题更新；手工 `update_scene_contract` 写入 `title_source=manual` 后保持人工标题。
- 服务证据：复现“爱丽丝在废弃车站听见异常广播”后再指定“广播响起”，标题更新为“广播响起”；人工改为“人工保留标题”后，再次指定新标题仍保留人工标题。没有修改正式正文或绕过 Proposal/Revision。
- Browser 证据：`390x844` 从章节细纲点击“去写本场”进入固定 `stage=draft&chapter_id=chapter-6d652b3fb16c&scene_id=scene-3fe0047175da`，横向溢出 `0`；`1440x900` 同样稳定跳转，横向溢出 `0`，Console warning/error `[]`；结束 `viewport.reset()`。
- 测试证据：定向 `127 passed`；完整 09 `483 passed in 233.15s (0:03:53)`；Python/JS 语法检查通过。服务 `8910` HTTP `200`，Provider 为真实 `gemini-3.7-flash (openai)`，不是 Fake。
- 边界：本切片未修改 08/10，未发送新的真实 Provider 消息，未采纳 Proposal、建立 Revision/Release、创建 ProductionRun 或安装 AA。真实费用、cache 命中、附件连续选择、同配置失败后成功重试、远端 `429/504`、正式制作副本和 AA 持久安装仍未形成证据。

## 2026-08-20 场景素材追溯详情补齐

- 目标 2：场景引用详情原先只显示原件、版本、Hash 和副本概念，缺少稳定的场景引用 ID，副本状态也不够明确。`web/writing-workbench.js?v=20260820-34` 现在在折叠详情中分别显示“引用 ID”“原件版本”“原件 Hash”和“任务副本状态”，继续区分全局素材原件与 ProductionRun 副本；没有改变引用保存或制作交接协议。
- 测试证据：`tests/test_asset_catalog_ui.py` 与 `tests/test_scene_asset_references.py` 定向 `16 passed`，缓存版本/HTTP/素材定向 `66 passed`；新增制作服务离线合同，确认不创建 ProductionRun 且返回 `production_asset_handoff_unavailable`/503；`node --check web/writing-workbench.js`、`node --check web/app.js`、`python -m compileall -q src` 通过。缓存版本更新后的完整 09 最终 `484 passed in 235.62s (0:03:55)`；此前单次 Intent 失败单独重跑 `38 passed` 后，最终两次完整套件均无失败。10 集成最终 `8 passed in 102.37s (0:01:42)`。
- Browser 证据：正式 Scene `scene-0235cbef3cf8` 在 `390x844` 展开素材详情，显示 `scene_asset_ref-c795bb485dcf`、原件版本 `catalog:557fea7aaf34`、Hash 类型 `aa_resource_hash`、已收到副本 `copy-302f53732d4b`，并确认实际加载 `writing-workbench.js?v=20260820-34`；Composer、移动导航可见，横向溢出 `0`。`1440x900` 同样无横向溢出；结束已 `viewport.reset()`。
- 边界：本轮未选择/移除素材、未发送 Agent 消息、未采纳 Proposal、未建立 Revision/ScriptRelease、未创建 ProductionRun。真实费用/cache、附件连续选择、同配置成功重试、远端 `429/504`、正式 AA 安装仍为证据缺口；未修改 08/10。

## 2026-08-20 Revision 后场景审查主操作顺序

- 目标 5 / 1：复现已采纳正文 Revision 页面仍把“与本场 Agent 讨论”放在“检查本场”之前的问题；待审 Proposal 页面还会显示对旧正文执行审查的次级入口。`web/writing-workbench.js?v=20260820-35` 现在按真实状态投影顺序：Proposal pending 只显示“查看候选与 Diff”；有新 Revision 且没有当前 `scene.review` Gate 时主操作为“检查本场”；审查阻塞时主操作为“查看审查结果”；审查通过后引导下一场或“进入检查与发布”。没有自动采纳、自动审查或绕过 Gate。
- Browser 隔离证据：`tests/in_app_browser_revision_fixture_server.py` 使用临时数据目录和 Fake Provider 建立一场已采纳正文。内置 Browser 首次显示“正文已采纳，先检查本场”，桌面和 `390x844` 手机均只有一个视觉主操作；点击“检查本场”后 Fake 审查完成，显示“本场检查已完成”和“进入检查与发布”，点击后 URL 保留 `section=writing&stage=release&work_id=...&chapter_id=...&scene_id=...`，手机横向溢出 `0`。夹具端口与标签已关闭，最终 `viewport.reset()`。
- 测试证据：自然语言/HTTP 定向 `90 passed`；完整 09 `486 passed in 261.48s (0:04:21)`；10 集成 `8 passed in 104.41s (0:01:44)`；两份 JS、夹具 Python 语法检查通过。
- 边界：Browser 夹具未触碰正式 `8910` 作品、正式 Proposal/Revision/ScriptRelease 或 AA；真实 Provider 网络故障、费用/cache、附件文件选择和正式用户制作安装仍是独立证据缺口。未修改 08/10 源码。

## 2026-08-20 场景审查阻塞定位与处理恢复

- 目标 5 / 1：复现“查看审查结果”仍查找旧 `.review-findings`、无法稳定定位当前 `.scene-review-summary` 的问题；`web/writing-workbench.js?v=20260820-36` 现同时识别当前审查面，并把焦点放到第一个可处理项。当前 Revision 的阻塞发现存在时，主操作仍是“查看审查结果”；阻塞发现已记录为 resolved、但 Gate 仍是上一次 blocked 快照时，页面明确显示“阻塞项已处理，需重新检查”，主操作改为“重新检查本场”，没有把处理记录伪装成 Gate 已通过。
- 原生 `prompt()` 在内置 Browser 控制面实际报“不支持”，因此 `web/app.js?v=20260820-70` 改为应用内 `#findingResolveDialog`：展示发现类型/内容、要求填写处理理由、说明不会自动改正文，并自动聚焦输入；`web/shell.css?v=20260820-34` 补齐桌面/手机对话框样式。处理仍调用原有 finding resolve API，不修改正文、不绕过重新审查。
- 新增 Fake 隔离夹具 `tests/in_app_browser_blocked_review_fixture_server.py`，使用临时数据目录建立带元叙事 blocking finding 的当前 Revision。内置 Browser 在 `1440x900` 点击主操作后，审查面顶边定位到约 `60px`、首个处理按钮获得焦点；`390x844` 显示移动“正文 / Agent / 审查”导航，应用内对话框打开后焦点在 `note`，两档横向溢出均为 `0`。提交阻塞处理理由后开放 blocking 数为 `0`，主操作变为“重新检查本场”，Gate 文案仍明确要求重新检查。全新夹具页 Console warning/error `[]`，实际加载 `app.js?v=20260820-70` 与 `writing-workbench.js?v=20260820-36`；结束已 `viewport.reset()`、关闭标签并清理临时端口。
- 工具恢复证据：第一次点击旧原生 `prompt()` 得到明确的 Browser 不支持错误，改为应用内对话框后复验通过；第一次完整 09 回归为 `488 passed, 1 failed`，唯一失败是静态合同仍断言旧 `app.js` 缓存版本，更新版本合同后单项通过，最终完整 09 为 `489 passed in 256.96s (0:04:16)`；10 集成最终为 `8 passed in 103.99s (0:01:43)`。`node --check` 两份 JS 与夹具 `py_compile` 通过。
- 正式入口 `http://127.0.0.1:8910/` 健康 HTTP `200`，唯一验收后监听端口为 `8910`；Provider 为真实 `gemini-3.7-flash (openai)`、`can_call_model=true`、`is_simulation=false`、`model-config-6`，Dispatcher running 且 `last_error=null`。usage 协议可用，cache 仍为 response-reported/unknown，费用未报告。本切片 Browser 夹具使用 Fake，不新增真实模型调用、费用、cache、Proposal/Revision/ScriptRelease/ProductionRun 或 AA 安装证据；未修改 08/10 源码。

## 2026-08-20 素材变化后的 Gate 失效消费面

- 目标 5 / 2：后端 Gate 快照已经记录 `scene_revision_refs.asset_references`，但发布页原先只比较场景 Revision ID，并且用第一条 Gate 作为当前状态，导致“正文没变、素材变了”或“重新审查后”无法正确推进。`web/app.js?v=20260820-71` 现在按最新 Gate、正文 Hash、素材引用身份/版本/Hash/来源快照、正式资料依赖、写作包和 BA 来源统一投影；素材变化会显示具体场景（例如“素材引用变化：温室门禁”），并明确“先运行连续性审查，再运行发布审查”。
- `web/shell.css?v=20260820-35` 新增失效 Gate 说明面板；连续性审查、发布审查、冻结按钮按当前快照分别启用/禁用。新增 `tests/in_app_browser_asset_gate_drift_fixture_server.py`，在临时 Fake 作品中先完成两项审查再改变素材引用。内置 Browser 最终夹具：`1440x900` 与 `390x844` 均 `overflowX=0`，显示素材变化原因，连续性审查可用、发布审查和冻结禁用；点击连续性审查后，连续性步骤显示“素材引用与正式资料已检查”，发布审查恢复可用；Console warning/error `[]`，结束已 reset viewport、关闭标签并清理临时端口。
- 本轮修复了一个复验中发现的前端状态根因：重新运行连续性审查后页面仍拿旧 Gate，改为按 `created_at` 选择最新 Gate，并用 `releaseSnapshotDrift` 统一判断当前性。相关静态/服务回归与隔离夹具合同均通过。最终完整 09 `491 passed in 263.25s (0:04:23)`；10 集成 `8 passed in 101.50s (0:01:41)`；`node --check web/app.js`、`node --check web/writing-workbench.js`、Python compile/py_compile 通过。
- 正式服务仍为 `http://127.0.0.1:8910/`、HTTP `200`、唯一监听端口 `8910`；Provider `gemini-3.7-flash (openai)`、`can_call_model=true`、`is_simulation=false`、`model-config-6`，Dispatcher running、`last_error=null`。本切片 Browser 使用 Fake 隔离数据，不新增真实费用/cache、远端故障、ProductionRun 副本或 AA 安装证据；未修改 08/10 源码。

## 2026-08-20 冻结前复核面板

- 目标 5 / 1：发布页在 Gate 通过且当前输入未漂移时新增“冻结前复核”面板，明确冻结范围包含场景正文、素材引用、正式资料和审查快照，并提示“冻结不会修改作品原件”。冻结按钮仍保留用户决定入口，未自动执行 ScriptRelease。
- `web/app.js?v=20260820-72` 增加 `release-freeze-preflight` 投影；`web/shell.css?v=20260820-36` 增加桌面四列、手机两列响应式布局。新增静态合同 `test_release_ui_shows_freeze_preflight_before_immutable_handoff`。
- 内置 Browser Fake 隔离夹具实际完成连续性审查与发布审查后：`1440x900` 面板宽 `628px`、冻结按钮可用、横向溢出 `0`；`390x844` 面板宽 `352px`、两列指标、Composer 与底部导航可见、横向溢出 `0`；Console warning/error `[]`，结束已执行 `viewport.reset()`。正式 `8910` 因第二场尚无正文而按协议保持冻结禁用，未伪造面板可用证据。
- 定向发布/HTTP/UI 回归 `66 passed`，`node --check web/app.js` 通过。完整 09 与 10 回归待本轮最终汇总；本切片未修改 `08-HaloCue-1.0/` 或 `10-HaloCue-1.0-Integrated/` 源码，未采纳 Proposal、建立 Revision、冻结 ScriptRelease、创建 ProductionRun 或安装 AA。Provider 与真实费用/cache/ProductionRun 证据边界保持不变。
- 最终门禁：完整 09 `492 passed in 233.51s (0:03:53)`；10 集成 `8 passed in 106.24s (0:01:46)`；`node --check web/app.js`、`node --check web/writing-workbench.js`、`python -m compileall -q src` 通过。正式 `http://127.0.0.1:8910/` 返回 HTTP `200`，唯一监听端口为 `8910`；临时 Browser 夹具进程已清理。

## 2026-08-20 空项目自然语言直达与首屏入口复验

- 目标 1：空项目首屏只保留自然语言 Composer 作为实际创作入口。无 Work 时左侧作品说明、章节流程和顶栏前进/后退箭头均隐藏或禁用；修复旧渲染器在后续 `renderWorkRail`/最终 Agent 渲染阶段重新显示入口的问题。`web/app.js?v=20260820-74`、`web/shell.css?v=20260820-37`；新增捕获层提交处理，避免旧事件委托吞掉“开始创作”，并在启动最终布局完成后恢复 Composer 焦点。
- Browser 隔离夹具 `tests/in_app_browser_first_use_fixture_server.py` 使用临时空库和明确的 `fake / local-rules` Provider。`1440x900` 实测左栏说明与章节流程 `display:none`、前进/后退均 disabled、Composer 自动聚焦、`overflowX=0`；`390x844` 实测澄清预览可展开，发送原文后预览关闭且焦点回到 `#intentMessage`，手机底部导航可见，`overflowX=0`，Console warning/error `[]`。
- 自然语言纵切：输入“我想写一个爱丽丝在废弃车站遇到老师的短篇同人故事，先从第一幕开始。”后点击“开始创作”创建 `未命名作品`，生成持久 Intent 执行计划和作品 Agent 对话；计划卡“去写这一幕”实际跳转到 `section=writing&stage=draft&chapter_id=...&scene_id=...`，逐场页面显示上下文准备、素材引用、正文/Agent/审查入口，手机单列无横向溢出。该夹具仅用 Fake Provider，不代表真实生产验收。
- 测试证据：最终自然语言/HTTP 定向 `96 passed`；`node --check web/app.js` 通过；焦点收尾后的完整 09 `495 passed in 260.09s (0:04:20)`；10 集成 `8 passed in 101.56s (0:01:41)`。最终 Browser 在先设置 `390x844` 再导航空夹具时 `document.activeElement=#intentMessage`、`overflowX=0`、Console warning/error `[]`；结束 `viewport.reset()`、关闭夹具并恢复正式 `8910` 标签。正式入口 HTTP `200`、唯一监听 PID `11084`，未修改 08 或 10 源码。
- 边界：本轮未采纳 Proposal、未建立新的 Revision、未冻结 ScriptRelease、未创建正式 ProductionRun 或安装 AA；正式 Provider 仍为 `gemini-3.7-flash (openai)`，usage 可观察，但真实费用 receipt、cache 命中/策略、附件连续上传、同配置失败后成功重试、远端 `429/504`、正式制作副本和 AA 持久安装仍是证据缺口。

## 2026-08-20 自然语言 Agent 附件 UI 连续纵切

- 目标 1 / 3：使用 `tests/in_app_browser_first_use_fixture_server.py` 的临时空库和明确标注 `fake / local-rules` Provider，先通过自然语言 Composer 创建临时 Work，再在作品 Agent Composer 打开“添加附件 -> 上传文档”。内置 Browser `filechooser` 成功接管 `README.md`，Composer 显示 `MD README.md · 文档`，移除按钮可见；发送“请读取这份附件，只总结其中的工作边界，不修改正式资料。”后用户消息回显文档链接，显示“已作为本轮上下文”。
- Agent 运行证据：Fake 运行摘要包含 `store_conversation_attachments succeeded`、`read_work_context succeeded`，文档回复明确“文字已提取并固定到本轮上下文；当前为模拟 Provider，没有冒充完成语义分析”。没有自动采纳 Proposal、修改正式资料或正文。
- Browser 证据：桌面 `1440x900` 附件选择、暂存、发送和消息回显均通过，`overflowX=0`、Console warning/error `[]`；手机 `390x844` 回读附件卡宽 `221.27px`、Composer 宽 `339.33px`、底部导航从 `790px` 开始、`overflowX=0`、Console `[]`。已 `viewport.reset()`、关闭临时标签和夹具，恢复正式 `8910` 标签。
- 后端合同已有定向覆盖：附件类型/大小/Base64 校验、Markdown 抽取、文档索引、Agent 输入快照、消息发送后 `staged -> attached` 状态和内容回读均由 `test_conversation_slice.py` / `test_document_context.py` 覆盖。本切片没有新增代码，新增的是内置 Browser 文件选择连续证据。
- 边界：夹具仍使用 Fake Provider，不能证明真实模型对附件的语义理解、费用或缓存；正式用户附件、真实 Provider 网络故障、费用 receipt/cache、同配置真实重试、ProductionRun 副本和 AA 持久安装仍是证据缺口。未修改 08/10，正式入口仍为 `http://127.0.0.1:8910/`。

## 2026-08-20 自然语言 Agent 摘要可读性与附件计数修复

- 目标 1 / 3：复现附件已成功绑定、但运行摘要仍显示“保存对话附件 · 已处理 0 项”的投影缺口。`src/halocue_writing/service.py` 现在以服务端本轮附件输入数量作为 `store_conversation_attachments` 的固定工具输入；`src/halocue_writing/agent_presentation.py` 将持久化的公开工具输出摘要投影到只读时间线，并把内部工具名映射为中文用户可读标签，例如“保存对话附件 · 已处理 1 项”“读取作品正式资料 · 已读取 0 项正式资料”。未暴露输入快照、隐藏参数或思维链。
- 前端窄窗口修复：`web/app.js?v=20260820-75` 将计划卡内部 `CURRENT INTENT`/`EARLIER DECISION` 改为“当前请求”/“较早请求”；`web/writing-workbench.css?v=20260820-33` 收紧手机卡片间距、文字截断和 420px 以上窄桌面三列动作布局，保留目标、风险、恢复和稳定场景跳转，不改变安全边界。
- 测试证据：附件/对话/HTTP/时间线/自然语言定向 `153 passed`；`node --check web/app.js`、`python -m compileall -q src`、夹具 `py_compile` 通过。完整 09 最终 `496 passed in 233.52s (0:03:53)`；10 集成最终 `8 passed in 111.72s (0:01:51)`。
- Browser 证据：正式 `8910` 作品 Agent 在 `390x844`、`574x965`、`1440x900` 复验，计划卡标签为中文、Composer 存在、`documentElement.scrollWidth === clientWidth`（分别为 `375/375`、`559/559`、`1440/1440`；浏览器工作区含滚动条时 CSS 视口宽度分别为 `375/559/1440`），Console warning/error `[]`，最终执行 `viewport.reset()`。Fake 隔离附件夹具实际完成“添加附件 -> 上传 README.md -> 发送 -> 展开运行摘要”，公开摘要包含“保存对话附件 · 已处理 1 项”；`390x844` 与 `1440x900` 均无横向溢出，Console `[]`。夹具标签、端口 `1428`、进程均已清理。
- 失败恢复记录：第一次夹具重启把停止与启动合并为一条命令，被执行策略拒绝；拆成停止 PID、确认端口释放、重新启动三步后恢复。第一次隐藏 file input 选择器超时；改用可见“添加附件 -> 上传文档”按钮后成功完成 Browser filechooser 证据。无真实模型调用、无正式作品写回。
- 边界：本轮未采纳 Proposal、未建立新的 Revision、未冻结 ScriptRelease、未创建正式 ProductionRun 或安装 AA；未修改 `08-HaloCue-1.0/` 或 `10-HaloCue-1.0-Integrated/` 源码。正式服务 `http://127.0.0.1:8910/` HTTP `200`，唯一监听 PID `21768`。Provider 仍为正式服务当前配置 `gemini-3.7-flash (openai)`；usage 可观察，但费用 receipt、cache 命中/策略、真实 Provider 同配置成功重试、远端 `429/504`、正式 ProductionRun 资产副本和 AA 持久安装仍为证据缺口。

- 集成壳只读复验：临时标签打开 `http://127.0.0.1:8910/?section=production`，`#productionModule` 的 ShadowRoot 已挂载；`390x844` 与 `1440x900` 均无横向溢出，作品/写作/AA制作/素材/资料/任务/反馈/设置导航与制作流程可见，手机底部导航和桌面侧栏保持统一 Shell，Console warning/error `[]`。未点击“选用此剧本制作”、未建立制作任务、未执行安装；临时标签已关闭并 `viewport.reset()`。10 集成完整回归 `8 passed in 111.72s (0:01:51)`。

## 2026-08-20 正式场景候选文字审查复验

- 正式作品 `work-583189373ff2` 的场景 `scene-0235cbef3cf8` 当前有真实 Provider 待审 `scene_script` Proposal。只读深链实际显示：`PROPOSAL / 未写入`、真实 Provider、生成时模型、运行 ID、`11,956 input / 201 output token`、缓存/费用未报告；每项变化均有当前正文、候选正文、删除/新增语义、字符级文字 Diff、复选框、选择计数、应用和退回入口。当前正文仍是 `revision-293c472616cb`，未发生写回。
- 该候选固定于 `model-config-5`，当前服务已是 `model-config-6`；页面明确显示“当前配置已变化”，不会把历史候选冒充当前配置或自动重跑。素材引用区同时显示本场背景原件与任务副本状态。
- Browser `390x844` / `1440x900`：Diff 根节点、应用按钮、场景 Composer 和真实 Provider 标识均存在；页面横向溢出为 `0`，Console warning/error `[]`，结束已 `viewport.reset()` 并关闭临时标签。本轮未点击应用/退回、未建立新 Revision、未改变正式正文。

## 2026-08-20 候选配置漂移的审查说明

- 复现正式场景候选使用 `model-config-5`、当前服务为 `model-config-6` 的真实状态。后端采纳合同已固定校验 `proposal.base_revision_id == scene.current_revision_id`，正文变化时返回 `revision_conflict`，Provider 配置变化不会绕过正文版本保护。
- `web/app.js?v=20260820-76` 在候选运行信息中新增“候选已固定，不会自动重跑；采纳前校验正文基准版本”，并保留生成时模型、配置、运行 ID、usage、cache/费用边界；`web/styles.css` 为该提示增加可读的漂移状态样式。没有自动重新调用模型或修改 Proposal 状态。
- 定向 HTTP/vertical/presentation `155 passed`；`node --check web/app.js` 通过。完整 09 最终 `496 passed in 244.59s (0:04:04)`；10 集成最终 `8 passed in 116.74s (0:01:56)`。
- Browser 正式候选在 `390x844` 与 `1440x900` 实际显示新说明；Diff、逐项应用/退回、Composer 和素材引用仍可见，横向溢出 `0`，Console warning/error `[]`，结束已 `viewport.reset()` 并关闭临时标签。本轮未应用/退回候选、未建立 Revision、未改变正文。

## 2026-08-20 普通用户 UI 信息减负：AA 交接与场景素材名称

- 目标 2 / 5：完成 AA 制作交接面板和场景素材主界面的边界审计。普通界面保留“已送往 AA 制作”“1 项素材已准备”、可识别的素材名称/类型、阻塞原因和刷新；删除 `ScriptRelease`/`ProductionRun` 关联说明、发布标识、Run/Scene/Reference/Copy ID、正文/原件 Hash、schema 与内部英文对象名。发布完整性摘要与素材引用身份、版本、Hash、副本状态仍保留在折叠“技术详情”及 API/数据库合同中。
- `web/production-embed.js` 将外层顶栏的 Run ID 改为“制作任务已打开”；交接读取继续使用原始 `run_id`，没有改变交接合同或数据追溯。`web/writing-workbench.js` 新增 `sceneAssetDisplayName()`：当 display name 缺失或等于资源键时，普通界面显示“背景素材/角色素材/音效素材/CG 素材”，原始 `source_asset_id` 只在技术详情中出现；选择器结果不再把资源键作为副标题。
- 测试证据：素材/引用/HTTP 定向 `72 passed`；交接显示合同定向 `2 passed`；`node --check web/writing-workbench.js`、`node --check web/production-embed.js` 通过。完整 09 最终 `499 passed in 362.94s (0:06:02)`。
- 内置 Browser 正式 `8910`：场景素材页 `1440x900`、`390x844` 均不显示 `00000-1392481605`，显示“背景素材”，横向溢出 `0`；发布 Gate 手机 `390x844` 唯一主操作“去完成…”返回准确 `scene_id`，焦点落到目标 `H2`，Composer 未被底部导航遮挡。AA 交接在 `1920x1080`、`1440x900`、`1366x768`、`390x844` 均显示“已送往 AA 制作”“1 项素材已准备”和“刷新”，横向溢出 `0`，手机编译操作/导航未遮挡；Console warning/error `[]`，结束已 reset viewport。
- 边界：只修改 `09-HaloCue-1.0-Writing`，未修改 08/10；未发送模型消息、未采纳 Proposal、未建立 Revision/ScriptRelease、未创建 ProductionRun 或安装 AA。正式 Provider 当前为 `gemini-3.7-flash (openai)`，不是 Fake；本轮未触发模型调用。真实费用 receipt、cache 命中/策略、远端故障、正式 ProductionRun 副本和 AA 持久安装仍是证据缺口。

## 2026-08-20 AA 制作列表技术标签二次清理

- 复验发现嵌入的 AA 制作“最近任务”和逐卡审查仍把 `run-…`、`compiled`、`installed`、`waiting_for_review`、`scene`、`line` 直接暴露给普通用户。`web/production-embed.js?v=20260820-6` 在 09 ShadowRoot 适配层做显示投影：改为“已编译/已安装/待审查/需要处理”和“场景/对白”，不改变 `data-run-id`、卡片 ID、路由或状态机。
- 定向交接/焦点/标签合同 `3 passed`；第二次完整 09 最终仍为 `499 passed in 322.40s (0:05:22)`。内置 Browser 复验最近任务与审查卡：Run ID、英文类型均不可见，中文标签可见；`1920x1080`、`1440x900`、`1366x768`、`390x844` 横向溢出均为 `0`，Console warning/error `[]`，交接刷新和移动编译/导航仍可用。

## 2026-08-20 正文候选应用影响与重新审查提示

- 目标 5 / 1：场景正文 Diff 在唯一主操作前新增紧凑“应用后的影响”投影，使用普通用户语言说明“建立一版新的正式正文”“本场需要重新检查”；已有连续性或发布 Gate 时补充“连续性与发布检查需要重新运行”，已有冻结版本时说明“已有制作定稿保持不变”。没有新增按钮、API 或状态机，Revision/Gate/Run/Hash 等内部标识不进入该提示；运行证据仍留在既有折叠“运行详情”。
- `web/app.js?v=20260820-78` 在采纳成功后提示“新正文版本已建立；旧审查结果不再适用，请先检查本场”；`web/writing-workbench.css?v=20260820-34` 提供桌面横向、手机纵向的无卡片提示布局。新增领域测试证明新正文建立后，旧 `scene.review` Gate 作为历史记录保留，但没有绑定新 Revision 的当前 Gate；正式 Proposal -> 用户决定 -> Revision 边界未改变。
- 测试证据：JS 语法检查通过；定向 HTTP/UI/vertical `5 passed in 3.40s`；完整 09 最终 `501 passed in 263.82s (0:04:23)`。未运行 10 集成回归，本切片未修改 10。
- 内置 Browser 只读复验正式待审候选：`1920x1080`、`1440x900`、`1366x768`、`390x844` 均显示影响提示，候选决策面只有一个主按钮，横向溢出均为 `0`；手机影响区与应用按钮完整可见，移动导航无可见遮挡。“查看候选与 Diff”将焦点放到首个变化复选框；桌面返回路径进入章节结构，手机正文/Agent 可往返，Composer 与底部导航边界相接。Console warning/error `[]`，结束已 reset viewport 并关闭标签。
- 边界：未点击应用或退回，未发送 Agent 消息，未采纳正式 Proposal、建立 Revision、冻结 ScriptRelease、创建 ProductionRun 或安装 AA；未修改 08/10。正式 `http://127.0.0.1:8910/` 健康，Provider 为 `gemini-3.7-flash (openai)`、`can_call_model=true`、`is_simulation=false`、`model-config-6`，Dispatcher running 且 `last_error=null`；本切片未触发模型调用。真实费用 receipt、cache 命中/策略、远端故障、正式 ProductionRun 副本和 AA 持久安装仍是证据缺口。
## 2026-08-20 稳定闭环验收最终汇总

- 09 完整回归最终 `501 passed in 269.20s (0:04:29)`；10 集成完整回归最终 `8 passed in 116.87s (0:01:56)`。`node --check web/app.js`、`node --check web/writing-workbench.js`、09 `python -m compileall -q src` 已通过。
- 正式服务 `http://127.0.0.1:8910/` 健康；Provider 为 `gemini-3.7-flash (openai)`，`can_call_model=true`、`is_simulation=false`，不是 Fake。隔离真实 Provider 纵切完成一轮作品讨论和一场场景 Proposal，Proposal 保持 pending，未采纳、未写入 Revision；累计 usage `19,545 input / 1,004 output`，费用未由 Provider 报告，不能视为免费；cache 命中/未命中未知。临时 8921 服务及隔离数据已停止并删除。
- ProductionRun 只读回执核对：`run-608b2614ca91/resource-usage` 返回 `production-asset-usage/1.0`，含场景引用、原件版本、原件 Hash 和任务副本回执；未创建新任务，ScriptRelease/正文/WorkCanon 未被改变。10 的 `test_scene_asset_handoff_creates_a_verified_production_run_receipt` 已包含副本身份与回执合同证据。
- 内置 Browser 正式页面四档验收（`1920x1080`、`1440x900`、`1366x768`、`390x844`）：写作候选页和 AA 制作页横向溢出均为 `0`；候选页唯一主操作、运行详情折叠、Proposal 未写入提示、移动 Composer/导航未遮挡，焦点进入候选区；AA 页 ShadowRoot 已挂载、首步制作入口可见、移动内容未被导航遮挡；Console warning/error 均为 `[]`。普通 UI 未显示 Revision/Run/Hash/Schema/内部英文状态，技术字段仍通过 API/折叠详情可追溯。
- AA 能力门阻塞：请求目标 `D:\桌面\蔚蓝档案二创\AA自动写剧本文件\02-最终AA工程` 是 `.aap` 项目集合，不是现有 AA 后端认可的 `data` 工作区，环境探测 `adopted=false`。未创建伪工作区、未覆盖 `.aap`、未修改 08；正式 AA 安装因此不能声称完成。当前结论为“ProductionRun/素材交接完成，AA 安装因外部边界阻塞”。
- 未完成或无真实证据：真实费用 receipt、cache 命中策略、远端 429/504、正式 ScriptRelease 冻结后的新 ProductionRun、目标 AA 持久安装。后续只能在合法 AA 工作区和明确安装合同存在时继续。
## 2026-08-20 一句想法到 ProductionRun 联合闭环补证

- 10 新增 `test_one_sentence_intent_reaches_production_without_bypassing_user_decisions`，从 `WritingService.plan_intent` 的一句自然语言开始，等待作品 Agent 结束后显式整理 `brief_blueprint` Proposal；断言方向 Proposal pending 时 brief/story_blueprint 没有正式 Revision，随后显式采纳方向，再生成并显式采纳 `scene_script` Proposal，才建立 Scene Revision。
- 同一测试继续按 `scene.review -> continuity.review -> release.review -> freeze` 顺序执行，冻结前 releases 为空；冻结后只读读取 ScriptRelease，交接到 ProductionRun，并断言 content hash、正文 text、manifest 和 release identity 不变，唯一允许变化是首次回填 `production_run_id` 交接关联；重复交接返回同一 ProductionRun。
- 本轮测试结果：10 完整 `9 passed in 137.14s (0:02:17)`（含新增联合测试）；09 完整 `501 passed in 269.13s (0:04:29)`；09/10 Python 编译检查、`node --check web/app.js`、`node --check web/writing-workbench.js` 通过。
- 内置 Browser 正式复验：写作候选决策页 `1440x900`、`390x844` 均显示“有一份候选等待决定”“正式正文仍未改变”，横向溢出 `0`、内部字段检测为空、Console warning/error `[]`；AA 制作页 ShadowRoot 已挂载，`390x844` 首步“选择剧本”和“选用此剧本制作”可见，底部导航不遮挡，横向溢出 `0`、Console `[]`。未点击采纳、冻结、编译或安装。
- 正式 Provider 仍为 `gemini-3.7-flash (openai)`，真实纵切累计 usage `19,545 input / 1,004 output`；费用未报告、cache unknown。未修改 08；本轮仅修改 10 集成测试和本证据文件，未修改 09 业务代码。
- AA 指定目标能力门仍阻塞：`02-最终AA工程` 不是现有 AA 后端认可的 `data` 工作区（`.aap` 项目集合，`adopted=false`），因此不能执行正式安装或声称 AA 工作区验收完成。
## 2026-08-20 外部工作区恢复后正式 AA 安装验收

- 用户明确允许使用电脑中其他位置后，重新探测并采用现有 AA 后端认可的 `E:\AzureArchive\存储文件\data`；未修改 08 源码，也未使用或覆盖 `02-最终AA工程` 的 `.aap` 集合。
- 安装前只读能力门：workspace `valid=true`，compile/install/script-release-handoff/scene-asset-handoff 均 available；AA 进程未运行；唯一测试工程名 `HaloCue闭环验收-20260820-RealProvider-v2` 的 `install-check` 返回 `available=true`、`conflict=false`。
- 正式安装回执：ProductionRun `run-608b2614ca91`、构建 `build-9f009eb8b711`、ScriptRelease `release-3b8020f120b1`，安装状态 `installed`；`.aap`、工程目录和 save 目录均已生成，`last_installed_project` 为唯一测试工程名。
- 安装后只读核对：ScriptRelease 内容 Hash 与 manifest Hash 均为 `sha256:22285fb4622a4abaf82c0e6bea17f2362dbca016c285ab34719d9a79ff0315a3`，来源 Revision 仍为 `revision-293c472616cb`；ProductionRun 上游 release、写作正文和素材回执未漂移。回执 schema `production-asset-usage/1.0`，包含 1 条场景引用和任务副本 `copy-302f53732d4b`。
- 重复提交保护：安装后 `install-check` 对同名工程返回 `conflict=true`；重复安装请求返回 HTTP `409 build_not_installable`，没有覆盖已有安装。既有 09/10 测试仍覆盖运行中保护、失败回滚与交接幂等协议。
- 本阶段结论升级为“09 + 10 真实闭环完成，正式 AA 工作区验收完成（使用现有合法工作区）”。费用仍未由 Provider 报告，cache 仍 unknown；这些不被冒充为真实费用或 cache 证据。

## 2026-08-21 10 全链路稳定性与生产深链复验

- 普通消息与制作标签继续减负：`web/app.js` 只在 assistant 的显示投影中把内部 Revision/Run/Proposal/Hash 和英文领域名改为用户语言；user 原文、消息对象、API 与数据库内容不变。`web/production-embed.js?v=20260821-1` 删除制作标题可见 Run ID，但 `data-run-id`、API 路由和回执仍保留追踪身份。新增静态合同覆盖这两个边界；09 定向最终 `10 passed`。
- 10 的一句想法联合测试现在继续经过制作侧角色映射、逐卡审查、确定性编译、隔离 AA 工作区的 install-check、安装和重复安装拒绝；安装文件只能落在 pytest 的临时 `aa-data`。测试同时断言安装后 ScriptRelease 的 ID、正文、内容 Hash 和 manifest 不变。单项 `1 passed in 34.71s`，最终 10 完整回归 `9 passed in 138.22s (0:02:18)`。
- Browser 发现直接打开 `section=production&run_id=...` 时，制作面已恢复但写作路由稍后把 URL 改回 `section=works`。`writing-workbench.js?v=20260821-38` 现在让 10 集成壳独占 production 初始深链；5 秒稳定等待后 URL、ShadowRoot 和 ProductionRun 保持一致，返回写作后保留 Work/Chapter/Scene，再进入制作时焦点恢复到 `#productionModule`。10 build 更新为 `halocue-integrated/1.0.0+20260821.9`。
- 最终 09 完整回归 `504 passed in 293.15s (0:04:53)`；09/10 Python compileall、`node --check web/app.js`、`writing-workbench.js`、`production-embed.js`、`static/integration-shell.js` 通过。正式服务重启为 PID `45608`，`http://127.0.0.1:8910/` 写作/制作健康，Dispatcher running、last_error null，compile/install/scene_asset_handoff 均 available。
- 内置 Browser 正式 ProductionRun `run-608b2614ca91` 在 `1920x1080`、`1440x900`、`1366x768`、`390x844` 检查：页面和制作 Shell 横向溢出均为 `0`；每档只有“编译 AA 工程”一个可见主操作；交接状态、`1 项素材已准备` 和刷新可见；手机导航无内容遮挡；普通界面未显示 Run/Revision/Reference/Copy/Hash/Schema；Console warning/error `[]`。结束时重启后的 `1440x900`、`390x844` 再次通过。
- 正式数据只读核对：ScriptRelease `release-3b8020f120b1` 仍指向 `revision-293c472616cb`，内容/manifest Hash 不变；素材回执仍为 `production-asset-usage/1.0`，任务副本仍为 `copy-302f53732d4b`。此前正式安装的 `.aap`、工程目录和 save 目录仍存在。因 Browser 重新编译，当前 ProductionRun 状态是 `compiled`、最新构建为 `build-9f6448402945`，旧安装没有被覆盖，也没有对同名工程再次安装。
- 边界：未修改 08、01 或 06；修改仅在 09/10。正式 Provider 为真实 `gemini-3.7-flash (openai)`，`can_call_model=true`、`is_simulation=false`；本阶段未调用写作模型。费用仍未报告、cache 仍 unknown，不能宣称为零费用或已验证真实缓存。

## 2026-08-21 作品 Agent 与写作 Inspector 可用性修复

- 修复写作桌面端在 `761–1360px` 范围直接隐藏 Inspector 的样式错误；右侧“当前决定 / 上下文 / 创作导演”恢复显示和切换。内置 Browser `1440x810` 实测 Inspector 宽 `380px`、三项均可见；切到创作导演后只有 `.conversation-scroll` 一个实际溢出的消息滚动区，不再出现空白最右滚动条。
- 修复作品 Agent 展开“查看较早对话”后 Grid 把聊天区压缩且外层不可滚动的问题。桌面改由 workspace 作为唯一页面滚动容器；展开后实测 workspace `clientHeight=750`、`scrollHeight=4152`、`overflow-y=auto`，canvas/thread 不再形成受困内嵌滚动。
- 普通界面减负：顶部五阶段流程与“判断依据”弹层改为一条“下一步”；自然语言请求卡不再输出 Agent 内部行动列表，也不显示“高风险/低风险”，只保留请求、可识别目标、用户需要处理的状态和操作。确认行为新增模态框，用户再次确认后才继续；正式作品仍只通过 Proposal/Revision 边界落地。当前 Provider 协议只有字符串问题列表，没有正式 `choices` 字段，因此未伪造 A/B/C 选择协议。
- 内置 Browser 按用户要求以 `1440x810`（16:9）验收作品和写作页；作品历史展开可滚动、写作三栏切换正常、Console warning/error `[]`。另以 `390x844` 检查，文档/body/app 均无页面级横向溢出，Composer 与移动导航存在且未造成整体宽度溢出；结束时恢复并保留 16:9 作品页供用户查看。
- 定向合同最终 `102 passed in 23.13s`；`node --check web/app.js`、`node --check web/writing-workbench.js` 通过；09 完整回归最终 `504 passed in 302.37s (0:05:02)`。服务地址仍为 `http://127.0.0.1:8910/`。本阶段仅修改 09 的 UI、CSS 和相关合同测试，未修改 08、10、01 或 06；未调用模型、未采纳 Proposal、未建立 Revision/ScriptRelease/ProductionRun。
- 追加减负：正常完成/运行中的执行计划不再进入作品 Agent 主聊天，只保留需要确认、阻塞或失败恢复的卡片；左栏重复的“下一步”入口移除，聊天区保持唯一主操作。第二次定向测试 `102 passed in 23.05s`，09 完整回归最终 `504 passed in 304.71s (0:05:04)`；浏览器 `1440x810` 复查页面级横向宽度 `1440/1440`、Console `[]`，正常页面执行卡为 `0`，左栏重复入口不存在。

## 2026-08-21 截图对应缓存与写作场景复验

- 用户截图中的三条内部执行步骤来自旧版 `app.js` 缓存；本轮将入口资源更新为 `app.js?v=20260821-79`，避免浏览器继续使用旧 UI。当前写作结构页和场景页重新加载后，`.intent-plan-card` 与步骤 chip 均为 `0`；场景页只保留“有一份候选等待决定 / 查看候选与 Diff”等用户可执行状态，不再显示“准备作品、读取资料、把原文交给 Agent”。
- 内置 Browser 16:9 `1440x810` 实测当前 URL `section=writing&stage=draft`：页面宽度 `body=1425 / document=1425 / inner=1440`（仅保留浏览器滚动条占用，无横向溢出），Console warning/error `[]`；结构页同样无执行计划卡。定向合同最终 `102 passed in 27.64s`。未修改 08/10/01/06，未触发 Provider 或正式数据写入。

## 2026-08-21 聚焦式首次使用引导

- 新增一次性界面引导，不新增业务状态机：首次没有作品时自动启动；已有作品可从“设置 → 创作与演出偏好 → 重新查看界面引导”再次启动。引导依次聚焦作品、创作对话、聊天/候选、Composer、写作和 AA 制作；每步都有遮罩、高亮框、说明、`跳过`、`下一步`，最后为`完成`。
- 内置 Browser `1440x810` 实测：第 `1 / 6` 步显示“作品”，点击下一步进入第 `2 / 6` 步“创作对话”，高亮框随目标更新且不越界；Console warning/error `[]`。首次空状态仍保留简短三步概览，实际理解由聚焦式教程承担。
- 定向测试 `102 passed in 23.73s`；09 完整回归最终 `504 passed in 270.78s (0:04:30)`；`node --check web/app.js` 通过。仅修改 09，未修改 08/10/01/06，未写入正式资料。

## 2026-08-21 Agent 候选分离与场景正文上下文审查

- 作品 Agent assistant 消息会把 `official_script` fenced content 投影为独立“正文候选 · 尚未写入”区域；普通讨论文字不再混入脚本，候选只提供“去写作页审查”，不在作品页直接采纳或写回正文。
- 场景候选由“每项当前/候选双栏卡片”改为“修改选择条 + 完整正文预览”：上下文行保持正常色，删除内容红色标记，候选内容绿色标记；原有选择、全选、部分应用、退回与 Proposal→Revision 边界不变。
- 作品 Agent Composer 桌面 sticky、手机 fixed；写作 Agent 手机 pane 由对话区单独滚动，外层 workspace 在 Agent 视图不再产生第二根滚动条。Inspector `上下文 / Agent / 审查` 高亮与实际内容同步。
- 新手引导增加正文候选、审核协作、附件、场景正文、局部选择、上下文、Agent、Composer 和 AA 制作关键控件说明，仍为一次可跳过/可重播的聚焦教程。
- 真实证据：`node --check web/app.js`、`node --check web/writing-workbench.js` 通过；新增 UI 合同 `4 passed`；本轮完整 09 最终 `508 passed in 283.50s (0:04:43)`。正式服务 `http://127.0.0.1:8910/` Provider 为真实 `gemini-3.7-flash (openai)`；本轮未调用模型、未采纳 Proposal、未建立 Revision/ScriptRelease/ProductionRun。
- 内置 Browser 16:9 `1440x810` 实测：作品 Composer 滚动后仍在可视底部；写作 Inspector 可往返切换，Agent 内容只有 `scene-conversation-scroll` 实际消息滚动；场景候选完整正文显示红/绿上下文行且不再有 `.scene-diff-columns`。`1920x1080`、`1440x900`、`1366x768` 横向溢出均为 `0`；`390x844` 作品 Composer fixed、写作 Agent 只有一根消息滚动；Console logs `[]`。
- 只修改 `09-HaloCue-1.0-Writing` 的前端与相关合同测试；未修改 08、10、01 或 06。技术 Proposal/Revision/运行证据仍在 API 与折叠详情中，普通 UI 未增加内部 ID/Hash/Schema/Run 字段。

## 2026-08-21 正文阅读面与 Agent 栏视觉减负

- `web/writing-workbench.css` 对正文编辑区做了阅读优先的视觉收束：正文标题、段落间距、行高和说话人层级重新拉开；段落的移动/删除控件默认退到 hover/focus，正文不再呈现为密集表格。移动端保留可触达控件、保存按钮和底部导航。
- 同一 CSS 将场景 Agent 改为“轻量上下文状态行 → 单一消息滚动区 → Composer”三段节奏；上下文不再抢占对话空间，候选等待提示与输入区增加留白，仍只保留讨论/形成候选/发送的正式边界。
- `web/app.js` 的正文文案改为“当前正文 / 正文段落 / 保存正文”，新手引导改为解释当前场景、阅读正文、上下文、Agent 和候选的真实作用；已有作品在未完成引导时也会自动进入可跳过的聚焦教程，仍可从设置重播。
- `node --check web/app.js`、`node --check web/writing-workbench.js` 通过；定向 HTTP/自然语言合同最终 `106 passed in 27.06s`；09 完整回归最终 `508 passed in 277.49s (0:04:37)`。
- 内置 Browser 16:9 `1440x810`：正文阅读区和 Agent Composer 可见，页面横向溢出 `0`，Console warning/error `[]`。`390x844`：页面横向溢出 `0`，正文段落可滚动，切换 Agent 后仅 `scene-conversation-scroll` 一个实际消息滚动容器，移动导航不遮挡。
- 本轮只修改 09 的 `web/app.js` 与 `web/writing-workbench.css`；未修改 08、10、01、06，未调用 Provider、未采纳 Proposal、未建立 Revision/ScriptRelease/ProductionRun。正式 Provider 仍为 `gemini-3.7-flash (openai)`；费用未报告、cache unknown。

## 2026-08-21 Agent 改动并入正文阅读面

- 有待审 `scene_script` Proposal 时，`renderDraft` 现在仍渲染同一张 `manuscript-desk`，但把候选 Diff 作为正文内部的 `has-inline-review` 区域；不再先离开正文再打开独立候选窗口。正文标题直接提示“有一份改动待决定”，改动区继续保留完整上下文、红删/绿增、逐项选择、应用与退回。
- 原有“查看候选与 Diff”入口只负责把焦点带到正文内已存在的改动，改名为“查看正文改动”并保留 aria 兼容标签；它不创建第二个视图、不复制状态机、不改变 Proposal → 用户决定 → Revision 边界。
- 新增静态 UI 合同 `test_pending_scene_proposal_is_rendered_inside_manuscript_surface`；定向合同最终 `107 passed in 22.74s`；09 完整回归最终 `509 passed in 298.39s (0:04:58)`；`node --check web/app.js`、`node --check web/writing-workbench.js` 通过。
- 内置 Browser 16:9 `1440x810` 正文页：正文面存在且页面横向溢出 `0`、Console warning/error `[]`。`390x844` 正文与 Agent：横向溢出 `0`，Agent 仍只有 `scene-conversation-scroll` 一个实际消息滚动容器，移动导航未遮挡。当前正式场景没有 pending Proposal，因此本轮未伪造截图或声称已采纳候选分支；代码与合同已覆盖该分支。
- 本轮只修改 09；未修改 08、10、01、06，未调用 Provider、未采纳 Proposal、未建立 Revision/ScriptRelease/ProductionRun。正式 Provider 仍为 `gemini-3.7-flash (openai)`；费用未报告、cache unknown。

## 2026-08-21 正文密度与段落类型常驻显示

- 根据正文截图复查，收紧 `.manuscript-block` 的上下留白、正文行高和最小高度，避免一屏只能看到少量段落；旁白/对白/动作的类型选择现在始终显示，不能靠点击或 hover 才出现。
- 桌面 `1440x810` 实测前三段高度约 `131–137px`，类型选择器 opacity `1`；手机 `390x844` 段落高度约 `125px`、类型选择器 opacity `1`。两档横向溢出均为 `0`，Console warning/error `[]`。
- `node --check web/app.js`、`node --check web/writing-workbench.js` 通过；定向合同 `107 passed in 22.87s`；09 完整回归最终 `509 passed in 271.46s (0:04:31)`。
- 本轮只修改 09 的正文 CSS；未修改 08、10、01、06，未调用 Provider、未采纳 Proposal、未建立 Revision/ScriptRelease/ProductionRun。正式 Provider 仍为 `gemini-3.7-flash (openai)`；费用未报告、cache unknown。

## 2026-08-21 正文阅读态 / 编辑态收束

- `web/app.js` 将已保存正文默认渲染为阅读态：类型标签、对白角色名和正文文字始终可见；点击段落后才进入编辑态并聚焦 textarea。新增段落仍直接进入编辑态，类型切换、输入同步、上移/下移、删除和保存继续读取原有 textarea 数据，未改变正文 API 或 Proposal → Revision 边界。
- `web/writing-workbench.css` 追加最终层叠规则，确保阅读态隐藏表单噪音、编辑态显示必要控件；对白角色名不再留出不可解释的空白列，动作/旁白保持对齐。桌面和手机都保持单一 Agent 消息滚动容器。
- 静态/HTTP 定向合同最终 `108 passed in 33.23s`；09 完整回归最终 `510 passed in 273.97s (0:04:33)`；`node --check web/app.js`、`node --check web/writing-workbench.js` 通过。
- 内置 Browser 按 16:9 `1440x810` 验收：8 个正文段落均为阅读态、textarea `display:none`、类型标签可见、页面宽度 `1440/1440`、Console warning/error `[]`；点击正文后该段进入编辑态且 textarea 获得焦点。`1920x1080`、`1366x768` 与 `390x844` 均无横向溢出；手机阅读态 8 段、Agent 消息滚动容器为 `1`、Console `[]`。
- 本轮只修改 `09-HaloCue-1.0-Writing/web/app.js`、`web/writing-workbench.css` 与 `tests/test_http_api.py`；未修改 08、10、01、06。未调用 Provider、未采纳 Proposal、未建立新的 Revision、ScriptRelease 或 ProductionRun；正式 Provider 仍为真实 `gemini-3.7-flash (openai)`，费用未报告、cache unknown。

## 2026-08-21 对白 / 旁白字体语气区分

- 根据截图反馈，正文阅读态不再只用深浅区分对白和旁白：对白正文切换到 `--font-ui` 无衬线台词字体，角色名使用同一字体并加重；旁白与动作保留 `--font-reading` 衬线叙述字体，并分别调整字距、字重和行距。手机端同步缩小字号，避免长对白造成横向溢出。
- 内置 Browser 新标签 `1440x810` 实测对白为 Noto Sans SC、17px、字重 520；旁白为 Noto Serif SC、16px、字重 450；`390x844` 对白/旁白均保持不同字体系统，页面宽度 `390/390`，Agent 消息滚动容器 `1`，Console warning/error `[]`。截图复查中对白视觉更紧凑、旁白更有叙述节奏。
- `node --check web/app.js`、`node --check web/writing-workbench.js` 通过；定向合同最终 `109 passed in 23.65s`；09 完整回归最终 `511 passed in 307.39s (0:05:07)`。
- 本轮只修改 09 的 `web/writing-workbench.css`、`web/index.html` 和相关合同测试；未修改 08、10、01、06，未调用 Provider、未采纳 Proposal、未建立新的 Revision/ScriptRelease/ProductionRun。服务仍为 `http://127.0.0.1:8910/`，Provider 为真实 `gemini-3.7-flash (openai)`，费用未报告、cache unknown。
## 2026-08-21 写作首屏信息减负

- 根据首屏截图复查，场景写作页不再把上下文、素材详情、素材建议和正文工具同时铺开。`writing-workbench.js` 将上下文保留为 Agent/上下文面板的次级入口，素材区收束为一行“X 项素材已准备 / 管理素材”，技术详情和本地建议不进入普通首屏；正文标题区移除重复的“查看上下文 / 生成候选”按钮，Agent 仍从右侧讨论入口进入。
- 首屏主路径现在是“当前场景 → 当前下一步 → 正文”；正式审查、素材选择、场景设定仍可通过原有入口访问，未删除业务能力或改变 Proposal、Revision、ScriptRelease、ProductionRun 边界。
- Browser `1440x810` 实测上下文卡不占主内容区，素材行约 `47px`，正文起点约 `363px`；手机 `390x844` 页面宽度 `390/390`，正文起点约 `497px`，无横向溢出，Agent 消息滚动容器为 `1`。两档 Console warning/error `[]`；16:9 首屏只保留“检查本场 / 继续讨论”作为当前场景的主要决策动作。
- `node --check web/app.js`、`node --check web/writing-workbench.js` 通过；定向合同 `66 passed in 11.04s`；09 完整回归最终 `511 passed in 266.11s (0:04:26)`。
- 本轮只修改 09 的 `web/app.js`、`web/writing-workbench.js`、`web/writing-workbench.css`、`web/index.html` 与相关合同测试；未修改 08、10、01、06，未调用 Provider、未采纳 Proposal、未建立新的 Revision/ScriptRelease/ProductionRun。服务仍为 `http://127.0.0.1:8910/`，Provider 为真实 `gemini-3.7-flash (openai)`，费用未报告、cache unknown。

## 2026-08-21 Composer 与场景切换收束

- 作品 Agent Composer 隐藏普通用户不需要的运行状态文字；权限入口保留为图标，展开后仍可选择审核协作。作品 Agent 侧栏的单段对话列表不再撑满整列，人物/设定/章节快捷入口压缩为窄底栏，减少左侧空白。
- 写作页切换场景不再在渲染时强制把 `.workspace` 滚动位置归零；保持现有位置后平滑滚到目标场景锚点。空场景编辑器不再使用 `360px` 最小空白，直接显示紧凑的“本场还没有正文”状态和顶部添加段落入口。
- Browser 移动视口 `403x898` 实测 Composer 运行文字 `display:none`、权限文字视觉隐藏、页面宽度 `403/403`；完整 09 回归最终 `513 passed in 278.65s (0:04:38)`；相关定向合同 `7 passed`，JavaScript/Python 编译检查通过。本轮只修改 09，未修改 08、10、01、06，未调用 Provider 或写入正式数据。桌面 16:9 与 `390x844` 本轮无可用视口切换/新标签证据，保留该证据缺口。

## 2026-08-21 单一章节正文流修正（最终证据）

- 章节正文是一张连续稿面，场景标题直接嵌入正文流；正文中间不再渲染第二套场景导航或独立场景大卡。当前场景只有一个编辑/保存表单，其他场景只读展示，Proposal → 用户决定 → Revision 边界不变。
- 左侧场景树是唯一场景入口。Browser `1280x720` 实测点击场景 2 后工作区 `scrollTop=804`，场景 2 标题距工作区顶部约 `18px`，URL、Agent 和当前场景同步；DOM 检查 `.chapter-manuscript-flow=1`、`.chapter-scene-nav=0`、`.chapter-scene-preview=0`、`#sceneManuscriptForm=1`，页面宽度 `1280/1280`。
- `node --check web/app.js`、`node --check web/writing-workbench.js`、`python -m compileall -q src` 通过；相关合同 `3 passed`；09 完整回归最终 `512 passed in 309.55s (0:05:09)`。本轮只修改 09，未修改 08、10、01、06，未调用 Provider 或写入正式数据；当前 Provider 仍为 Fake/模拟验收状态，真实费用与 cache 证据未报告。Browser 当前无可用 `390x844` 切换接口，手机视觉证据缺口保留。

## 2026-08-21 章节连续正文阅读流

- `web/app.js` 的 `renderDraft` 现在将当前写作章节的全部场景连续渲染在同一页：当前场景继续使用完整 `manuscriptMarkup`（编辑、保存、候选 Diff、审查与 Agent 作用域不变），其他场景使用只读正文预览；没有复制 `sceneManuscriptForm` 或建立第二套状态机。
- 新增本章场景导航与稳定锚点 `data-chapter-scene-anchor` / `#chapter-scene-{scene_id}`。点击“场景 1/2”会先沿用原有 `openScene` 与 `persistWritingTarget` 更新当前 Scene，再滚动到对应正文位置；Agent、上下文、审查随当前场景同步。
- 新增 `chapter-continuous`、场景导航、只读场景卡和对白/旁白/动作预览样式；移动端导航可横向滚动，正文无横向溢出。新增静态合同 `test_writing_draft_renders_a_continuous_chapter_with_scene_anchors`。
- 真实证据：`node --check web/app.js`、`node --check web/writing-workbench.js` 通过；相关定向合同 `4 passed`；09 完整回归最终 `512 passed in 276.63s (0:04:36)`。内置 Browser 当前 16:9 `1280x720`：章节导航、场景 1 正文和场景 2 空正文同页可见，点击场景 2 后 URL、Agent 标题、上下文与主操作切换到场景 2，页面宽度 `1280/1280`，锚点存在，Console error `[]`。本轮未伪造 390 视口证据；当前标签视口控制未提供可用切换接口。
- 本轮只修改 09 的 `web/app.js`、`web/writing-workbench.js`、`web/writing-workbench.css`、`web/index.html` 与 `tests/test_http_api.py`；未修改 08/10/01/06，未调用 Provider、未采纳 Proposal、未建立新的 Revision/ScriptRelease/ProductionRun。服务仍为 `http://127.0.0.1:8910/`，Provider 为真实 `gemini-3.7-flash (openai)`，费用未报告、cache unknown。

## 2026-08-21 连续正文滚动驱动场景同步

- 修复了“点击场景像切换网页”的根因：应用层场景树处理器不再 `render()` 或 `navigateToStage('draft')`，只对当前章节正文锚点执行平滑定位；移动场景抽屉选择后同样留在同一正文页。
- `writing-workbench.js` 新增节流滚动监听和阅读位置识别：以 `.workspace` 内 `data-chapter-scene-anchor` 判断当前场景，滚动到场景 2 时同步左侧 active 场景、当前场景正文编辑区、Agent/上下文/审查作用域和 URL；同步重绘后恢复原 `scrollTop`，不会跳回顶部。到达滚动底部时稳定选中最后一个场景，空正文不再制造额外页面。
- 内置 Browser 独立新标签 `1280x720` 实测：初始锚点 2 个、连续正文容器 1 个；滚动到页面底部后 `scene-3fe0047175da` 为 `.is-current`，左侧 active 同步为场景 2，URL 仍是同一 `section=writing&stage=draft` 页面，`scrollTop=942`；点击场景 1 后平滑回到场景 1，未发生整页导航。页面宽度 `1280/1280`，Console warning/error `[]`。
- `node --check web/app.js`、`node --check web/writing-workbench.js`、`python -m compileall -q src` 通过；相关静态合同 `3 passed`；09 完整回归最终 `514 passed in 279.04s (0:04:39)`。
- 本轮只修改 09 的 `web/app.js`、`web/writing-workbench.js`、`web/index.html` 与 `tests/test_http_api.py`；未修改 08/10/01/06，未调用 Provider、未采纳 Proposal、未建立新的 Revision/ScriptRelease/ProductionRun。服务仍为 `http://127.0.0.1:8910/`；最终 `/api/v1/health` 实际报告 `gemini-3.7-flash (openai)`、`can_call_model=true`，但本轮没有真实调用，因此真实 Provider/费用/cache 证据仍缺失。内置 Browser 本轮没有可用视口切换到 `390x844` 的接口，手机视觉证据缺口保留。
- 回归后补充未保存编辑保护：`manuscriptDirty` 时滚动不会自动切换当前场景，避免丢失未提交草稿；定向合同仍为 `3 passed`，09 完整回归最终 `514 passed in 305.04s (0:05:05)`。

## 2026-08-21 连续正文视觉与滚动稳定性修正

- 修复滚动到场景 2 时的跳跃感：滚动同步不再调用整页 `render()`，只更新场景树 active、正文锚点的阅读态标记、右侧 Inspector 和地址栏；连续稿面 DOM、编辑表单数量和 `scrollHeight` 保持不变。未保存正文时仍不会自动切换场景。
- 移除连续章节正文外层卡片边框、阴影和场景卡片感，场景标题仅作为轻量分隔；场景 2 不再看起来像下方新增了一套独立“正文框”。
- 内置 Browser 新标签 `1280x720` 实测：滚动前后 `#sceneManuscriptForm=1`、连续稿面 `scrollHeight` 不因场景同步改变；场景 2 active 自动同步，URL 保持同一 `section=writing&stage=draft` 页面，页面宽度无溢出，Console warning/error `[]`。截图复查确认章节正文为无外框连续稿面。
- `node --check web/app.js`、`node --check web/writing-workbench.js` 通过；相关合同 `3 passed`。只修改 09，未修改 08/10/01/06，未调用 Provider 或写入正式数据。
- 本轮完整 09 回归最终汇总：`514 passed in 305.98s (0:05:05)`。

## 2026-08-22 整章统一正文与 Agent 信息减负

- 写作正文继续保持单一章节稿面：本章 2 个场景共享一个连续正文流，左侧场景只负责平滑定位；滚动到场景 2 时只同步阅读锚点、左侧 active 与 URL，不重新渲染正文，也不清空章节上下文。普通页面不再提供“上下文 / 审查”右栏标签，只保留 Agent；内部场景合同、审查和上下文数据仍留在既有 API 与正式边界内。
- 修正右栏装饰逻辑残留的“本场 Agent”文案，统一显示“本章 Agent / 统一上下文”，避免用户误以为滚动场景会更换一套 Agent。当前场景仍保留唯一、默认折叠的正文编辑表单；Proposal 仍必须经用户决定后才能建立 Revision。
- 内置 Browser 实测 `1440x810`：`data-chapter-scene-anchor=2`、`#sceneManuscriptForm=1`、`.chapter-edit-tools=1`、可见 Inspector 标签仅 `Agent`。点击场景 2 后 `.workspace scrollTop=354`，当前锚点与 URL 更新，正文表单和阅读块数量保持不变，右栏仍为“本章 Agent / 统一上下文”，Console warning/error `[]`。
- `1920x1080`、`1440x900`、`1366x768`、`390x844` 均无横向溢出；手机 `.workspace` 恰好止于底部导航顶部（`bottom=790`），底部导航为 `790..844`，没有遮挡正文。定向连续正文合同 `5 passed`，`node --check web/app.js` 与 `web/writing-workbench.js` 通过。
- 完整 09 回归首次运行因系统临时目录无法建立测试夹具而得到无效环境结果；改用独立可写 `--basetemp=.pytest-run-20260822` 后最终 `515 passed in 345.18s (0:05:45)`。服务 `http://127.0.0.1:8910/` 健康，Provider 为 `gemini-3.7-flash (openai)`、`can_call_model=true`；本轮未调用模型，因此费用与 cache 仍无新增证据。
- 只修改 09 的 `web/writing-workbench.js` 与相关合同测试（以及追加本审计）；未修改 08、10、01、06，未采纳 Proposal、未建立 Revision、ScriptRelease 或 ProductionRun。

## 2026-08-22 Composer 视觉收束与正文手工编辑复验

- 修复作品 Agent Composer 权限入口在旧响应式规则下退化为单独 `!` 小图标的问题，入口现在固定显示可识别的“审核协作”文字；同时将 Composer 底部不透明遮罩扩大到 42px，滚动聊天时不会再从输入框下方透出下一行文字。
- 正文仍只有一张连续章节稿面，用户可点击“编辑正文”或任意正文段落，在原位置进入 textarea 编辑并保存，不增加第二层编辑窗口；继续沿用 Proposal → 用户决定 → Revision 边界。
- 证据：定向 UI 合同 `2 passed`，完整 09 回归最终 `516 passed in 461.03s (0:07:41)`；`node --check web/app.js`、`node --check web/writing-workbench.js` 通过。内置 Browser 16:9 `1280x720` 实测作品页权限入口宽 `93px`、文字字号 `11px`、页面横向溢出 `0`、Console warning/error `[]`；写作页仍为单一正文流，手工编辑入口可见，Agent 消息区保持单一滚动容器。
- 只修改 09 的 `web/writing-workbench.css`、`web/index.html` 与相关合同测试；未修改 08/10/01/06，未调用 Provider，未写入或采纳正式正文、Proposal、Revision、ScriptRelease、ProductionRun。服务 `http://127.0.0.1:8910/`；Provider 仍为 `gemini-3.7-flash (openai)`，费用未报告、cache unknown。

## 2026-08-22 正文段落间内联插入

- 新增正文段落不再依赖顶部或底部的三枚“加对白 / 加旁白 / 加动作”按钮。每个正文段落之间现在都有一个轻量插入缝隙，右侧 `+` 会在该位置直接插入一个空白段落并自动聚焦；空场景提供同样的“添加第一段”入口。
- 新段落默认以旁白形式创建，进入编辑态后仍可在段落自身的类型选择器切换为对白、旁白或动作；原有删除、上下移动和保存行为保留，移动时段落与其插入缝隙一起移动。正文保存仍是手工建立新 Revision，Agent 候选仍必须经过用户决定。
- 证据：`tests/test_http_api.py` 定向合同 `69 passed in 12.92s`；完整 09 回归最终 `517 passed in 321.53s (0:05:21)`；`node --check web/app.js`、`node --check web/writing-workbench.js` 通过。内置 Browser `1280x720` 实测 8 个段落对应 8 个插入点，点击第二段后的 `+` 后段落数为 9、新块位于第二和第三段之间、textarea 获得焦点、保存状态变为“未保存修改”；上移/下移后顺序和插入点数量保持稳定。`390x844` 实测无横向溢出，工作区底部 `790` 与移动导航顶部重合，Console warning/error `[]`。
- 正式 API 只读核对：健康 `ok=true`，作品版本 `115`，当前场景正文 Revision `revision-f7c4437b536c`、正文块 `8`，临时 Browser 编辑未写入正式数据。只修改 09 的 `web/app.js`、`web/writing-workbench.css`、`web/index.html` 与相关合同测试；未修改 08/10/01/06，未调用 Provider、未采纳 Proposal、未建立新的 Revision/ScriptRelease/ProductionRun。服务 `http://127.0.0.1:8910/`；Provider 仍为 `gemini-3.7-flash (openai)`，费用未报告、cache unknown。
## 2026-08-22 插入缝隙视觉状态收束

- 正文段落之间的插入条改为低干扰 affordance：默认只保留一条细线，桌面 hover/focus-within 时线条提高对比度并平滑加粗，右侧 `+` 从轻微位移中显现；不会改变插入条的固定高度，也不会造成正文滚动跳动。触摸/窄屏规则绑定 `max-width: 760px`，按钮保持低对比度但可触达，按下或聚焦时强化。
- 插入逻辑未改变：`data-manuscript-insert` 仍在原缝隙建立空白旁白段落，自动聚焦 textarea；移动、删除、保存和 Proposal → 用户决定 → Revision 边界保持不变。未新增第二套入口或状态机。
- 证据：`tests/test_http_api.py` 最终 `70 passed`；第一轮完整回归出现 1 个意图测试并发夹具偶发失败，单测重跑 `1 passed`，第二轮完整 09 回归最终 `518 passed in 333.48s (0:05:33)`；`node --check web/app.js`、`node --check web/writing-workbench.js` 通过。
- 内置 Browser `1440x810`：默认按钮 `opacity=0`、`pointer-events=none`，hover 后按钮 `opacity=1`、`pointer-events=auto`，线条 `scaleY(2.2)`；页面横向溢出 `0`，Console warning/error `[]`。`390x844`：插入条高度 `22px`、按钮 `opacity=.28` 且可触达，点击后段落数 `8→9`、新 textarea 自动获得焦点；横向溢出 `0`，Console `[]`。临时浏览器编辑未保存到正式 API。
- 本轮只修改 `09-HaloCue-1.0-Writing/web/writing-workbench.css`、`web/index.html`、相关静态合同测试；未修改 08、10、01、06，未调用 Provider、未采纳 Proposal、未建立新的 Revision、ScriptRelease 或 ProductionRun。服务仍为 `http://127.0.0.1:8910/`，Provider 仍为 `gemini-3.7-flash (openai)`；费用未报告、cache unknown。
## 2026-08-22 插入条激活态精修

- 根据 Browser 截图复现，修复激活插入条像“整条浅蓝胶带”的问题：移除细线的扩散 `box-shadow`，激活线保持 1px 高度并只用 `scaleY(1.6)` 提高对比度；右侧加号改为 28px 圆形轻量按钮，保留自己的浅阴影，不再使用横向矩形块。
- 鼠标移开后按钮恢复 `opacity=0`、`pointer-events=none`，线条恢复默认 1px；手机仍为低对比度可触达状态。插入位置、自动聚焦、保存和正式边界未改变。
- 证据：`tests/test_http_api.py` `70 passed`；09 完整回归最终 `518 passed in 302.09s (0:05:02)`；`node --check web/app.js`、`node --check web/writing-workbench.js`、`python -m compileall -q src` 通过。Browser `1440x810` 激活态无扩散阴影、线条 `scaleY(1.6)`、圆形加号，移开后恢复默认；`390x844` 按钮 `opacity=.28`、可触达，横向溢出 `0`，移动导航完整，Console warning/error `[]`。
- 本轮只修改 `09-HaloCue-1.0-Writing/web/writing-workbench.css`、`web/index.html` 与静态合同测试；未修改 08、10、01、06，未调用 Provider、未采纳 Proposal、未建立新的 Revision、ScriptRelease 或 ProductionRun。服务仍为 `http://127.0.0.1:8910/`，Provider 仍为 `gemini-3.7-flash (openai)`；费用未报告、cache unknown。

## 2026-08-22 长期稳定闭环计划最终核对

本轮按长期计划完成现有代码和正式入口的最终复验，没有新增第二套状态机，也没有把未完成的外部能力包装成成功：

- 09 最终全量回归：`527 passed in 310.59s (0:05:10)`；10 最终全量回归：`9 passed in 144.89s (0:02:24)`。
- `python -m compileall -q`（09/10）以及 `node --check`（`09/web/app.js`、`09/web/writing-workbench.js`、`09/web/production-embed.js`、`10/static/integration-shell.js`）全部通过。
- `GET http://127.0.0.1:8910/api/v1/health` 返回 `ok=true`、Dispatcher running、`last_error=null`、`ba-writing.productized/1.1.0` ready；当前 Provider 为 `gemini-3.7-flash (openai)`，`can_call_model=true`，但本轮未发起真实模型请求，因此没有新增 usage、费用或 cache 证据。
- 09 独立 `resource-catalog/1.0` API 实测 ready：背景 `2773`、角色 `941`、装束 `2085`、表情 `23916`、表情组件 `27`；基础库只读、用户覆盖层 `0`。查询结果仍保留来源迁移记录，普通 UI 不显示技术身份。
- 内置 Browser 复核 `1920x1080`、`1440x900`、`1366x768`、`390x844`：章节正文保持一个连续稿面，场景锚点为 `2`、正文表单为 `1`，页面横向溢出均为 `0`；手机工作区止于底部导航，Agent/Composer 不遮挡正文；Console warning/error 均为空。
- 10 同源 ShadowRoot 交接页实测 `1440x900` 与 `390x844`：交接摘要为“已送往 AA 制作 / 1 项素材已准备 / 刷新”，正文可见文本未包含 `Run`、`Revision`、`Copy`、`Reference`、`Hash`、`Schema` 等内部字段，ShadowRoot 和单页路由保持有效。
- `02-最终AA工程` 只读检查发现已有多个 `.aap` 文件和工程目录；当前没有可证明的现有 AA 安装能力门或空闲测试项目。本轮未覆盖、未安装、未创建伪工作区，正式 AA 安装保持外部边界阻塞。10 的安装回归仅使用隔离临时工作区，并验证重复安装拒绝和 ScriptRelease 不变。

六项目标当前结论：

| 目标 | 当前证据 | 当前结论 | 仍需补的证据 |
| --- | --- | --- | --- |
| 首次使用闭环 | 聚焦式六步引导、作品 Agent Proposal、场景正文/审查/发布合同与重启恢复测试 | 协议闭环已验证 | 真实 Provider 下的首轮质量与正式用户数据非破坏性验收 |
| 素材库接入场景写作 | 09 独立资源库、场景引用、`production-asset-handoff/1.0`、ProductionRun 任务副本回执 | 09/10 交接协议已验证 | 合法 AA 工作区的持久安装与回滚 |
| 真实 Provider 小规模纵切 | 健康接口显示真实 Gemini relay 可调用，协议和 Gate 有测试 | 本轮未调用，不宣称真实纵切新增完成 | 费用 receipt、cache hit/miss、真实网络故障恢复 |
| Agent 运行恢复 | 持久队列、租约、CAS、迟到结果丢弃、失败重试和四类恢复夹具 | 稳定恢复协议已验证 | 真实 Provider 429/504/超时的现场证据 |
| Revision、影响预览和审查 | Proposal/Diff/部分采纳、影响预览、Gate 失效、ScriptRelease 不可变和 10 读取合同 | 主链大部完成 | 关系图/时间线完整消费面及正式素材变化后的端到端复核 |
| 后续协作与规模化 | 未创建第二状态机或第二入口 | 按计划未启动 | 前五项目标和正式安装边界稳定后再规划 |

本轮结论：**09 + 10 的协议和稳定闭环已验证；ProductionRun/素材交接可在隔离工作区验收；正式 AA 安装因现有工作区非空且缺少能力门证据而阻塞。**

2026-08-22 移动写作导航与 Agent 面板收束：修复后置 CSS 覆盖导致的三个移动标签和隐藏 Agent 面板占位问题。移动端默认只显示“正文 / Agent”两个主视图；“审查”仍可由下一步动作进入，但不再占用首屏主导航。面板 `[hidden]` 现在始终 `display:none`，Agent 重新打开时只有一个内部对话滚动区；面板高度按 `100dvh - 330px` 计算，Composer 底部留在移动导航上方。正文阅读态在手机移除不可见的右侧操作列，旁白/动作不再保留空的说话人列，对白说话人列收紧为 `48–84px`，正文列获得更多宽度；切换增加 180ms 轻量进入反馈，并支持 `prefers-reduced-motion`。
- 真实证据：定向合同 `2 passed`；09 全量回归最终 `528 passed in 280.89s (0:04:40)`；`node --check web/app.js`、`web/writing-workbench.js` 与 `python -m compileall -q .` 通过（历史输出目录权限告警不影响编译结果）。内置 Browser `390x844` 实测默认可见标签 `2`、正文横向溢出 `0`；Agent 面板 `514px` 高，Composer 底部 `733px`，移动导航顶部 `790px`，无遮挡；`1920x1080`、`1440x900`、`1366x768`、`390x844` 四档横向溢出均为 `0`；Console warning/error `[]`。
- 本轮只修改 `09-HaloCue-1.0-Writing/web/writing-workbench.css`、`web/writing-workbench.js`、`web/index.html` 与 `tests/test_http_api.py`；未修改 08、10、01、06，未调用 Provider，未采纳 Proposal，未建立新的 Revision/ScriptRelease/ProductionRun。服务仍为 `http://127.0.0.1:8910/`；Provider 仍为 `gemini-3.7-flash (openai)`，本轮无新增真实费用或 cache 证据。

2026-08-22 场景定位与移动滚动维护性修正：修复 `app.js` 捕获监听抢走场景按钮事件、导致点击场景 2 无动作的问题。场景树和手机场景抽屉现在统一交给 writing workbench：不重建连续章节正文，只更新当前场景标记、URL 和持久写作位置，再平滑滚到锚点；后台运行刷新时通过 `_pendingChapterSceneScroll` 恢复目标位置。切换场景不再重建章节 Agent/上下文，继续使用统一章节上下文。手机锚点偏移自动避开“正文 / Agent”吸顶栏，场景标题不会被遮挡。
- 维护性整理：删除重复的移动 pane/EOF 覆盖，将 pane 高度、隐藏态、单一对话滚动区、Composer 和视图显隐规则收束到一个 authority 区段；资源版本更新为 `app.js?v=20260822-99`、`writing-workbench.js?v=20260822-62`、`writing-workbench.css?v=20260822-61`。
- 真实证据：定向合同 `5 passed`；第二轮完整 09 回归最终 `528 passed in 282.08s (0:04:42)`；`node --check web/app.js`、`web/writing-workbench.js`、`python -m compileall -q src tests` 通过。内置 Browser 实测桌面 `1440x900` 点击场景 1/2 后 URL 与 active 锚点同步，后台等待后场景 2 仍保持目标位置；手机 `390x844` 从场景抽屉选择场景 1 后对话框关闭、横向溢出 `0`，锚点顶部 `118.95px` 与吸顶栏底部对齐；四档视口横向溢出均为 `0`，Console warning/error `[]`。
- 本轮只修改 `09-HaloCue-1.0-Writing/web/app.js`、`web/writing-workbench.js`、`web/writing-workbench.css`、`web/index.html` 和 `tests/test_http_api.py`；未修改 08、10、01、06，未调用 Provider，未采纳 Proposal，未建立新的 Revision/ScriptRelease/ProductionRun。服务仍为 `http://127.0.0.1:8910/`；Provider 仍为 `gemini-3.7-flash (openai)`，本轮没有新增真实费用或 cache 证据。
## 2026-08-22 移动 Agent 滚动规则最终收束

- 清理 `web/writing-workbench.css` 中互相覆盖的移动 Agent 规则：移除旧的“页面滚动 owner”区段、重复的 pane 高度/Inspector 溢出声明，仅保留一个移动 authority。移动 Agent 面板现在由固定高度 pane 承载，历史消息是唯一内部滚动区，Composer 保持在 pane 底部；隐藏 pane 不再占据布局空间。CSS 资源版本更新为 `writing-workbench.css?v=20260822-63`。
- 更新相关静态合同测试，使其验证单一滚动 owner 和新资源版本，不再依赖已删除的旧 `height:auto`、`overflow:visible` 或 `100dvh - 340px` 规则。Proposal → 用户决定 → Revision、正文连续稿面和章节统一上下文均未改变。
- 证据：5 个定向合同最终 `5 passed`；09 完整回归最终 `528 passed in 299.25s (0:04:59)`；`node --check web/app.js`、`node --check web/writing-workbench.js`、`node --check web/production-embed.js` 与 `python -m compileall -q src tests` 全部通过。
- 内置 Browser 实测 `1920x1080`、`1440x900`、`1366x768` 和 `390x844`：横向溢出均为 `0`；桌面 Inspector 内容 `overflow:hidden`、Agent harness 高度随视口稳定；手机 Agent pane 约 `514px` 高、Composer 底部约 `733px`，没有被底部导航或正文遮挡；控制台 warning/error 均为 `[]`。1440x900 截图确认正文仍是一章连续稿面，右侧只保留 Agent 工作区。
- 本阶段只修改 `09-HaloCue-1.0-Writing/web/writing-workbench.css`、`web/index.html` 与相关合同测试；未修改 08、10、01、06，未调用 Provider，未采纳 Proposal，未建立新的 Revision、ScriptRelease 或 ProductionRun。服务仍为 `http://127.0.0.1:8910/`；当前 Provider 虽报告 `gemini-3.7-flash (openai)` 且 `can_call_model=true`，但本阶段没有新增真实 usage、费用或 cache 证据。正式 AA 工作区能力门仍按既有记录阻塞。

补充只读核对：10 集成全量回归 `9 passed in 159.44s (0:02:39)`；`GET /api/v1/health` 返回 `ok=true`、Dispatcher running、`last_error=null`、`ba-writing.productized/1.1.0` ready。10 未修改源码，Provider 本轮未调用。

## 2026-08-22 移动视图可访问性与响应式归位

- 09 写作页移动“正文 / Agent / 审查”标签现在使用完整 tab-panel 语义：标签带 `aria-controls`，动态面板为 `role=tabpanel` 并关联当前标签。正文、Inspector 和移动面板切换时同步设置 `aria-hidden` 与 `inert`，隐藏区域不会继续进入焦点顺序；恢复到桌面宽度时，Inspector 内容会从移动面板归位，避免响应式切换丢失内容。
- 新增窄屏断点变化监听，只在跨越 `760px` 时重新归位，减少无意义重绘；不改变章节连续正文、场景锚点、Agent 上下文或正式写入边界。
- 证据：定向合同 `2 passed`；09 全量回归最终 `528 passed in 289.42s (0:04:49)`；`node --check web/writing-workbench.js` 通过。内置 Browser 实测 `1920x1080`、`1440x900`、`1366x768`、`390x844`：横向溢出均为 `0`，桌面 Inspector 可见且内容未丢失；手机 Agent pane `514px` 高、Composer 底部约 `733px`、移动导航顶部 `790px`，无遮挡；控制台 warning/error `[]`。390 宽度下切换 Agent 后正文 `aria-hidden=true/inert`，Inspector `aria-hidden=true/inert`，面板 `role=tabpanel`；来回切换到桌面后内容归位，再回到手机仍可正常显示。
- 本阶段只修改 `09-HaloCue-1.0-Writing/web/writing-workbench.js` 与相关合同测试；未修改 08、10、01、06，未调用 Provider，未采纳 Proposal，未建立新的 Revision、ScriptRelease 或 ProductionRun。服务仍为 `http://127.0.0.1:8910/`；Provider 仍为 `gemini-3.7-flash (openai)`，无新增真实费用或 cache 证据。

## 2026-08-22 构思 Composer 顶部遮罩精修

- 根据内置 Browser 的手机截图复现，作品构思页固定 Composer 上方仍会透出上一条消息的浅色文字。`web/writing-workbench.css` 为 Composer 增加 20px 实体白色顶部遮罩，保留原有底部遮罩和 180ms 状态反馈，不改变聊天滚动、输入焦点或提交逻辑。资源版本更新为 `writing-workbench.css?v=20260822-64`。
- 证据：定向 Composer/UI 合同 `2 passed`；09 完整回归最终 `528 passed in 324.33s (0:05:24)`；三份写作 JavaScript `node --check` 通过。内置 Browser `390x844` 截图确认 Composer 上方残影消失，输入区和移动导航未遮挡；`1920x1080`、`1440x900`、`1366x768`、`390x844` 横向溢出均为 `0`，Composer 伪元素尺寸为 `20px/42px`，Console warning/error `[]`。
- 本阶段只修改 `09-HaloCue-1.0-Writing/web/writing-workbench.css`、`web/index.html` 与合同测试；未修改 08、10、01、06，未调用 Provider，未采纳 Proposal，未建立新的 Revision、ScriptRelease 或 ProductionRun。服务仍为 `http://127.0.0.1:8910/`；Provider 仍为 `gemini-3.7-flash (openai)`，无新增真实费用或 cache 证据。

## 2026-08-22 移动标签焦点恢复

- 实机复现发现移动写作页点击 Agent 标签后焦点落到 `body`：原因是捕获阶段为避免吸顶标签造成滚动跳动而阻止了默认鼠标聚焦，但切换完成后没有恢复焦点。现于移动面板挂载后用一帧轻量恢复当前标签焦点，正文分支继续保留原有滚动位置恢复。
- 证据：定向 UI 合同 `2 passed`；09 完整回归最终 `528 passed in 285.59s (0:04:45)`；`node --check web/writing-workbench.js` 通过。内置 Browser 实测 `390x844` 点击 Agent 后 `activeElement=writingMobileTab-agent`、`role=tab`、横向溢出 `0`；四档视口横向溢出均为 `0`，Console warning/error `[]`，视口已 reset。正文、Agent、审查路由和 Proposal/Revision 边界未改变。
- 本阶段只修改 `09-HaloCue-1.0-Writing/web/writing-workbench.js` 与合同测试；未修改 08、10、01、06，未调用 Provider，未采纳 Proposal，未建立新的 Revision、ScriptRelease 或 ProductionRun。服务仍为 `http://127.0.0.1:8910/`；Provider 仍为 `gemini-3.7-flash (openai)`，无新增真实费用或 cache 证据。

## 2026-08-22 自定义背景与 CG 类型隔离

- 场景素材选择器的“我的素材”查询现在始终携带当前槽位类型；背景只请求 `kind=background`，CG 只请求 `kind=cg`。前端加入候选时再次核对自定义素材声明类型；09 服务端保存场景引用时核对 `source_snapshot.kind`，不一致则拒绝且不提升作品版本。10 的既有交接校验继续核对真实自定义原件类型、版本和 Hash，类型错误不能进入 ProductionRun。
- 静态资源更新为 `writing-workbench.js?v=20260822-65`。定向 09 资源/场景/UI 回归 `30 passed`；08 自定义素材库只读回归 `7 passed`；10 素材交接定向回归 `5 passed`。完整 09 最终 `531 passed in 277.37s (0:04:37)`；完整 10 最终 `9 passed in 155.59s (0:02:35)`；JavaScript 语法与 Python compileall 通过。
- 内置 Browser 16:9 `1440x810` 实测“我的素材 / 背景”和“我的素材 / CG”保持独立当前槽位，背景页不显示 CG 候选；页面宽度 `1440/1440`、对话框横向溢出 `0`、确认按钮可见、Console warning/error `[]`。`390x844` 下 CG 槽位和“我的素材”均保持选中，对话框与页面横向溢出 `0`、确认按钮未被移动导航遮挡。正式自定义素材库当前为空，因此没有向正式库写入测试素材；错配拒绝由隔离服务测试覆盖。
- 本阶段只修改 09 的 `web/writing-workbench.js`、`web/index.html`、`src/halocue_writing/service.py` 与相关测试；未修改 08 或 10 源码，未调用 Provider，未改正文、资料、Proposal、Revision、ScriptRelease 或 ProductionRun。服务仍为 `http://127.0.0.1:8910/`；Provider 报告 `gemini-3.7-flash (openai)`、`can_call_model=true`，本阶段没有新增 usage、费用或 cache 证据。

## 2026-08-22 背景、CG 与自定义背景正式目录分型

- 1.0 资源迁移现在结合 `scene_visual_label.visual_kind`、已登记自定义背景和明确文件特征完成分型。普通背景查询只返回 `visual_kind=background`；`BG_CS_*` 漏标记录补归 CG，生成器文件名、纯数字、数字导出号和长十六进制文件名补归自定义背景。已有标题卡、特效和人工标签优先，不被兜底规则覆盖。所有记录继续留在 1.0 数据库和来源清单中，不删除追溯信息。
- 正式重建后的 2773 条视觉记录分为：普通背景 `1233`、CG `1044`、自定义背景 `380`、标题卡 `94`、特效 `22`；角色 `941`、装束 `2085`、表情 `23916`、表情组件 `27`，用户覆盖层 `0`。普通背景中 `BG_CS_*`、纯数字/数字导出号、长 Hash 文件名均为 `0`。API 实测 `BG_CS_Abydos_53`、`BG_CS_Abydos_06`、`DIFF_BG_7F3A91`、`00013-1885357390` 均返回空，`BG_GameDevRoom` 仍返回 5 条正常背景。
- 场景背景来源只保留“1.0 写作资源 / 我的素材”，CG 保持独立“AA 内置 / 我的素材”槽位。前端查询、结果渲染、加入引用和 09 服务端保存均校验当前槽位类型；10 的既有交接继续校验自定义原件类型、版本和 Hash。类型错配不会提升作品版本，也不会进入 ProductionRun。
- 空背景搜索不再先展示内部导出号和“未命名背景”，而是优先显示有可识别名称与语义标注的资源，并正常加载预览。素材弹窗改为候选列表独立滚动、确认区固定在底部；静态资源为 `writing-workbench.js?v=20260822-65`、`writing-workbench.css?v=20260822-66`。技术 key、来源版本、`visual_kind`、Hash 和引用身份继续保留在数据库、API 或折叠技术详情，普通选择面不直接展示。
- 两个 0.95 来源库始终以 SQLite `mode=ro` / `PRAGMA query_only=ON` 读取；导入前后 SHA-256 分别保持 `39D9B1B79DED5AB92B4B7BFFAEBD0A72EEBAA115F8CF1C9FF142EC5686573471` 与 `FC426DF2124493F73A80D85BE077608DF495E70D40405DB9635280401E4553C0`，文件时间戳不变。写入目标仅为 09 的 `data/resource-catalog/halocue-1.0.db`。
- 最终证据：定向资源/场景/UI 合同 `31 passed`；09 完整回归 `533 passed in 338.70s (0:05:38)`；10 完整联合网关回归 `9 passed in 156.64s (0:02:36)`。09/10 Python compileall、`node --check`（`app.js`、`writing-workbench.js`、`production-embed.js`、`integration-shell.js`）全部通过。
- 内置 Browser 实测 16:9 `1440x810`：CG 与自定义背景在背景搜索中为空，正常背景返回 5 条、预览图可见；`1920x1080`、`1440x900`、`1366x768`、`390x844` 的横向溢出均为 `0`，确认按钮始终可见，结果列表独立滚动，Console warning/error `[]`。正式自定义素材库当前无条目，因此未污染正式库制造正向样本；错配拒绝由隔离测试覆盖。
- 本阶段只修改 09 和证据文档；未修改 08 或 10 源码，也未写回 01。未调用 Provider，未修改正文、资料、Proposal、Revision、WorkCanon、ScriptRelease 或 ProductionRun。服务 `http://127.0.0.1:8910/` 健康，Provider 为 `gemini-3.7-flash (openai)`、`can_call_model=true`、Dispatcher running、`last_error=null`；没有新增 usage、费用或 cache 证据。
- 2026-08-22 构思页 Composer 底部白屏修复：移除桌面 `.work-agent-thread` 原先强制保留的 `132px` 底部空白，以及 Composer 上下 `::before/::after` 白色遮罩；Composer 改为贴合工作区底部，仅保留细分隔线，避免输入框悬空和正文末尾大块白屏。CSS 资源版本更新为 `writing-workbench.css?v=20260822-67`，相关静态合同同步更新。
- 真实证据：定向 Composer/章节合同 `2 passed`；09 完整回归最终 `533 passed in 362.27s (0:06:02)`；Python 编译和写作 JavaScript 语法检查通过。内置 Browser 复核 `1920x1080`、`1440x900`、`1366x768`、`390x844`：横向溢出均为 `0`，桌面正文末尾到 Composer 为约 `24px`、Composer 底边贴合 viewport，底部白屏为 `0px`；手机 Composer 位于移动导航上方且无内容遮挡；Console warning/error `[]`。
- 本次只修改 09 的写作 CSS、HTML 资源版本和相关合同测试；未修改 08、10、01、06，未调用 Provider，未写入正文、Proposal、Revision、ScriptRelease 或 ProductionRun。服务仍为 `http://127.0.0.1:8910/`；Provider 为 `gemini-3.7-flash (openai)`、`can_call_model=true`，无新增 usage、费用或 cache 证据。
## 2026-08-22 作品 Agent 用户状态投影与首屏减负

- 09 新增只面向普通界面的 `GET /api/v1/works/{work_id}/user-status`。它只投影当前主操作、待决定项、阻塞项、对话是否需要整理、失败运行是否可恢复和用户可理解的数量；不返回 Run ID、Revision ID、Hash、Schema、Provider 配置或内部参数。完整 `GET /works/{id}`、数据库、审计时间线和折叠“运行详情”继续保留技术追溯信息。
- 构思 Agent 首屏现在把“查看待决定内容 / 整理对话后继续 / 从失败位置恢复”等状态合并为一条紧凑的“当前下一步”；顶部不再向普通用户显示作品版本、后台任务数或待审查内部任务统计。主按钮只做页面定位，不采纳 Proposal、不建立 Revision，也不调用 Provider。
- 当前正式作品实测投影为：`1` 项候选等待决定、对话需要整理、存在可恢复失败；页面只显示对应用户语言。16:9 `1440x810` 与手机 `390x844` 横向溢出均为 `0`；桌面 Composer 底边贴合 viewport，手机 Composer 底边约 `788px`、移动导航顶部 `790px`，无遮挡；主操作可见并可跳到待审正文，Console warning/error 为 `[]`。
- 定向 HTTP/UI 合同最终通过；09 完整回归 `535 passed in 293.94s (0:04:53)`；10 只读联合回归 `9 passed in 203.49s (0:03:23)`。09 写作 JavaScript `node --check` 和 Python `compileall` 通过。
- 本阶段只修改 09 及证据文档；未修改 08、10、01、06，未调用 Provider，未采纳 Proposal，未建立新的 Revision、ScriptRelease 或 ProductionRun。服务为 `http://127.0.0.1:8910/`；Provider 仍为 `gemini-3.7-flash (openai)`、`can_call_model=true`、Dispatcher running、`last_error=null`，没有新增 usage、费用或 cache 证据。正式 AA 工作区能力门仍按既有记录阻塞。

## 2026-08-22 当前下一步语义路由与恢复投影修复

- 修复普通用户状态投影把所有待审 Proposal 都送到正文页的问题。`canon_fact`、`character_card`、`world_card`、`world_entity`、`world_rule` 现在返回“审查创作资料 / library_suggestions”；`scene_script` 返回“审查正文候选 / draft”；`brief_blueprint`、结构候选和记忆候选分别返回构思、结构或对应场景工作面。前端只按语义动作切换现有页面，不传 Proposal ID，也没有新增状态机。
- 修复历史失败运行长期污染首屏的问题：`failed_runs` 只在写作 Harness 判定最新固定输入仍可恢复时投影为 1；已被后续成功运行替代的旧失败仍保留在审计时间线，但不再显示为当前恢复动作。
- 证据：用户状态定向 HTTP 合同 `3 passed`；HTTP、Agent Presentation、Writing Harness 定向回归 `107 passed in 30.77s`；09 完整回归最终 `537 passed in 322.17s`；Python compileall 与实际存在的 `web/app.js`、`web/writing-workbench.js`、`web/shell.js`、`web/production-embed.js`、`web/agent-showcase.js` 均通过。内置 Browser `1440x810` 点击“审查创作资料”进入“资料 → 待整理建议”，横向溢出 `0`、单一“应用这项修改”主操作、Console warning/error `[]`；`390x844` 同样进入待整理建议，横向溢出 `0`，Composer/移动导航无重叠，Console `[]`。
- 真实服务 `http://127.0.0.1:8910/` 重启后健康：Dispatcher running、`last_error=null`、Provider `gemini-3.7-flash (openai)`、`can_call_model=true`。本阶段未调用 Provider、未采纳 Proposal、未建立 Revision/ScriptRelease/ProductionRun；未修改 08、10、01、06。10 继续只读核对，正式 AA 安装仍受现有工作区能力门阻塞。
- 补充只读证据：10 全量回归 `9 passed in 157.86s`；10 源码未修改，09 的普通用户状态投影没有改变 ScriptRelease、ProductionRun 或 AA 交接合同。

## 2026-08-22 首屏唯一主操作收束

- 作品 Agent 已确认资料展开区的“进入章节写作”只是快捷入口，降为普通次要按钮；当前状态投影的“审查创作资料”保留为首屏唯一可见主操作，功能路由不变。
- 最终证据：定向 UI/HTTP 合同 `5 passed`；09 完整回归最终 `537 passed in 269.61s`；`node --check web/app.js` 通过。内置 Browser `1440x810` 与 `390x844` 均只显示一个可见主按钮“审查创作资料”，横向溢出 `0`；桌面 Composer 底部贴合 `810px`，手机 Composer 底部 `788px`、移动导航顶部 `790px`，Console warning/error 均为 `[]`。视口随后已恢复默认。
- 本次仍只修改 09；未修改 08、10、01、06，未调用 Provider、未采纳 Proposal、未建立 Revision/ScriptRelease/ProductionRun。正式 AA 安装能力门保持阻塞。
- 入口缓存版本同步提升为 `app.js?v=20260822-105`；HTTP 合同 `77 passed`，五份实际前端 JavaScript 与 Python compileall 通过。仅改变静态资源版本，不改变业务状态或正式数据。

## 2026-08-22 0.95 r17 资源数据库同步

- 09 的独立 `resource-catalog/1.0` 已从 0.95 r17 的 `aa_assets.db`、`overlay-1-aa-assets.db` 和 `character_aliases.json` 只读同步；来源库以 SQLite `mode=ro` / `PRAGMA query_only=ON` 打开，未写回 0.95。同步脚本为 `tools/sync_resource_catalog.py`，迁移前备份为 `data/resource-catalog/halocue-1.0.db.pre-095-r17-sync-20260822.bak`。
- 同步后目录计数：普通背景 `1235`、CG `1044`、自定义背景 `378`、标题卡 `94`、特效 `22`；角色 `938`、装束 `2078`、表情 `23726`、表情组件 `0`；用户覆盖层 `0`。来源版本和迁移记录仍保留在 1.0 数据库/API，普通 UI 不显示内部 ID、Hash、版本或 manifest 技术字段。
- 新增 `resource_catalog.py` 提供角色规范名、偏好名、别名、骨骼键、manifest 状态、背景语义标注、表情 observation/backend/manual 标注及可选 AA manifest 身份覆盖；09 服务支持 `character_aliases_path` 与 `manifest_path`。资源选择仍只形成场景引用，不直接修改正文或正式资料。
- 证据：定向资源/HTTP 合同 `83 passed`；09 完整回归 `538 passed in 339.51s`；10 只读回归 `9 passed in 154.67s`；Python compileall 与 `web/app.js`、`web/writing-workbench.js` `node --check` 通过。服务 `http://127.0.0.1:8910/` 健康，Dispatcher running、`last_error=null`、Provider `gemini-3.7-flash (openai)`、`can_call_model=true`。
- 内置 Browser `1440x810`、`390x844` 均横向溢出 `0`、主操作可见、Console warning/error `[]`；未调用 Provider，因此没有新增真实 usage、费用或 cache 证据。未修改 08、10、01、06，未写入正文、Proposal、Revision、WorkCanon、ScriptRelease 或 ProductionRun；正式 AA 工作区能力门仍阻塞。

## 2026-08-22 AA 制作背景分类优化

- 09 的 ShadowRoot 嵌入适配层为 AA 制作素材库增加“场景背景 / 官方 CG / 自定义背景”三段用途控件。普通场景背景只读取 `backgrounds` 并排除官方 CG、生成器/数字导出名等自定义特征；官方 CG 与自定义背景只读取 `cg-backgrounds`，再按 `cg_source` 分开。背景请求选择器同步隐藏 CG 与自定义背景，提示用户从“插入 CG 段落”入口选择。
- 普通界面只显示用途、可读名称、预览和“当前任务可用”的简短说明；原始 key、来源、版本、Hash、ProductionRun 身份继续留在资源 API、快照和审计边界中，没有写回正文、资料或正式交接对象。适配层增加请求竞态接管，AA 原始素材请求晚返回时不会覆盖已分类列表。
- 证据：新增背景分类静态合同；09 完整回归最终 `539 passed in 344.78s (0:05:44)`；10 全量回归最终 `9 passed in 167.23s (0:02:47)`；`node --check web/app.js`、`node --check web/production-embed.js` 通过。
- 内置 Browser 实测 `1920x1080`、`1440x900`、`1366x768`、`390x844`：横向溢出均为 `0`，素材对话框横向溢出均为 `0`；场景背景、官方 CG、自定义背景可切换，列表分页不会恢复混合列表；Console warning/error `[]`。本轮只修改 09，未修改 08 或 10 源码，未调用 Provider，正式 AA 工作区能力门仍按既有记录阻塞。

## 2026-08-23 AA 制作成功态刷新状态栏清理

- 根据内置 Browser 截图复现，移除 AA 制作普通成功态顶部整条“已送往 AA 制作 / 素材已准备 / 刷新”交接状态栏。成功结果已经由当前“审查与安装”工作面表达，普通用户不再被重复状态和素材摘要挤占首屏；低频刷新保留为顶栏图标工具“刷新制作任务”。
- 不改变生产交接合同：ScriptRelease、ProductionRun、素材回执、资源副本和内部 API 仍由制作后端保留；本次只移除前端重复读取/展示层，不删除数据库、审计或正式技术字段。未建立新的 Revision、ScriptRelease 或 ProductionRun，也未采纳 Proposal。
- 证据：定向制作嵌入合同 `9 passed`；09 完整回归最终 `542 passed in 330.30s (0:05:30)`；`node --check web/production-embed.js`、`node --check web/app.js` 与 Python 编译检查通过。内置 Browser 使用 16:9 `1440x810` 和 `390x844`：桌面/手机横向溢出均为 `0`，成功态状态栏节点数量为 `0`，桌面刷新工具可见、手机按响应式隐藏，底部“编译 AA 工程”可见且未被遮挡；Console warning/error 均为 `[]`。
- 本阶段只修改 `09-HaloCue-1.0-Writing/web/production-embed.js`、`web/production-embed.css`、`web/index.html` 与相关合同测试；未修改 08、10、01、06，未调用 Provider，当前仍无新增真实 usage、费用或 cache 证据。服务为 `http://127.0.0.1:8911/`，此前正式主服务 `http://127.0.0.1:8910/` 的正式边界未改变。
2026-08-23 AA 制作工作台步骤式重组：在 09 的 ShadowRoot 嵌入适配层重排现有 08 DOM，将左侧制作流程移到工作区顶部横向步骤条；当前步骤保持单一主要工作面，审查路径说明移除。审查页增加只读背景时间线、桌面常驻剧情预览和移动端主动预览抽屉，预览通过现有 `/performance-preview` 合同按卡片同步，不修改草稿或复制 08 状态机。素材查询增加结果缓存、请求去重、背景切换过期请求取消和已有图片懒加载；素材工作台普通界面隐藏初始快照等技术来源文案，设置增加工作区/模型/渲染状态分栏与折叠技术详情。修改文件仅为 `09-HaloCue-1.0-Writing/web/production-embed.js`、`web/production-embed.css`、`web/index.html` 和 `tests/test_http_api.py`；08、10、01、06 未修改。
- 证据：定向嵌入/UI 合同 `11 passed`；场景 Agent/展示/纵切定向回归 `107 passed in 101.06s`；09 完整回归最终 `546 passed in 411.03s (0:06:51)`；10 完整回归最终 `9 passed in 197.46s (0:03:17)`；四份前端 JavaScript `node --check` 和 Python `compileall` 通过。服务 `http://127.0.0.1:8911/` 页面 HTTP `200`，`/api/v1/health` 健康，Provider 为 `gemini-3.7-flash (openai)`、`can_call_model=true`、Dispatcher running、`last_error=null`；本阶段未调用 Provider、未写入正文/资料/Proposal/Revision/ScriptRelease/ProductionRun 或 AA 工作区。
- 浏览器证据缺口：按要求尝试用 Codex 内置浏览器重新加载并读取 8911，但刷新/DOM 读取连续超时，浏览器控制会话重置；未取得本轮四档视口、横向溢出、焦点、遮挡或 Console 的真实新证据，因此不宣称 Browser 验收通过。上一轮背景分类和状态栏清理的既有 Browser 证据仍保留，但不能替代本轮视觉验收。

## 2026-08-23 AA 制作工作台运行时兼容与四档 Browser 验收

- 真实 Browser 复现了两处由 09 重组造成的兼容错误：审查操作替换时删除了 08 客户端仍需绑定的 `#openPerformancePreview`，并删除了 08 客户端仍会更新的 `#reviewFlowState`。09 现保留这些节点但隐藏，不重新显示内部流程说明；08、10 源码未修改。
- 修复后的嵌入 CSS/JS 资源版本为 `production-embed.css/js?v=20260823-7`，避免浏览器继续使用旧缓存。
- 桌面布局修正为步骤条位于工作区顶部；审查页的编译动作改为工作区流内的固定底部操作区，卡片列表和编辑区各自滚动，避免底部操作覆盖正文。手机端标题区不再因桌面 flex 基线产生大块空白；编译动作固定在移动导航上方且不重叠。普通展示中的 `scene` / `line` / `qa-model` 转为“场景”/“对白”/“可以使用”，技术字段仍留在 API、数据库和审计记录。
- 定向嵌入/UI 合同最终 `11 passed`；09 完整回归最终 `546 passed in 318.39s (0:05:18)`；10 完整回归最终 `9 passed in 165.10s (0:02:45)`；`node --check`（`app.js`、`writing-workbench.js`、`production-embed.js`、`shell.js`）和 09/10 Python `compileall` 全部通过。
- 内置 Browser 真实验收：`1920x1080`、`1440x900`、`1366x768`、`390x844` 均横向溢出 `0`；步骤条顶部可见，桌面剧情预览随卡片选择同步，移动端预览抽屉可打开/关闭且关闭后焦点回到“查看剧情预览”，编译操作与移动导航无重叠。审查页普通文本未发现 `run/revision/schema/hash/ProductionRun/ScriptRelease/scene/line/qa-model` 内部标识。最终刷新后的 Browser Console 无新增 warning/error；日志中仅保留修复前旧时间戳的两类错误。
- 服务地址为 `http://127.0.0.1:8911/`，页面 HTTP `200`，健康接口显示 Dispatcher running、`last_error=null`、Provider `gemini-3.7-flash (openai)` 且 `can_call_model=true`。本阶段未调用 Provider、未产生新增 usage/费用/cache 证据，未写入正文、资料、Proposal、Revision、WorkCanon、ScriptRelease、ProductionRun 或 AA 工作区。

## 2026-08-23 AA 制作步骤互斥与移动审查底部安全区修复

- 修复步骤式重组回归：`#page-review` 的布局规则只对 `.active` 页面生效，非当前步骤明确隐藏；四个制作步骤不再同时堆叠成长页面，原有 `data-stage`、事件绑定和 08 兼容节点保持不变。静态资源版本更新为 `production-embed.css/js?v=20260823-9`。
- 手机审查卡片列表增加 `76px` 编译操作安全区和 `scroll-padding-bottom`，最后一张卡可以滚到编译栏上方；编译栏仍位于移动导航上方。预览抽屉关闭后焦点回到“查看剧情预览”。
- 证据：制作嵌入定向合同 `10 passed`；09 完整回归最终 `546 passed in 313.04s (0:05:13)`；`node --check web/production-embed.js` 通过。内置 Browser 实际截图检查四个步骤的桌面和手机画面，覆盖 `1920x1080`、`1440x900`、`1366x768`、`390x844`，当前步骤互斥且横向溢出均为 `0`。手机第四步实测编译栏顶部约 `714.7px`、移动导航顶部 `790px`，卡片列表底部安全区 `76px`；Console warning/error `[]`。
- 本阶段只修改 09 的 `web/production-embed.css`、`web/index.html`、`tests/test_http_api.py`；未修改 08、10、01、06，未调用 Provider，未写入正文、资料、Proposal、Revision、WorkCanon、ScriptRelease、ProductionRun 或 AA 工作区。

## 2026-08-23 最新 0.95 offscreen-cache-fix 资源同步

- 09 使用现有 `tools/sync_resource_catalog.py` 将最新 0.95 `源码包-0.95-offscreen-cache-fix-20260823/aa/aa_assets.db`、`databases/overlay-1-aa-assets.db` 与 `character_aliases.json` 只读迁移到自有 `data/resource-catalog/halocue-1.0.db`；迁移前备份为 `halocue-1.0.db.pre-095-offscreen-cache-fix-20260823-141812.bak`。源库由 `mode=ro` 和 `PRAGMA query_only=ON` 打开，未写回 0.95。
- 最新来源 SHA-256 为主库 `02A9F5D0A33C91CA2529C4B6A3A55D943E8DAF74DE309879A785AF2F8F3CB1D3`、overlay `B3A0FE9FED54DA00A6B664DA978B2E92AD1853F4A80E747CB82FBC217F358EDE`、别名索引 `B07FA0527C53DB2C17A8C4375093A178D7CC3A0D7A95F5AACEE0E93923484EFF`；1.0 迁移记录保存来源文件名、版本和导入计数。
- 1.0 导入计数为背景 `2773`（普通背景 `1235`、CG `1044`、自定义背景 `378`、标题卡 `94`、特效 `22`）、角色 `938`、装束 `2078`、表情 `23726`、表情组件 `0`，用户覆盖层 `0`；中文背景分类和 `55` 组人物别名可直接查询，CG 与自定义背景没有混入普通背景查询。
- 09 Provider 解析层增加了对最新 0.95 平铺 `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens` 的兼容读取，同时保留 `prompt_tokens_details.cached_tokens`；仍使用 09 的 `provider-usage/1.0` 和 `cache_status`，不把未知响应变成命中证据。
- 资源定向合同与 HTTP 资源合同最终 `9 passed`；Provider 定向回归 `34 passed`；09 完整回归最终 `546 passed in 248.38s (0:04:08)`；10 完整回归最终 `9 passed in 130.74s (0:02:10)`。`python -m compileall -q src tools tests`、`node --check`（`app.js`、`writing-workbench.js`、`production-embed.js`、`shell.js`）通过。未复制 0.95 的 `annotation_agent.py`、`annotation_scene_planner.py`、`prompt.py` 或 AA 演出状态机。
- 0.95 新增的 cache telemetry 仍只属于 0.95 真实 Provider 响应；09 当前没有对应的真实调用证据，本轮未伪造 cache hit/miss、费用或 token。未调用 Provider，未修改正文、资料、Proposal、Revision、WorkCanon、ScriptRelease、ProductionRun 或 AA 工作区；08、10、01、06 未修改。
- 重启后的 09 服务 `http://127.0.0.1:8911/` 返回 HTTP `200`，健康接口显示 Dispatcher running、`last_error=null`、`ba-writing.productized/1.1.0` ready；资源目录 API 实测中文背景搜索、CG/自定义背景隔离和人物别名查询均正常。本轮没有 UI 代码改动，因此未新增 Browser 截图验收；既有四档 UI 证据仍有效。

## 2026-08-23 自行验收与移动审查操作条修复

- Browser 只读验收使用正式 10 集成入口 `http://127.0.0.1:8910/`，确认 `/integration/manifest` 为 `halocue-integrated/1.0.0+20260821.9`、写作由 09 持有、生产面以 ShadowRoot 挂载；8911 仅是 09 独立服务，访问 `/production/` 返回 404，不将其冒充完整集成入口。
- 发现并修复 09 制作嵌入层手机审查页的真实遮挡：`#page-review.production-review-ready .buildbar` 不再 sticky，改为页面流内操作条；卡片列表末尾可完整滚动，避免编译按钮覆盖最后一张卡。修改仅限 `web/production-embed.css`，资源版本仍为 `production-embed.css/js?v=20260823-9`。
- Browser 实测 `1920x1080`、`1440x900`、`1366x768`、`390x844`：正式 8910 页面和 ShadowRoot 横向溢出均为 `0`，步骤条位于顶部，当前步骤互斥；桌面审查预览随卡片选择显示，手机预览抽屉可打开；手机审查页编译条 `position=static`，位于卡片列表之后，移动导航保持在底部且不遮挡；Console warning/error `[]`。普通展示未发现 Run/Revision/Hash/Schema/Provider 参数；仅保留用户可懂的制作步骤、卡片和唯一编译动作。
- 自动化最终证据：09 定向制作合同 `14 passed`；移动审查条修复后的 09 完整回归最终 `546 passed in 288.59s (0:04:48)`；10 完整回归 `9 passed in 129.89s (0:02:09)`；`node --check`（`app.js`、`writing-workbench.js`、`production-embed.js`、`shell.js`）和 09 Python `compileall` 通过。
- 本轮只修改 09；未修改 08、10、01、06，未调用 Provider，未采纳 Proposal，未创建 Revision、ScriptRelease、ProductionRun，未安装 AA。健康接口显示 Dispatcher running、`last_error=null`、Provider `gemini-3.7-flash (openai)` 且 `can_call_model=true`；没有新增真实 usage、费用或 cache 证据。正式 `02-最终AA工程` 仍未通过合法、空闲、可写能力门，AA 安装继续属于外部边界阻塞。

## 2026-08-23 真实 Provider 最小讨论纵切

- 按用户明确授权，在正式 `http://127.0.0.1:8910/` 对当前作品主对话发起一轮真实请求，Provider 为 `gemini-3.7-flash (openai)`，`is_simulation=false`、`can_call_model=true`。请求明确限定为仅讨论三句话，不生成 Proposal、不修改正式资料、正文或发布版本。
- AgentRun `agent-a3b8674e8bc8` 于 `2026-08-23 18:29:36 +08:00` 创建并于 `18:29:46 +08:00` 完成；Provider 返回 `input_tokens=14531`、`output_tokens=273`，`cache_read_tokens=0`、`cache_write_tokens=0`，`estimated_cost=null`。费用未由 Provider 报告，不能自行推算；本次不把 `cache_read_tokens=0` 冒充 cache miss 证据。
- 返回内容为当前作品核心冲突、人物关系和下一步待确认问题；`proposal_id=null`、运行失败为空，正式正文、WorkCanon、资料、Revision、ScriptRelease、ProductionRun 均未改变。API/审计保留完整 Run、消息和 Provider runtime 技术字段，普通 UI 不需要显示这些字段。
- 本次只产生真实 Provider 调用证据，不代表 09/10 全链已由模型自动完成；没有采纳 Proposal、没有发布或安装 AA。`02-最终AA工程` 的合法、空闲、可写能力门仍未通过，正式 AA 安装继续属于外部边界阻塞。

## 2026-08-24 Agent 决策卡底部覆盖交互

- 09 对助手消息增加可选 `decision_card` 校验，有限选项必须为 2 至 6 项且 ID 唯一；普通文字问题保持消息形态。用户选择通过既有 `messages:enqueue` 发送并持久化 `decision_response`，不会直接建立 Proposal、Revision 或修改正文。Intent 确认和 Proposal 采纳/退回继续调用原有边界接口。
- 构思页将最新有限选项、待确认 Intent 和待审 Proposal 统一投影为 Composer 上方的绝对定位决策卡。打开时 Composer 为 `inert`；支持鼠标、方向键、Enter 和 Escape；关闭后输入框恢复焦点并保留“待决定”入口。修复入口被 Composer `z-index: 8` 覆盖的真实命中缺口，入口现在位于 `z-index: 21`，可见区域与点击目标一致。
- 最终静态资源为 `app.js?v=20260824-114`、`shell.css?v=20260824-43`。定向合同 `2 passed`；09 完整回归 `550 passed in 323.39s (0:05:23)`；10 只读回归 `9 passed in 214.15s (0:03:34)`；四个前端脚本 `node --check` 和 09 Python `compileall` 通过。
- 内置 Browser 在 `1920x1080`、`1440x900`、`1366x768`、`390x844` 实测：横向溢出均为 `0`；卡片 `position=absolute`，不推动对话高度；首次显示和重新打开后焦点均落到“确认继续”；关闭后 Composer 不再 inert 且焦点回输入框；“待决定”命中自身而非发送按钮。手机卡片底边 `788px`、底部导航顶边 `790px`；Console warning/error `[]`。
- 正式入口 `http://127.0.0.1:8910/` 已重启并加载上述资源。本轮未调用 Provider、未产生费用/token/cache 证据，未发送选项消息、未确认 Intent、未采纳 Proposal，未写入正文、资料、Revision、WorkCanon、ScriptRelease、ProductionRun 或 AA 工作区；08、10 源码未修改。

## 2026-08-24 普通选项卡真实交互补验收

- 新增隔离 Browser 夹具 `tests/in_app_browser_decision_card_fixture_server.py`：数据只写系统临时目录，Provider 固定为 `fake / local-rules`，可让第一次选项提交返回 503，以验证恢复路径；不连接真实 Provider 或正式作品。
- 内置 Browser 在 `1920x1080`、`1440x900`、`1366x768`、`390x844` 实测真正的两选项 `decision_card`。四档横向溢出和页面纵向溢出均为 `0`，卡片保持绝对定位、只有一个主操作且文字无截断；桌面卡片与视口底部间距约 `12px`，手机卡片底边 `788px`、底部导航顶边 `790px`，两者不重叠。Console warning/error 为 `[]`。
- 键盘实测覆盖 `ArrowDown` 选择第二项、向前与向后循环、`Enter` 提交和 `Escape` 收起。收起后 Composer 解除 `inert` 且焦点回到输入框；“待决定”点击命中自身；重新打开后仍选择第二项并恢复焦点。卡片开合前后工作区高度保持 `840px`，不会推动聊天布局或产生第二滚动条。
- 验收发现并修复一个真实状态投影缺口：普通选项提交成功后，旧助手消息的卡片仍会被当成待决定事项。前端现在根据后续用户消息的 `decision_response.message_id` 排除已回答卡片；刷新后卡片和“待决定”入口均为 `0`，Composer 可用。静态资源更新为 `app.js?v=20260824-115`。
- 成功提交持久化的审计元数据为原助手 `message_id`、`option_id=direction_b`、可见 `label=先定开场事件`，用户消息正文相同；Proposal 和 Revision 计数均保持 `0`。失败夹具第一次提交后决策消息、Proposal、Revision 均为 `0`，选中项和提交按钮保留；第二次重试成功且只新增一条普通决策回复。
- 最终证据：决策卡定向合同 `3 passed`，版本与移动合同补验收 `2 passed`；09 完整回归 `550 passed in 271.12s (0:04:31)`；10 只读完整回归 `9 passed in 212.23s (0:03:32)`；`node --check`（`app.js`、`writing-workbench.js`、`production-embed.js`、`shell.js`）和 `python -m compileall -q src tests` 均通过。两个临时夹具目录已删除，端口 `9320/9297` 已关闭；08、10 源码未修改，也未写入正式正文、资料、Proposal、Revision、WorkCanon、ScriptRelease、ProductionRun 或 AA 工作区。

## 2026-08-24 Proposal 决策卡边界补验收

- 新增隔离夹具 `tests/in_app_browser_proposal_decision_fixture_server.py`，创建两个未写入正式人物卡的 `character_card` Proposal：一个用于退回，一个用于采纳。Provider 固定为 `fake / local-rules`，数据只在系统临时目录中产生。
- Browser 发现 Proposal 候选详情内仍有一套“应用/退回”按钮，与底部统一决策卡重复。已在底部决策卡存在时隐藏详情区的重复操作，但保留候选字段、来源和影响预览；收起卡片后详情按钮仍不抢回首屏，用户通过“待决定”入口重新打开统一卡片。资源更新为 `shell.css?v=20260824-44`。
- 桌面 `1440x900` 与手机 `390x844` 均只有底部决策卡的一个主操作；横向和页面纵向溢出均为 `0`，手机卡片底边 `788px`、移动导航顶边 `790px`，Console warning/error 为 `[]`。Escape 收起、入口重开和焦点恢复正常。
- 退回路径：Proposal=`rejected`，人物卡 Artifact=`0`，Revision=`0`；采纳前同样为 Revision=`0`，明确点击“采纳”后 Proposal=`accepted`，只建立一个人物卡 Artifact，名称为“白露”，Revision=`1`。没有通过打开卡片或浏览候选触发正式写入。
- 最终证据：决策卡/版本/移动定向测试 `3 passed`；09 完整回归 `550 passed in 294.97s (0:04:54)`；10 只读完整回归 `9 passed in 185.86s (0:03:05)`；四份前端 JavaScript `node --check`、Python `compileall` 均通过。正式入口 HTTP/健康检查均为 `200` 并加载 `app.js?v=20260824-115`、`shell.css?v=20260824-44`；夹具端口 `2949` 与临时目录已清理。08、10 源码未修改，未调用真实 Provider，未写入正式作品或 AA 工作区。
