# 2026-08-25 导入采纳与 0.95 兼容验收

## 本轮完成

- 增加 `.aap` 与 TXT/DOCX 的正式采纳接口：
  - `POST /api/v1/imports/aap:adopt`
  - `POST /api/v1/imports/story:adopt`
- 采纳前仍要求明确 `confirm: true`；预览和暂存不会写入正式作品。
- 采纳后创建新的 Work、Volume、Chapter、Scene 和 `scene-blocks/1.0` 正文 Revision。
- 原始导入文件和解析预览继续保存在 `data/imports/`，并通过 `staged_imports` 记录来源哈希、状态、作品 ID 和幂等结果。
- 相同导入编号重复采纳不会创建第二个作品；源文件变化会被拒绝。
- 0.95/0.9 兼容适配器从 `pyproject.toml`、`halocue_meta.py` 或 `VERSION` 检测实际 checkout 版本，能力接口不再硬编码为 0.9.3。

## 验证

- `services/halocue/writing`: `581 passed`
- `services/halocue/production`: `86 passed`
- `services/halocue/integrated`: `9 passed`
- 0.95 最新远端 `origin/migration/mainline-0.95-official`（已 fetch 到 `f63d660`）导出临时 checkout 后运行素材/资源验收：`51 passed`
- `node --check`：`app.js`、`writing-workbench.js`、`production-embed.js`、`shell.js` 全部通过
- Python `compileall` 和 `git diff --check` 通过
- 全量 `ruff check` 仍受本分支既有问题阻塞（writing 78 项、production 9 项，主要是旧文件的导入顺序、未使用变量和单行多语句）；本轮没有用格式化或大范围清理覆盖协作者修改。

## 边界与剩余风险

- 0.95 真实 checkout 作为适配器输入和验收来源，不复制进 1.0；1.0 仍使用自己的数据库和覆盖层。
- 0.95 分支公开仓库不包含用户真实 `aa_assets.db`、个人资源和 AA 工程，因此本轮不能声称完成真实用户素材库或真实 AA 客户端安装验收。
- `.aap` 的无法识别节点仍在预览警告中，需要用户/Agent 补充；不会伪造恢复结果。
- 当前工作区包含本轮之前的未提交 UI/服务修改；本 handoff 不代表可以回退或覆盖这些变更。

## 下一步

在具备授权的真实 0.95 资源数据库和 AA 工作区后，使用 `HALOCUE_LEGACY_ROOT` 指向对应 checkout、使用隔离 `HALOCUE_DATA_DIR` 运行一次完整 ScriptRelease → ProductionRun → 编译/安装验收；不要把个人数据库或资源提交到 GitHub。
