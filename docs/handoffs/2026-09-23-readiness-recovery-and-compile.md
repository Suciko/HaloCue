# 发布就绪：恢复与编译前置校验

## 操作事故与恢复

上一轮误执行 `git checkout -- legacy_adapter.py`，覆盖了既有未提交改动，导致 70 failed / 40 passed；这不是原有版本质量结论。
从本任务历史逐条提取该文件修改，在内存中以 HEAD 为基线重放（未重放其他文件或外部命令）。重建结果模拟历史误删后的 Git blob 为 `e2a852b14e3be8ba4c1cbaae7df8fc0494d071b0`，与误删后、checkout 前历史 diff 的 `e2a852b1` 完全匹配。补回已知被误删的原始块，原子恢复文件。
恢复前副本与重建过程在 `.scratch/adapter-recovery/`；恢复后原组合测试 **110 passed in 14.04s**。

## 真实缺陷修复

原 `resource_index_incomplete` 检查位于 AI 演出路径，并非编译路径。现在 `_create_compile_snapshot_locked` 在创建构建快照前检查任务冻结 AA 索引：文件存在、JSON 可读、四个顶层字段类型、emoticon/action 表类型。不生成资源、不回退全局/官方索引。

新增 `test_compile_resource_preflight.py`：修复前 **9 failed / 1 passed**，修复后与原组合 **120 passed in 16.12s**。异常不启动 job、不改变 run、不留下 input 快照；合法最小索引生成真实 AAP，冻结索引不变。

命令：`python -X utf8 -m pytest -q services/halocue/production/tests/test_compile_resource_preflight.py services/halocue/production/tests/test_service.py services/halocue/production/tests/test_background_import.py services/halocue/production/tests/test_preview_resource_root.py services/halocue/production/tests/test_handoff_idempotency.py`

## 隔离链路

`.scratch/verify_real_aa_chain.py` 成功：写作候选→显式采纳→审查→冻结 ScriptRelease→真实本地 HTTP handoff→角色映射→审查→异步编译→AAP。
这是 deterministic provider、空但结构完整 AA index、所有 speaker 映射旁白的格式链路，不代表真实模型质量、立绘/表情/CG、原生客户端播放或实际用户 AA 安装均已通过。
证据及 AAP 复制到工作区根目录 `output/2026-09-23-readiness/`，未操作正式作品。

## UI 实际观察

在隔离集成服务 8928 的内嵌浏览器打开已编译任务，看到“已编译（可安装）”，截图 `compiled-review-baseline.png`。
仍有问题：工具栏已选中第一张，但常驻预览仍显示“选择一张卡片”；另有“官方背景/官方快照”旧文案，与 AA-only 来源口径不一致。记录为待复现修复，未声称 UI 完成。

## 持续任务

完整 writing suite 已启动，日志 `.scratch/writing-readiness-current.log`，进程句柄 49283；本记录写入时仍运行，不能引用旧结果冒充此次通过。隔离集成服务句柄 87459，供后续截图验证。原生 AA 播放与打包发布验证未完成，目标保持 active。未提交、未推送、未发布。

## 后续验证：预览与写作回归

- 完整写作套件：`python -X utf8 -m pytest services/halocue/writing/tests -q --tb=short`，**1164 passed in 819.11s**，进程 49283 已退出（0）。日志已复制到根工作区 `output/2026-09-23-readiness/writing-suite.log`。
- 复现了重新打开任务、未配置全局资源索引时的预览失败：真实 HTTP 返回 `resource_index_not_configured`；前端 finally 又将错误覆盖成“选择一张卡片”。
- 后端预览现在允许明确的资源索引/图片缺失，不影响已有台词展示，其他未识别异常继续抛出；前端持久保存错误供统一 render 展示，加载新任务前清空旧预览。
- 后端新增恢复任务测试修复前 **1 failed**，修复后 `test_compile_resource_preflight.py + test_service.py` **93 passed in 15.16s**。
- 浏览器回归 `test_scene_background_preview_ui.py` **4 passed in 5.05s**：包含图片可用/缺失边界、请求失败保留错误、无图片仍显示台词，均检查无 pageerror、无写请求。
- `test_embedded_workbench_ui.py + test_full_background_library.py + test_ui_information_architecture.py` **62 passed in 39.19s**。
- 当前隔离服务使用 8929（句柄 81885；8928 仍是修改前的服务），内嵌浏览器已实际验证 1/7→2/7，同时选中卡、编辑面板和预览台词同步；截图 `compiled-review-preview-fixed.png`。
- 场景选择与审查中的“官方背景/官方快照”文案改为“AA 背景/AA 资源快照”，未改内部兼容标识或数据来源。

仍未验收：完整 production 套件、原生 AA 含立绘/CG 的实际播放、当前代码安装包、夜间写作待决卡层级；当前截图也显示审查页上方工具区域占据较多纵向空间，不能仅以预览恢复就宣称 UI 完善。

## 完整制作回归与当前代码打包

- 完整 production suite：**441 passed in 170.38s**，进程 90314 退出 0；证据复制为 `output/2026-09-23-readiness/production-suite.log`。
- Integrated suite 已启动，句柄 34628，日志 `.scratch/integrated-readiness-current.log`，尚未取得最终结果。
- 发现 `prepare_release.py` 按 Git index 导出而非工作树；首次 `build/readiness-20260923` 的成功构建属于旧暂存源码，**不能作为本轮修改验收，也不应交付**。
- 使用独立临时 GIT_INDEX_FILE（复制原索引，仅临时索引 git add 公开白名单文件）导出 `build/readiness-current-20260923/HaloCue`，没有改动用户暂存区，没有 commit/push。导出扫描通过。
- 逐文件核对 545 个文件与当前工作树匹配，其中 535 项仅 Git CRLF→LF 规范化；新增 AA-only 模块和当前 UI/服务修复均在导出中。
- 正确的当前工作树构建正在运行：句柄 **51647**，日志 `.scratch/build-worktree-current.log`。完成后对该路径的 EXE 运行 `tools/verify_integrated_release.py`（隔离数据、无 Python PATH、重启持久化），再进行兼容包验收；不要使用首次旧源码构建混淆结果。

## 当前安装包与集成测试结果

- 当前工作树包构建成功，`build/readiness-current-20260923/artifacts/HaloCue-1.0.0-windows-x64.zip`，SHA-256 `b69c68f0dc14bb1cca03f4fab775732ebb02e5b1b5ce541c1c0b4bde74199843`。仅本地候选，不是发布版本。
- 实际 EXE 验收：`tools/verify_integrated_release.py .../HaloCue.exe --screenshots ../../output/2026-09-23-readiness/packaged` 退出 0，返回 `ok:true, interface:integrated, launches:2, work_persisted:true`。截图与独立数据由验收脚本生成；未使用正式作品。
- archive 兼容验收正在运行，句柄 93262，日志 `.scratch/verify-archive-current.log`，尚未声明通过。
- 完整 integrated suite **4 failed / 37 passed in 116.44s**。四项在 `test_production_navigation.py`：works 侧栏拖动（两参数）、空工作台旧侧栏分界按钮可见性、共享导航前置状态断言。源码表明 works 宽度目前强制上限 260，但 limits() 仍宣告最高 480；测试从 224 拖动 60，实际只增长 36。这是需要进一步统一实际范围与无障碍范围的交互问题，不能仅改断言刷绿。
- 另外两项涉及旧 `.panel-divider-toggle-left` 与 `.work-user-status` 架构假设。需要用当前 `.agent-sidebar-toggle` 等可见入口验证折叠/展开、导航和 inspector 状态，再决定测试迁移或产品修复，尚未处理。
- 包启动成功不代表所有集成交互通过，也不代表原生 AA 播放通过。目标仍 active。

- archive 兼容验收句柄 93262 已退出 0，合成 AA 路径验收通过，console_errors=0，python_on_path=false；日志复制到根工作区 output/2026-09-23-readiness/packaged-archive-verification.log。此为合成编译/安装验证，仍非原生 AA 客户端播放。

## 侧栏交互修复

- 已核对当前 shell 实现：works 紧凑栏最大宽度 260、director 最大 300 是现有布局意图，但 limits() 仍上报 480，并按 writing 的 240 主区预算计算。现在键盘/鼠标/ARIA 统一采用各自设计最大值及 works 的 560 主区预算。
- `.agent-workspace.css` 隐藏旧左侧 divider 的规则原来适用于所有 works 页面。没有作品的空工作台并没有 `.agent-sidebar-toggle` 替代按钮，因而会失去展开入口。将该隐藏规则限定到 `.work-agent-stage`，保留空工作台原有控制。
- 测试迁移到 panels.v7、已有作品的可见 `.agent-sidebar-toggle`，保留折叠/展开/刷新保存/窄屏无横向溢出/共享导航/pageerror 验证；另新增 Home/End 与 aria-valuemin/max 对应实际宽度的验证。Inspector 在 works 默认收起，writing 保留独立展开测试。移除“用户状态区域必须不存在”的旧架构假设，改验收实际对话与输入区可见。
- `test_production_navigation.py` **15 passed in 79.62s**；shell JS syntax 和本轮 diff-check 通过。
- 集成完整 suite 重跑中：句柄 55583，日志 `.scratch/integrated-readiness-fixed.log`。
- 注意：之前成功的安装包包含预览修复，但不包含此次 shell.js / agent-workspace.css 修改；最终验收包须再次导出构建，不能把之前 EXE 成功算作此次 UI 已打包验证。

## 含侧栏修复的最终候选检查点

- 集成完整 suite：**41 passed in 121.70s**，`.scratch/integrated-readiness-fixed.log`。
- 从原始 2026-09-21 失败输出提取 21 个完整 nodeid，对当前代码逐项重跑：**21 passed in 0.26s**。未删除原始测试；当前断言清单导出到 `output/2026-09-23-readiness/21-regression-current-contracts.md`，用于语义覆盖审阅；不能仅凭静态字符串检查宣称实际 UI 完整验收。
- 独立临时索引导出包含侧栏修复的源码 `build/readiness-final-20260923/HaloCue`，全部公开文件与工作树逐一匹配（仅行尾规范化）。
- 构建成功：`build/readiness-final-20260923/artifacts/HaloCue-1.0.0-windows-x64.zip`，SHA-256 `162736be4199cff402eb10390d1828174252659e3b7082b5872e7fa3765fe935`。本地候选，无上传发布。
- 该 EXE 的 `verify_integrated_release.py`：退出 0，启动两次、作品保存通过；该 ZIP 的 `verify_release.py`：退出 0，console_errors=0，python_on_path=false。截图目录 `output/2026-09-23-readiness/packaged-final/`。
- 底层兼容完整 tests 套件正在运行：句柄 18280，`.scratch/root-readiness-current.log`。尚不能宣称其通过。
- 原生 AA 播放（授权真实资源、立绘/CG/老师选项）、夜间待决卡视觉仍未完成，保持明确未验证。没有修改正式作品、没有提交推送。

## 底层兼容回归结果及快照迁移

- 根 tests 全套结束：**2 failed, 1915 passed, 14 skipped in 247.84s**。两项均在 test_direction_profiles.py 的 standard_system 精确快照检查。
- 逐行 diff 确认仅两段新增素材约束：表情参考不是指令/角色与服装范围/持续策略、背景匹配不能改写正文或编造键。未修改其他提示词或规则 hash。此为此前已实施的素材标记使用需求，不是当前编译修复引入的差异。
- 手动把这两段明确文本插入 synthetic fixture，保留全文 equality、版本与规则 hash 检查；不以运行输出全量重写快照。`test_direction_profiles.py + test_resource_annotation_usage.py + test_annotation_memory.py` **43 passed in 0.51s**。
- 该次修改仅测试 fixture，不改变已验收候选包的可执行源码。根套件仍需修复后全量重跑，不能将以上窄测结果冒充全套通过。

## 夜间状态卡复现与修复

- 当前隔离作品真实页面复现 `.work-user-status` 仍是浅纸色背景、浅色标题，标题几乎不可读；并非仅旧截图缓存。
- 仅在 dark 主题中将该卡的背景、边框、标题、说明与警告接入现有主题 token；不隐藏用户下一步操作、不更改业务状态。
- 新增按生产 index.html 全部 CSS 实际顺序加载的浏览器颜色检查（1440×900、390×844）：背景相对亮度 <0.15，标题与说明对背景对比度 >=4.5。`test_ui_polish_layout.py` **5 passed in 6.04s**；diff-check 通过。
- 内嵌浏览器强制重新加载后目视确认恢复可读，截图 `output/2026-09-23-readiness/dark-agent-status-fixed.png`。
- 此为下一步状态卡验收，不冒充所有待决卡/弹窗均已验证。当前 dark CSS 修复晚于最终候选包构建，包需刷新该资源并重新验收；已有包通过不覆盖此改动。

## 本轮最终证据更新

- 修复快照后的根 tests 全套：**1917 passed, 14 skipped in 210.84s**，日志已留存 `output/2026-09-23-readiness/root-suite-final.log`。跳过不计通过。
- 夜间修复候选包：`build/readiness-night-20260923/artifacts/HaloCue-1.0.0-windows-x64.zip`，SHA-256 `42bd01ca8adf0468192e6e3a1222a695efda1a90e6f7365c1eb6189a2cb8b176`。
- 此包 EXE 验证和 ZIP 兼容验收均退出 0：两次启动作品持久化、无 Python PATH、合成编译/安装链路、console_errors=0。包内 theme.css/shell.js/agent-workspace.css 与当前源码一致（行尾规范化）；截图 `packaged-night/`。
- 新增空必填取消真实交互测试 desktop/mobile：两项通过，检查无 POST /works、无 pageerror、取消后 app 不保留 inert。首次测试误把无作品的 inline first-use 当成 dialog；改用明确的“已有隔离作品→作品切换→新建”路径验证真实 dialog，未修改产品来迎合错误夹具。
- 原始 21 项回归分类文件：`output/2026-09-23-readiness/21-regression-classification.md`。保留静态检查的证据边界，不宣称静态绿等于所有交互组合验证。
- 此次新增的是测试与记录，不改变已验收包的生产代码。尚需最终需求逐项审阅与剩余原生播放/待决卡边界说明，目标保持 active。

## 验收清单交付

最新 integrated suite（含取消表单）43 passed，句柄 39915 已退出 0。运行文件 262 项与夜间候选源码逐项匹配，ZIP hash 复核通过。交付总表与未验证边界见工作区 output/2026-09-23-readiness/ACCEPTANCE.md；原生 AA 实际播放、真实模型质量和签名发布明确未认证。
