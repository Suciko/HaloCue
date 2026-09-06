# HaloCue 1.0 源码交接摘要

更新时间：2026-08-22

这份说明面向协作者，描述当前工作树中 1.0 的真实代码边界、运行方式和已验证状态。代码以 `09-HaloCue-1.0-Writing` 为写作域；`10-HaloCue-1.0-Integrated` 只做集成网关和制作交接。`08-HaloCue-1.0`、`01-完整程序`、`06-安卓端` 不属于本轮修改范围。

## 1. 运行入口

09 是一个标准库 HTTP 服务，不依赖单独的前端构建步骤：

```powershell
cd 09-HaloCue-1.0-Writing
$env:PYTHONPATH = (Resolve-Path .\src).Path
python -m halocue_writing.server --port 8910
```

默认数据目录是 `09-HaloCue-1.0-Writing/data`，可以用 `HALOCUE_WRITING_DATA_DIR` 覆盖；制作服务地址由 `HALOCUE_PRODUCTION_URL` 指定，默认是 `http://127.0.0.1:8892`。当前统一入口是 `http://127.0.0.1:8910/`。

10 的入口是 `10-HaloCue-1.0-Integrated/src/halocue_integrated/server.py`。它启动集成网关、写作上游和制作上游，并提供同源 ShadowRoot/单页交接。10 当前会只读加载既有制作域适配器；不要在 10 复制写作 Proposal、Revision、Gate 或上下文状态机。

## 2. 09 后端结构

- `src/halocue_writing/server.py`：ThreadingHTTPServer 启动器，创建 `WritingService`、恢复 Dispatcher，并挂载静态前端。
- `src/halocue_writing/app.py`：HTTP 路由、请求解析、错误结构和静态资源响应。
- `src/halocue_writing/service.py`：领域用例总编排，包括作品/章节/场景、正文保存、Proposal、审查、发布、素材引用、ProductionRun 回执和恢复入口。文件较大，修改前先定位现有用例，不要新增第二套状态机。
- `src/halocue_writing/repository.py`：SQLite 持久化、不可变 Revision/Artifact、附件、运行记录、幂等事务和 CAS/版本检查。正式正文和资料必须通过这里创建新 Revision，不能原地覆盖。
- `src/halocue_writing/writing_harness.py`：从 Artifact、Proposal、AgentRun、WorkItem、Gate 和 ScriptRelease 推导用户下一步；普通 UI 应使用它的用户语义，不直接铺内部字段。
- `src/halocue_writing/agent_dispatcher.py`：持久队列、租约、心跳、重试、取消和迟到结果丢弃；输入快照变化时拒绝旧任务恢复。
- `src/halocue_writing/providers.py`、`model_settings.py`：Provider 激活、固定配置摘要、真实/模拟边界和用量能力声明。Fake 只用于协议测试，不能当作真实模型证据。
- `src/halocue_writing/scene_readiness.py`、`workflow_pack.py`、`ba_skill_runtime.py`：场景运行前置检查、不可变 WritingPack 和 BA 写作规则投影。
- `src/halocue_writing/resource_catalog.py`、`official_reference_catalog.py`：独立的 `resource-catalog/1.0` 资源目录。背景、CG、自定义背景、角色、装束、表情和组件在 1.0 自有 SQLite 中查询；0.95 仅作为迁移来源，运行时不打开、不写回。
- `src/halocue_writing/story_import.py`、`aap_import.py`、`ba_world_card_import.py`、`ba_character_card_import.py`：TXT/DOCX/小说结构、`.aap` 只读解析和 BA 资料导入。导入结果先是草稿/Proposal，不覆盖正式作品。
- `src/halocue_writing/proposal_impact.py`、`commit_projection.py`、`current_projection.py`：影响预览、Revision 后派生索引和待办。派生读模型不是事实源，失败时回退正式 Revision。
- `src/halocue_writing/conversation_summary.py`、`document_context.py`、`memory_store.py`：长对话摘要、上下文边界和长期记忆 Proposal。摘要不是 WorkCanon，只有用户确认的资料才进入正式上下文。
- `src/halocue_writing/release_integrity.py`、`agent_presentation.py`、`agent_tools.py`：发布不可变性、Agent 用户摘要和受控工具注册。公开 thinking 只能来自 Provider 的 `reasoning_summary`，不暴露隐藏思维链。

## 3. 前端结构

- `web/index.html`：入口 HTML 和资源版本号。
- `web/app.js`：作品/构思、资料、素材、发布、AA 交接等页面渲染和用户动作；普通界面已把 ID、Hash、Run、Schema、Provider 参数等技术字段移出主操作面。
- `web/writing-workbench.js`：章节连续正文、场景锚点、正文/Agent 移动标签、单一对话滚动区、场景同步和 Composer 行为。场景切换只滚动到同一章正文锚点，不刷新页面、不重建章节上下文。
- `web/writing-workbench.css`：写作稿面、对白/旁白字体区分、响应式布局、内联 Diff、移动导航和 Composer。当前 `writing-workbench.css?v=20260822-68` 已删除 Composer 上下白色遮罩和桌面 132px 底部占位；Composer 贴合窗口底部，保留细分隔线，并为作品 Agent 的用户状态引导提供紧凑移动布局。
- `src/halocue_writing/app.py` / `service.py`：新增 `GET /api/v1/works/{work_id}/user-status` 用户状态投影。普通界面只读取当前下一步、待决定/阻塞/整理/恢复提示和可理解计数；完整作品 API、数据库和折叠运行详情继续保留审计字段。投影按最新待审 Proposal 类型返回资料候选、正文候选、结构或构思工作面，历史失败只有 Harness 判定仍可恢复时才显示为首屏恢复动作。
- 作品 Agent 的资料展开区“进入章节写作”是次要快捷入口，不再使用 `primary` 样式；普通首屏只保留用户状态投影提供的唯一主操作。
- `web/index.html` 当前入口资源为 `app.js?v=20260822-105`，用于确保协作者不会继续命中旧首屏缓存。
- `web/styles.css`、`shell.css`、`tokens.css`、`shell.js`：全局壳层、设计 token 和导航。
- `web/production-embed.js`、`production-embed.css`：10 交接页面的同源嵌入；普通交接只显示“已送往 AA 制作 / 素材已准备 / 刷新”等用户状态，技术追踪留在 API/折叠详情。

## 4. 正式领域边界

1. Agent 输出只能是 Proposal 或审查 Finding。
2. 用户决定后才能建立正式 Revision；场景素材选择只建立引用，不改正文。
3. ScriptRelease 冻结后不可变；ProductionRun 只读消费发布合同并回传可验证的素材副本回执。
4. 10 不得直接改正文、资料、WorkCanon 或写作状态；AA 安装必须经过现有能力门。
5. 资源基础库只读；用户修正进入覆盖层。背景、CG 和自定义背景按 `kind` 隔离，错配会被前后端拒绝。

## 5. 测试和当前证据

```powershell
# 09
cd 09-HaloCue-1.0-Writing
python -m pytest -q

# 语法/编译
python -m compileall -q .
node --check web/app.js
node --check web/writing-workbench.js
node --check web/production-embed.js

# 10
cd ..\10-HaloCue-1.0-Integrated
python -m pytest -q
```

当前最终 09 全量回归：`537 passed in 269.61s (0:04:29)`；本轮未修改 10，10 只读回归为 `9 passed in 157.86s (0:02:37)`。内置 Browser 最终复核 `1440x810` 和 `390x844`：资料候选主操作能进入“待整理建议”，作品首屏只显示一个主按钮，横向溢出为 `0`，Composer/移动导航不遮挡内容，Console warning/error 为空。此前四档桌面/手机视口证据仍有效。

当前 `/api/v1/health`：`ok=true`、Dispatcher running、`last_error=null`、`ba-writing.productized/1.1.0` ready；Provider 报告 `gemini-3.7-flash (openai)`、`can_call_model=true`。本轮没有发起真实模型请求，因此不能声称新增真实 usage、费用或 cache 证据。

正式 AA 工作区 `02-最终AA工程` 已做只读能力核对：已有多个 `.aap`/工程目录，未取得合法安装能力门和空闲测试工程证据，因此正式安装保持外部边界阻塞；不要覆盖已有工程或创建伪工作区。

## 6. 协作注意事项

- 先读根 `CONTEXT.md`、`UBIQUITOUS_LANGUAGE.md` 和 09 正式文档，再改代码。
- UI 修改优先补静态/HTTP 合同，再用内置 Browser 检查桌面和 `390x844`；不要用外部 Playwright、raw CDP 或伪造截图。
- 只修改 09；只有明确授权时才改 10。08、01、06 默认只读。
- 修改后更新资源版本号，避免浏览器使用旧缓存。
- 重要阶段把真实测试、服务、浏览器视口和未完成证据追加到 `docs/six-goal-evidence-audit.md` 与根 `CONTEXT.md`，不要覆盖历史记录。
