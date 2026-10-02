# HaloCue 1.0.0 合作者源码验收包 — 2026-09-26

- kind: handoff; scope: current HaloCue 1.0.0 integrated source; status: completed for source review delivery
- 用户要求先验收，再提供可转交合作者的源码程序、进入入口、审查清单和审查流程。
- 分支 `codex/1.0-release-readiness-20260914`，未提供独立Issue，不新增公开Issue/PR；不提交或推送继承的脏工作树。
- 依据：AGENTS、CONTEXT-MAP、backend/client CONTEXT、产品方向、ADR-0006及远程协作协议。
- 本包是脱敏的工作树验收快照（包含未提交的新功能），不是可覆盖合作者Git工作树的同步包；须解压到独立目录。正式协作仍以审查后的提交/PR为准。

## 计划
1. 运行集成写作/制作全服务回归，记录通过与失败边界，不扩新产品功能。
2. 提供Windows源码启动入口：独立环境和独立审查数据、默认模拟模式、动态本机端口、明确日志与停止方式，不依赖维护者绝对路径或7179旧进程。
3. 提供可重复生成的源码验收包与敏感数据扫描，保留许可证/来源；排除私有配置、用户作品、原作资源、缓存、备份和旧源码快照。
4. 从实际交付ZIP解压到新目录，验证全新环境启动及内部浏览器主流程；交付起步说明、逐项审查表、问题记录模板和已有验收证据。

## 完成与证据
- 新增 `开始验收.cmd`、`requirements-review.txt`、`tools/review_start.py`：独立 venv/data，清除继承的 HALOCUE／模型私有环境配置，本机动态端口，`--empty`、`--check`、`--stop`。
- 新增 `tools/review_fixture.py`：原创虚构样例；三个场景分别覆盖待复查、未变化、尚未检查。只在空目录首次运行时建立。
- 新增 `tools/build_review_bundle.py`：显式工作树快照，含未提交／untracked 功能；保留基线提交、逐文件清单和归档校验。扫描有发现时拒绝打 ZIP。
- 文档入口 `START_REVIEW.md`，流程清单、问题模板、如实验收报告位于 `docs/review/`。源码 ZIP 不是 Git 同步包，不覆盖开发分支。
- `python -X utf8 -m pytest services/halocue/writing/tests services/halocue/production/tests services/halocue/integrated/tests -q --tb=short`：1899 passed / 16 failed，1618.29s。完整失败列表／分类随验收报告交付，不声称全绿。
- `python -X utf8 -m pytest tests/test_review_bundle.py services/halocue/writing/tests/test_settings_hub.py -q --tb=short`：36 passed，21.09s。
- Ruff：仅本次验收工具／测试，check 通过。
- CMD 从中文／空格路径解压包创建干净 CPython 3.12.7 venv 后成功启动；内部浏览器亲验人物／世界卡、草稿往返、新建作品、修改影响／复查、正文保存、帮助检索、本地反馈、深浅主题和390宽度；console error/warn为空。
- 恢复原验收数据后样例不重复、两个作品和已保存正文保留；`--stop` 返回0且服务退出。
- 未做真实模型/真实AA/原生EXE更新专项。模拟候选不足的人工步骤没有计为通过。另记录等待任务被归为后台运行的P2易用性问题。
- 未触碰7179正式进程／真实作品；仅测试由本轮创建的服务。无提交／推送／Issue／PR，本轮只交付可独立检查的源码快照。
- 首次源码扫描发现：历史机器路径文档（排除）、一条测试用合成密钥外形字符串（改成普通测试标识）、非品牌验收截图（留在交付目录外，不打入源码）。未放宽扫描器。

- 打包工具追加中文归档名回归：SHA 校验文件使用 UTF-8，避免中文包名导致最后一步写入失败。

## 最终归档
- 交付文件：最终改为 `HaloCue-1.0.0-协作者验收-20260926.zip`；product manifest 明确为 HaloCue 1.0.0；旧的无版本名归档不再发送。
- SHA-256：`c69cea132444b76d8a0020b52f64734710d9f4c9d285da45c28c17cefcdf2f7e`。
- 最终ZIP另行完整解压，逐文件大小／SHA与manifest一致，ZIP CRC通过；再次由CMD建立全新venv并成功启动，内部浏览器确认只有一个新样例，error/warn为空；`--stop`已确认正常退出。
- 最终本地交付目录位于项目交付物的 `2026-09-26-collaborator-review/最终交付/`。不要发送候选目录、测试数据、完整回归原始日志或早期不完整归档。

- 纠正用户反馈：最终交付明确标记为 HaloCue 1.0.0；不是把 0.95 作为交付版本。0.95 只保留在兼容迁移与历史版本线中。

## Complete 1.0 package follow-up — 2026-09-26
- Built current-worktree Windows package `HaloCue-1.0.0-windows-x64.zip`; release scanner passed after removing PyInstaller `direct_url.json` provenance and tightening the scanner against CSS class names that begin with `sk-`.
- Desktop artifact: 1002 files, ZIP SHA-256 `e66a24e497cfb44c45af605c517d693ce7cd6c82da9682f56ef47bc6cf323244`.
- EXE check with isolated fake AA workspace returned `ok=true`, `startup_ready=true`; EXE integrated server was started with a dynamic port, opened in the internal browser, and stopped through the authenticated local shutdown route.
- Current focused verification: 59 passed / 1 skipped across release scanner, desktop release, public docs, and collaborator source bundle tests. The historic broad service run remains 1899 passed / 16 failed and is not re-labeled as green.
- The final combined handoff contains the Windows runtime ZIP, source review ZIP, hashes, and the explicit 0.95 compatibility boundary. No 0.95 private assets, user projects, keys, Spine, or game resources are included.
