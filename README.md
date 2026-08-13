# HaloCue｜AA 剧本自动演出工具

**HaloCue 0.9.2** 是一款面向
[AzureArchive](https://github.com/foxxlight/AzureArchive) 的 AA 剧本自动演出工具。它读取用户已经写好的中文剧本，安排表情、动作、站位、镜头、背景与声音，经过人工审查后编译为 AA 工程，同时帮助管理演员和素材。

现版本的 AI 用于提出演出标注，不负责创作或改写剧本正文；用户始终可以在编译前逐项审查和修改结果。

这是第三方项目，与 AzureArchive 作者、Nexon、Yostar、NAT Games 和
Esoteric Software 均无隶属关系。HaloCue 不提供游戏资源，也不授予任何第三方素材的使用权。

## 下载与开始

普通 Windows 用户下载 `HaloCue-0.9.2-windows-x64.zip`：

1. 完整解压 ZIP，不要直接在压缩包里运行。
2. 双击 `HaloCue.exe`。
3. 双击 `HaloCue.exe`，程序会直接打开独立应用窗口，不会启动系统浏览器。
4. 首次使用时，在应用内选择你自己的 `AzureArchive.exe`；HaloCue 会读取 AA 设置并自动识别项目和存档位置。
5. 按“导入剧本 → 确认演员 → 审查 → 编译”完成一章。

**Windows ZIP 不需要安装 Python。** 更完整的非技术说明见
[使用说明-从这里开始.md](使用说明-从这里开始.md)。

## 发布版本边界

| 版本 | 可以包含 | 明确不包含 |
|---|---|---|
| 公开源码 | HaloCue 原创代码、文档、品牌图标、已脱敏标签数据库 | Spine、游戏资源、个人配置、密钥、创作稿、生成物、个人骨骼 |
| 公开 Windows ZIP | HaloCue、运行所需依赖、公开源码中的脱敏数据 | Spine、游戏资源、个人文件、个人骨骼 |
| 私发覆盖包 | 公开版内容，以及获得明确书面授权后逐文件核准的 Spine 程序文件 | 个人骨骼、图集、纹理、音频、游戏资源、激活信息、配置和日志 |

**个人骨骼、个人素材和作品在任何版本都不得包含。** 私发不等于可以转发专有软件；没有覆盖接收人的明确书面授权，就不能制作或发送带 Spine 的私发覆盖包。详情见
[私发版说明](docs/private-release.md) 和
[Spine Editor 官方许可](https://esotericsoftware.com/spine-editor-license)。

公开版不包含 Spine。未配置 Spine 时，普通的剧本导入、审查和编译仍可使用；只有需要渲染或分析自备骨骼的功能会提示配置 Spine 路径。

## 数据保存位置

HaloCue 不会向解压目录写入个人状态。配置、数据库、缓存、草稿和输出统一保存在：

```text
%LOCALAPPDATA%\HaloCue
```

升级前先退出 HaloCue，再复制这个文件夹即可备份。需要干净地重新配置时，先退出程序，把该文件夹重命名为 `HaloCue-backup`，再启动；确认新配置可用后再决定是否保留旧备份。

## 从源码运行

源码支持 **Python 3.10–3.13**。建议使用虚拟环境：

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m pip install pywebview
.\.venv\Scripts\python launcher.py
```

检查环境但不启动：

```powershell
.\.venv\Scripts\python launcher.py --check
```

常用启动参数见 [命令与语法](docs/commands.md)。开发测试依赖位于
`requirements-dev.txt`。

## 使用流程

- 导入 `.txt` 或 `.md` 剧本。推荐一行一个角色，并用 `##` 分隔场景。
- 确认旁白、无立绘角色和演员映射。
- 可选择 AI 演出标注，也可以只做确定性格式转换。
- 在审查页处理缺失素材和诊断，确认后再编译。
- 生成结果写入用户数据目录；选择安装时再复制到自己的 AA 工作区。

示例：

```text
## 场景一：商店街，午后

旁白: 商店街人声嘈杂。
老师: 久等了。
凯伊: ……你为什么要把「普通」说得那么不普通。
```

推荐一行一个角色，并在旁白中写清真实动作和位置变化。标点应表达实际语气，
不要为了触发演出而机械堆叠省略号或感叹号。AI 生成后仍要进入审查草稿，
逐项确认表情、动作、镜头和素材引用。

高级标注语法、镜头指令和文字样式见 [docs/commands.md](docs/commands.md)，
演出建议见 [docs/direction.md](docs/direction.md)。

## 自定义素材与 Spine

自定义背景、音效和人物骨骼始终由用户自己提供，并复制到自己的 AA 项目中。每章保留独立副本，HaloCue 不建立跨工程的运行时链接。

导入人物时可选择包含骨骼、图集和纹理的目录，并填写 AA 中登记的真实
`Identifier`。如果你合法安装了兼容版本的 Spine，可在设置中明确选择其命令行程序路径；HaloCue 不会扫描其他磁盘上的个人安装，也不会上传这些文件。

## 模型与密钥

模型不是“仅转换格式”的必需项。使用 AI 功能时，在设置页建立模型配置并先运行连接测试。API Key 应放在环境变量或 Windows 凭据管理器中，不要写进仓库、截图或发布包。

## 开源许可

**MIT 许可证只适用于 HaloCue 原创代码。** 依赖库、AzureArchive、Blue Archive、Spine、用户素材和生成作品仍由各自权利人及许可约束。完整清单见
[LICENSE](LICENSE) 和 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 维护者

公开导出、扫描和上传步骤见 [UPLOAD.md](UPLOAD.md)。安全问题请按
[SECURITY.md](SECURITY.md) 私下报告。版本变化见 [CHANGELOG.md](CHANGELOG.md)。
