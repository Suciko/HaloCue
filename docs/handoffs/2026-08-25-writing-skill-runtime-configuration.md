# 2026-08-25 WritingPack 运行时配置

## 已完成

- 当前 Windows 用户已配置 `HALOCUE_BA_WRITING_SKILL_DIR`。
- 配置指向本机授权的完整 `ba-writing` 来源，不把来源文件复制进 Git 仓库。
- 来源包含 16 个必需文件，`SKILL.md` SHA-256 为
  `23b036af8cb94c0c7ef638057b915aafd92cdeb1ca73eb8290c58601d3ff212a`。
- 来源与隔离验收使用的 WritingPack 文件逐文件哈希一致，WritingPack 来源摘要为
  `7059aecc3a7a7f5426239137580a8562f311ea7c39a6712d0a7420b60616dd76`。

## 运行时证据

- 正式集成入口已启动：`http://127.0.0.1:8910/`。
- `GET /api/v1/health`：`ok=true`、Dispatcher running。
- `ba_writing_skill.status=ready`，`missing_files=[]`，`configured_by=HALOCUE_BA_WRITING_SKILL_DIR`。
- 当前 Provider 仍是本地模拟 Provider；本次只配置 WritingPack，不改变模型配置或正式作品数据。

## 边界

- Skill 来源只读，运行时会编译为不可变 WritingPack 快照。
- 不把本机绝对路径写入协作协议；其他机器需要设置自己的
  `HALOCUE_BA_WRITING_SKILL_DIR`，并以健康接口为准检查完整性。
- 真实 Provider 仍需单独完成模型激活和小规模调用验收；本次没有产生新的模型费用。
