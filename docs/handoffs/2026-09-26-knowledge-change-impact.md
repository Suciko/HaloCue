# 设定修改影响追踪 — 2026-09-26

- kind: handoff; status: implemented and isolated acceptance complete; live restart pending; scope: 1.0 writing local workbench
- 用户批准继续；本轮仅做资料变更到场景复查的闭环，不扩张剧情模拟器或全应用自动改写。
- 分支 `codex/1.0-release-readiness-20260914`；未提供专属 Issue，沿用当前用户任务，不擅自新建公开Issue/PR。
- 依据：产品方向、backend/ba-editor CONTEXT、ADR-0006；沿用Proposal→人工采纳→Revision边界。
- 开始时已fetch；大量继承脏改动全部保留，不清理/重置/提交/推送。

## 计划与验收
1. 复用场景稳定选用ID和既有scene-review-input快照，新增只读knowledge-change-impact/1.0投影；没有基准或不可读时如实报告，不凭名称命中判断正文矛盾。
2. 只在现有卡片“修改影响预览”和场景上下文增加折叠式信息，定位具体场景并复用本场检查。不自动调用模型或改变正文/资料/发布门禁。
3. 回归已选/未选/同名/归档/未确认/世界集合无关条目/过期或损坏检查快照，以及跨作品和异步UI状态。
4. 合成隔离数据在内部浏览器验收桌面和390px，真实用户作品只读。

## 已知运行边界
7179在上轮结束时仍运行旧后端；重启命令曾被策略拒绝。本轮不绕过该拒绝，新增能力须由能力握手识别，不向旧服务发送新接口请求。

## 验收中发现的问题（定位中）
一次窄屏回归复查后仍显示待复查。优先验证：①现有场景导航持久化writing_target与立即复查竞争，expected_version过期；②滚动时选中场景变化，通用按钮检查了另一场；③异步报告晚到覆盖。先记录网络错误、实际检查scope与局部面板，不增加等待时间掩盖问题。

## 已完成
- 新增只读 `knowledge-change-impact/1.0` 合约及 GET `/api/v1/works/{work_id}/knowledge-impact`。一个一致数据库读事务内比对当前正式人物／世界卡与最近一次完成的本场检查，校验快照内容哈希、场景／正文修订与同作品卡片身份。
- 状态区分尚未检查、待复查、资料未变化、检查基准不可读取；解释新增／撤出／归档或未确认资料。只列字段标签，不把整份资料复制到报告。
- 固定选用按稳定ID，兼容范围按既有Brief角色与已确认世界卡规则；名字出现在场景标题或正文里不构成自动关联。WorldBible无关条目变化不会误报本卡变化。
- 卡片既有“修改影响预览”升级为按需读取，可定位具体场景。新入口复用正文检查区的一条折叠“资料变更检查”；没有新增主导航。原“本场上下文”在精简布局中被有意隐藏，因此没有强行展开整个选择器。
- 报告检测到变化后，不再继续用本场“已检查”标识暗示当前资料已核对；提示复查，但不改变后端Gate或发布权限。
- 显式“重新检查本场”复用原检查服务。报告展开／刷新不调用模型；未保存卡片阻止跳走，未保存正文阻止复查，错误为局部可重试，已冻结定稿不重写。
- 新增能力握手；旧后端不会请求新接口。不加外部依赖或数据库迁移，不改变历史检查快照。

## 本轮定位并修复的两类实际问题
1. 进入场景会异步保存既有 `writing_target`。立即复查可能携带保存前的作品版本。用真实HTTP路由暂停writing-target复现：旧代码提前发出scene.review请求。改为等待已有 `writingTargetSavePromise`，并重查原作品、场景、正文修订及未保存状态。加入回归，不靠延长超时解决。原模型／审查接口不变。
2. 老世界观快照可能未包含可选 `participant_character_ids`，手动保存补出空数组。比对时将缺省与空数组等价，避免“没改人物关联却报变化”。内部浏览器发现后加入专门测试。

临时诊断日志已移除。中途测试选择器重名（反馈表单也有summary）、写作位置artifact计数与路由先unroute后continue的测试释放顺序问题已修正；失败尝试不计作通过。

## 测试证据
- 最终主要新增与相邻回归：
  ```text
  python -X utf8 -m pytest services/halocue/writing/tests/test_knowledge_change_impact.py services/halocue/integrated/tests/test_knowledge_change_impact_ui.py services/halocue/writing/tests/test_proposal_impact.py services/halocue/writing/tests/test_card_assistance.py services/halocue/integrated/tests/test_card_assistance_ui.py -q --tb=short
  ```
  **44 passed in72.97s**。含桌面／390px、字段变化到复查闭环、同名ID、无关世界卡、归档和未确认、缺基准／损坏基准、作品隔离、服务重开、正文改动、兼容选用、optional空数组、局部503重试、草稿防丢失及导航保存竞态。
- 相邻纵向／UI矩阵：
  ```text
  python -X utf8 -m pytest services/halocue/writing/tests/test_vertical_slice.py services/halocue/writing/tests/test_scene_detail_polish.py services/halocue/writing/tests/test_reference_details_ui.py services/halocue/writing/tests/test_library_editor_flow_ui.py services/halocue/writing/tests/test_writing_responsive_shell.py services/halocue/integrated/tests/test_experience_surface_matrix.py -q --tb=short
  ```
  **135 passed in139.54s**。
- 新增4个Python文件 `ruff check`、`ruff format --check`，新模块及service/app `compileall`，app.js和knowledge-impact.js的 `node --check`，本轮叠加的已跟踪文件 `git diff --check`：通过。
- 没有跑全仓库发布验收，不将这些通过数解释成历史测试债务或所有真实环境问题已解决。

## 内部浏览器真实操作
使用Codex内部浏览器web control，隔离临时服务／合成资料／模拟Provider，无付费或外部模型请求：
- 桌面1280：从白露人物卡展开影响预览，看到两个关联场景（一个待复查、一个尚未检查），没有按标题误选另一场；定位夜访档案室，查看知情边界及世界观定义变化，显式复查后显示资料未变化。
- 390px：世界卡手改未保存定义，跳场景被阻止且草稿保留；保存新修订后显示关联场景待复查；定位场景并复查，结果更新。深色／浅色截图可读，document.scrollWidth=innerWidth=390，页面error/warn为空。
- 最终后端另开隔离实例复核世界卡字段标签。没有强制显示隐藏上下文面板；新增入口默认折叠，从卡片跳转才展开。
- 实际验收库三份正文仍各只有1个修订；两次复查未改正文。正式参考库 `work-3c40d9c813ae` 与上轮保存的修订基线逐项一致：版本29、28份人物资料。

## 变更文件
新增：
- `services/halocue/writing/src/halocue_writing/knowledge_change_impact.py`
- `services/halocue/writing/web/knowledge-impact.js`
- `services/halocue/writing/docs/contracts/knowledge-change-impact-1.0.schema.json`
- `services/halocue/writing/docs/knowledge-change-impact.md`
- `services/halocue/writing/tests/test_knowledge_change_impact.py`
- `services/halocue/writing/tests/in_app_browser_knowledge_impact_server.py`
- `services/halocue/integrated/tests/test_knowledge_change_impact_ui.py`
叠加小改动：writing service.py / app.py、web/app.js / index.html / authoring-ui.css。与本轮开始的本地检查点对比确认，没有混入其他改造。authoring-ui.css在开始前就是未跟踪文件，保留其已有内容。

## 边界与交接
- 本轮只是已保存人物／世界观卡的依赖和字段变更提示，不做语义矛盾判定；证据文件、世界规则、时间线、作品事实仍由原完整审查负责。
- “资料未变化”不等于发布通过，有检查阻塞时仍显示阻塞提示；既有Gate为权威。场景导航原本就会保存writing_target，不能把它误认成报告改变正文。
- 7179的运行进程仍未加载新后端（已只读核验能力缺失）；延续上轮限制，不绕过重启拒绝。正常重启原服务后即可启用，不需迁移数据。此轮未发布安装包。
- 仍没有提交、推送、PR或数据清理，保留全部继承改动。可按本文件的范围作小型人工代码审查。

## 最终收尾
- 导航竞态修复后的场景详情、场景消息和资料编辑入口终检：`python -X utf8 -m pytest services/halocue/writing/tests/test_scene_detail_polish.py services/halocue/writing/tests/test_scene_message_ui.py services/halocue/writing/tests/test_library_editor_flow_ui.py -q --tb=short` → **38 passed in36.01s**（与135组部分重叠，不叠加成虚假的独立测试总数）。
- 浏览器390px临时覆盖已重置，隔离验收页已关闭，两个自建临时服务器已停止；正式7179预览未被终止或改配置。
- 最终JS语法、Ruff与本轮已跟踪文件diff检查通过，未提交/推送。
