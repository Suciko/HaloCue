# Collaborator AI integration brief

Give the following instruction to the collaborator's coding AI. It is written
for the next implementation session, not as permission to copy every external
directory into HaloCue.

```text
你负责 HaloCue 的 BA 剧情编辑器集成。目标仓库是：

  D:\桌面\蔚蓝档案二创\HaloCue

远程仓库：

  https://github.com/Suciko/HaloCue.git

请先执行并阅读：

  git status --short --branch
  git switch feature/1.1-ba-editor
  Get-Content -Raw AGENTS.md
  Get-Content -Raw CONTEXT-MAP.md
  Get-Content -Raw contexts\ba-editor\CONTEXT.md
  Get-ChildItem docs\adr -File | Sort-Object Name

你的实现分支是 feature/1.1-ba-editor。跨模块 schema 或类型合同不要直接
改在本分支：先在 chore/contracts 建独立提交/PR，加入迁移、round-trip 测试
和消费者测试，再回到编辑器分支接入。所有成果通过 PR 进入目标分支，禁止
force-push、压缩包覆盖和直接复制文件交接。

研究输入的位置如下：

  Studio 1.11 解包研究：E:\Studio-1.11.0-win\learning-source\
  AzureArchive 行为研究：E:\AzureArchive_decompiled\
  ChatArchive 行为研究：E:\ChatArchive_decompiled\

这些目录是只读研究输入。请提取“行为、数据字段、资源角色、逻辑键、相对
路径、用户流程”形成自己的合同和测试，再独立重写实现。请不要把以下内容
放进 HaloCue：app.asar、node_modules、dist、生产 bundle、source-map 恢复的
源码、反编译源码、游戏资源、AssetBundle、数据库、音频、模型、字体、缓存、
用户绝对路径或生成压缩包。LingChat 是 AGPL-3.0，只能参考行为和架构，不能
复制代码。任何可复用的上游代码都必须先确认仓库 URL、不可变 commit 和覆盖
该文件的许可证，并在 PR 中保留版权/许可证信息。

目标目录映射：

  packages/project-model/  HaloCueProject 规范模型
  packages/contracts/     跨上下文 JSON/schema 合同
  apps/desktop-client/    Tauri/React 编辑器和预览界面
  services/halocue/       导入、校验、持久化和适配器服务
  contexts/ba-editor/     领域约束和术语
  docs/adr/                改变架构/许可证/格式时的决策记录
  docs/handoffs/           每次交付的 commit、PR、合同、测试和已知问题

产品不变量：

  HaloCueProject 是唯一正式剧情模型。
  StudioProject v2 只是 StoryForge/Studio 导入导出适配格式。
  AA 和 MMT 是同一剧情、变量、资源 ID 和存档状态的两种表现视图。
  AI 输出只能是 Proposal，用户采纳后才形成正式 Revision。
  真实 BA/AA 资源只能由用户授权的本地 resource-manifest 导入，公开测试使用
  合成资源。

请按纵向切片推进，而不是一次性“合并所有库”：

  1. 先检查 GitHub Issue #24，并为当前切片补充明确验收标准。
  2. 先实现一个可运行的 BA 场景：章节/场景/事件、稳定 ID、角色和资源引用、
     校验诊断、AA 预览；再增加高级节点图和 Studio 导出。
  3. 每个切片同时添加成功、错误、持久化/round-trip 测试；涉及 UI 时加
     Playwright 流程测试。
  4. 运行与改动匹配的测试、类型检查和格式检查，记录完整命令及结果。
  5. 创建 docs/handoffs/YYYY-MM-DD-<slice>.md，写明 commit、PR、修改的
     schema/合同、迁移、测试、已知问题、未完成 Issue 和待确认架构决定。
  6. 打开 PR 到 feature/1.1-ba-editor。不要直接合并 main。

完成标准：代码已放在正确的 HaloCue 目录，合同有版本和 round-trip 测试，
编辑器能消费 canonical HaloCueProject，公共边界检查通过，交接文档完整，
且外部研究目录保持不变。
```

## Current coordination record

- Target repository: `Suciko/HaloCue`
- Integration issue: [#24](https://github.com/Suciko/HaloCue/issues/24)
- Editor branch: `feature/1.1-ba-editor`
- Shared-contract branch: `chore/contracts`
- Resource contract: `packages/contracts/resource-manifest/1.0.schema.json`
- Research boundary: `docs/adr/0005-studio-1-11-research-boundary.md`

The maintainer should ask for the collaborator's PR URL and handoff before
reviewing or merging a slice. The public repository is not a staging area for
the unpacked Studio, AzureArchive, ChatArchive, or game resource directories.
