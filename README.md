# AA 剧本编译器

把纯文本剧本编译成 [AzureArchive](https://github.com/) 的 `.aap` 工程文件，跳过全部手工点击。

> 第三方工具，与 AzureArchive 作者、Nexon、Yostar 均无隶属关系。
> 不分发任何游戏资源，使用者需自备 AzureArchive 及其素材库。
> 工程格式由公开数据逆向分析得出，仅用于互操作。

---

## 普通用户：双击启动

回到 `AA自动写剧本文件` 总目录，双击：

`启动AA自动写剧本.cmd`

它会自动检查 Python、程序文件、素材数据库和 AA 工作区，然后打开网页。程序打不开时双击同目录的 `检查运行环境.cmd`。完整的非技术说明见 [使用说明-从这里开始.md](使用说明-从这里开始.md)。

黑色窗口是本地服务，使用期间请保留；关闭窗口即可停止程序。

### 首次连接 AA 安装与官方资源

打开网页右上角的“设置”，在“AA 安装与资源”中选择 `AzureArchive.exe` 或 AA 安装目录。程序会自动显示当前 `projects`、`saves` 和官方资源包状态。资源包已安装但“图片预览”显示尚未建立时，点击“建立图片预览”。

程序只读取每位用户自己安装的 AA 程序、设置和资源包。生成的缩略图只保存在本机 `out/official-previews`，不会修改或上传 AA 的 EXE、配置、AssetBundle、工作区文件或时间戳，也不会随发布包分发。

常见状态的处理方式：

- **所选程序无法识别**：重新选择 `AzureArchive.exe` 或它所在的安装目录。
- **工作区有效，但资源包尚未安装**：可以继续使用 projects；需要官方图片预览时，先在 AA 中安装资源包，再回到设置页检查状态。
- **图片预览需要更新或部分可用**：资源包更新后重新建立索引；“部分可用”表示可用图片已经建立，个别损坏资源已跳过，可直接使用或稍后重试。

## 开发者：命令行启动

```bash
python aapaths.py                 # 确认能找到你的 AA 存储目录
python label_assets.py --init     # 建素材库（扫一遍你的 AA）
python launcher.py --check        # 与一键入口相同的环境体检
python webui.py                   # 浏览器打开，四步做完一章
```

网页界面只监听本机、不联网、不对外。流程是：选择剧本 → AI 初审全文与本章素材 →
确认角色/缺失素材 → 生成审查草稿 → 审查、编译并安装到 AA。

每个 AA 工程都要保存自己的自定义素材副本。因此页面区分两层：

- **本剧情素材**：当前章节已独立登记、可供初审和编译使用的自定义骨骼、背景、音效。
- **素材工作台**：跨章节的分类与副本履历，可标记“系列共用”或“章节专用”，但不会建立跨工程的运行时引用。需要复用时仍要从历史项目复制到当前章节。

页面顶部的“自定义素材导入”支持背景、PCM16 WAV 音效和 Spine 人物骨骼。
素材先经过完整性检查，再复制进所选工程并写入项目级 `manifest.json`。人物
`Identifier` 必须由用户填写并原样保存，程序不会散列、随机生成或猜测。

独立真实项目完成注册、生成与闭合引用校验后，仍须由用户在 AA 中执行“打开、预览、
编译、退出重启、重开”验收；在该人工步骤完成前，不能把自动化通过视为 AA 客户端接受。

### 批量表情差分与视觉标注

`batch_label_spine_faces.py` 用于离线整理 AA 本机覆盖目录中的角色表情。默认只选择：

- 真实存在且文件完整的 `CH/NP` 人物立绘；
- 至少 4 个不同的两位表情编号；
- 非明显匿名路人/学生 A、B 等次要角色；
- 当前可由本机 WebGL 运行时读取的 Spine 4.2 骨骼。

先生成只读计划：

```powershell
python -X utf8 batch_label_spine_faces.py plan
```

计划默认写入 `out/spine-face-batch/plan.json`，其中同时记录纳入项和每个排除原因。
确认后再运行：

```powershell
$env:OPENAI_API_KEY = "你的密钥"
python -X utf8 batch_label_spine_faces.py run --force-vision
```

也可以双击 `运行全角色表情自动标注.cmd`。任务按骨骼落库并持续写
`out/spine-face-batch/report.json`；中断后重新运行会复用渲染缓存和完整模型标注。
人工修订保存在独立覆盖字段中，AI 重跑不会覆盖人工确认结果。

首次使用公开源码仓库时，先双击 `安装Spine网页渲染运行时.cmd`。安装器会从官方 npm
包下载固定版本并校验摘要。Spine Runtimes 使用单独许可证；请阅读安装器保存的许可证并
确认自己具备相应使用权。公开仓库不包含 AA 游戏的 `.skel`、`.atlas`、贴图、模型密钥、
本机资源索引、数据库或渲染缓存，这些内容都由使用者在本机发现或生成。

演员表能**自动认人**，认不出的点一下从已登记素材库里挑。你每选一次数据库就记
一次，下次同名角色自动认出来。未登记骨骼不会直接交给模型或生成器使用。

### 命令行

```bash
python build_index.py                                   # 建资源索引
python annotate.py 剧本.txt -o 标注稿.txt --provider mock  # 演出标注（mock 不花钱）
python script2aap.py 标注稿.txt -o "第一章" --install     # 转换 + 装进 AA
python verify.py out/第一章.aap                          # 校验
python script2aap.py --syntax                           # 查全部语法
```

---

## 流水线

```
台词稿.txt ──annotate.py──▶ 标注稿.txt ──script2aap.py──▶ .aap ──AA autoCompile──▶ .aas
              (LLM 演出)      (人工可审改)     (确定性转换)
```

模型只写标注、**一个字都不碰台词**。中间产物是人能读能改的剧本文件，
所以哪一步出问题都能单独重跑。

AI 演出标注会按场景和自然对话段落分块处理。每一块会读取必要的前后文、当前背景与人物演出状态，以及带原文证据的相关剧情事件；程序会在每块完成后保存检查点。长剧本不会把全文重复塞进每一次请求，任务中断后可以从最近完成的场景块继续。原文、演员表、素材或模型规则发生变化时，程序会从受影响的场景重新推演，已经确认的早期场景不会被无条件重做。

---

## 文件

| 文件 | 作用 |
|---|---|
| `script2aap.py` | 主转换器 |
| `stage.py` | 舞台引擎：站位、走位、进出场 |
| `camera.py` | 镜头切换：决定每行画面上显示谁 |
| `annotate.py` | 演出标注（调 LLM） |
| `prompt.py` | 系统提示词 —— 最需要打磨的部分单独成模块 |
| `llm.py` / `llm.json` | 可插拔 API 接入层（anthropic / openai / mock） |
| `tables.py` | 过渡与背景效果对照表 + xxHash32 |
| `aapaths.py` | 跨机器路径探测 |
| `assetdb.py` / `label_assets.py` | 素材数据库与看图打标 |
| `asset_validation.py` / `asset_import.py` | 自定义素材发现、格式验证和统一导入 |
| `aa_registry.py` / `asset_catalog.py` | 项目级注册、幂等清单和模型白名单 |
| `aa_install_discovery.py` | 从 AzureArchive.exe 只读定位工作区和官方资源包 |
| `aa_resource_cache.py` | 官方 Addressables 资源缓存只读发现 |
| `official_preview_index.py` | 从用户本机资源包建立背景和头像预览索引 |
| `build_index.py` | 扫 AA 生成资源索引 |
| `verify.py` | 结构校验 + 与参照工程比对 |
| `webui.py` / `ui.html` | 本地网页界面 |
| `prepare_release.py` | 打包上传 |
| `docs/format.md` | `.aap` 格式规范 |
| `docs/commands.md` | 指令速查 |
| `docs/direction.md` | **演出与镜头语言** |
| `UPLOAD.md` | GitHub 上传清单 |

---

## 跨机器适配

不写死任何绝对路径。优先从用户选择的 `AzureArchive.exe` 或安装目录确认 AA 程序身份，再读取 AA 自己的 `user_settings.json` 中的 `workspacePath` 和 `cachePath`。旧版的命令行 `--aa-data`、`aa_config.json` 和 `AA_DATA` 入口继续兼容。

跑 `python aapaths.py` 看本机探到了什么。找不到会给出三种解决办法。

---

## 剧本格式

完整语法：`python script2aap.py --syntax`

推荐一行一句台词，角色名放在行首，并用 `##` 分场景。这样规则提取和 AI 初审最准确：

```text
## 场景一：商店街，午后
旁白: 商店街人声嘈杂，凯伊已经在服装店门口等候。
老师: 久等了。
凯伊: ……你为什么要把「普通」说得那么不普通。
旁白: 凯伊短暂地噎住，随后向老师走近一步。
凯伊: 那就更不行了！！
```

一行一个角色，角色名保持一致。场景标题或旁白应给出地点、时间、光线和环境声音；真实动作和位置变化要写清楚。标点应表达真实语气，不要为了触发演出堆叠省略号或感叹号。无需手工填写 `Steam`、`Dot`、`jump` 等内部名称，但生成后仍需在审查草稿中确认结果。

这不是硬性限制。小说体、分镜表或混合 Markdown 仍可导入；页面会标为“自由文本／非标准格式”，再由 AI 通读全文提取角色、骨骼、背景、音效和 BGM，用户确认后才进入生成。自定义背景、音效和骨骼必须先登记到**当前章节**。自定义 BGM 的 AA 原生登记契约仍未验证，当前只应使用已知数字 BGM ID。

```
# 章节标题                      忽略，纯注释
## 场景标题                     新建一个节点，清空舞台

旁白: 键盘声停了下来。
凯伊(05)[惊叹]{jump}<特写>: 都停一下。
      (表情) [气泡] {动作} <效果>   四个都可省略，只作用于说话者

环境
  @bg BG_GameDevRoom      @trans 淡入淡出 1500    @bgfx 集中线
  @popup Event03_CH0070   @bgm 999               @se SE_DoorOpen_01
  @place 千年科技学园       @wait 2500

舞台
  @enter 凯伊 5 右   @exit 爱丽丝 左   @move 桃井 1
  @stage 桃井@1 绿@3 柚子@5   @auto
  @fx 绿 特写       @hl 桃井,柚子

额外指令
  @bgshake  @clearst  @hidemenu  @showmenu  @shot 3  @aronatouch
  @st [-1200,-430] serial 60      @stm [0,-430] instant 90
  @zoom instant 300,-150 2160     @zoom smooth -650,-450 1860 500
  @raw #任意指令
```

对话框内的文字样式直接写在台词里，原样传给 AA：
`[7cd0ff]淡蓝色[-]`、`[size=100]放大[/size]`、`[ruby=注音]文本[/ruby]`。
详见 `docs/commands.md`。

---

## 演出

这是 galgame，**人不能一直杵着**。完整指南见 `docs/direction.md`，要点：

- **AA 会自己插停顿**：有气泡自动停 2500ms，有走位/动作自动停 1500ms。
  你写的 `@wait` 是覆盖不是叠加。所以挂气泡等于附赠 2.5 秒停顿，多了会拖垮节奏。
- **切镜头就是换立绘名单**。上一行有、这一行没有的人会自动隐藏（`#N;hide`），
  不需要进出场动画。进出场动画表示的是"人离开了房间"，两码事。
- 131 个 AA 人工工程的创作基线：同屏 1 人 38%、2 人 25%、3 人 12%、
  **5 人只有 0.6%**。镜头长度中位数 3 行。
- 特写一场戏最多 1–2 次，背景抖动一整章 2–3 次。

### 镜头由 `camera.py` 自动决定

四条最初从 AA 人工工程基线反推的规则：

1. 新面孔第一次开口、且当前镜头已端了 3 行以上 → 硬切单人，让观众看清是谁
2. 太久没说话的人下镜（超过 2 人时每行最多请走一个）
3. 同屏上限 4 人，满了踢最久没说话的
4. 旁白是否退空镜由导演语义决定；官方语料既有连续空镜，也有保留人物的旁白段。
   一旦有立绘角色正常开口，说话者必须恢复到画面中。

官方语料与 AA 人工工程基线不是同一套数据。官方命令流按槽位状态展开后的详细
分布与 main/event/bond 差异见 `docs/direction.md`；这些数据用于理解节奏倾向，
不作为后端固定次数或比例限制。

效果对比（同一份剧本）：

| | 行数 | 切镜头 | 平均 |
|---|---|---|---|
| 你手工做的第一章 | 262 | 57 | 4.6 行/镜头 |
| 旧版生成 | 266 | **7** | **38 行/镜头** |
| 新版生成 | 266 | 78 | 3.4 行/镜头 |
| 旧版第二章 | 342 | **2** | **171 行/镜头** |
| 新版第二章 | 342 | 90 | 3.8 行/镜头 |

自测：`python camera.py` 会打出与 AA 人工工程基线的逐项对比和前 40 行镜头序列。
参数在 `camera.DEFAULTS`，也可以在 `cast.json` 里写 `"camera": {...}` 覆盖，
`{"enabled": false}` 关掉。

站位与走位由 `stage.py` 排布：台上人数变化时保序最短路径重排，落在对称站位上。
要手动控制用 `@move` / `@stage`。

---

## API 接入

配置在 `llm.json`，改 `provider` 切换。

| provider | 说明 |
|---|---|
| `anthropic` | 官方 SDK，`claude-opus-4-6` + adaptive thinking。资源表打了 1 小时缓存断点 |
| `openai` | OpenAI 兼容接口。改 `base_url` 就能打 DeepSeek / GLM / Kimi / Qwen |
| `mock` | 不联网的假标注，用来验证管线 |

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."      # PowerShell
```
```bash
export ANTHROPIC_API_KEY=sk-ant-...        # Git Bash
```

加新家：继承 `llm.Provider` 实现 `complete_json` 和 `complete_json_vision`，
登记进 `REGISTRY`。

### 约束机制

送给模型的资源表**按本章演员表裁剪**——每个角色只看得到自己真实拥有的表情编号。
回来的标注再过一遍白名单：`face` 必须在该角色表情表里，`emo`/`act`/`fx`/`bgfx`/`trans`
必须是已知枚举，`se`/`bg` 必须存在。越界一律丢弃并告警。

所以模型**放不上不存在的东西**，最坏是漏标，不会生成打不开的工程。

---

## 素材数据库

打标是一次性成本。跑过一次的人把 `aa_assets.db` 拷给别人，别人不用再让 AI 看一遍图。

```bash
python label_assets.py --init                            # 建库
python label_assets.py --all --limit 20 --provider mock   # 试水
python label_assets.py --all                             # 真跑（557 张图）
python label_assets.py --export                          # 导出给转换器
```

断点续跑，标过的跳过，每批落盘，Ctrl+C 不丢进度。图片自动缩到 560px（238KB → 32KB）。

| 表 | 内容 |
|---|---|
| `bg` | 1014 个背景 + 中文语义标签 |
| `popup` | 113 张剧情 CG |
| `sound` | 308 个音效 |
| `character` / `face` | 446 个角色、4292 个表情 |
| `enum` | emoticon / action / appear / shape 全表 |
| `name_alias` | 剧本名 → AA 标识的记忆，用一次记一次 |

---

## 配音

每行都有一个**确定性**的配音槽 GUID（工程名+行号推导，重跑不变，
已做好的音频不会错位）。生成时自动导出 `<工程>/voices/voices.txt`：

```
9cac6738-b34e-4814-8bc3-427c6ac5d245 => [-] 哒哒哒哒哒。
c20f7e4e-a35f-46ff-bcf8-c4ef18fa6c8c => [桃井] 告白演出就再加一段！
```

做完 TTS 按 `<guid>.ogg` 或 `0001.ogg` 命名，加 `--voices <目录>` 重跑即可挂上，
会自动拷进工程并登记到 `manifest.json`。

---

## 上传 GitHub

```bash
python prepare_release.py --check          # 安全检查
python prepare_release.py -o ../release    # 打包
```

检查绝对路径、密钥泄露、版权素材、跨机器适配。清单见 `UPLOAD.md`。

**核心原则：传代码和知识，不传素材和作品。**
`overrides/` 下 313 MB 的背景/立绘/CG/音效是 Nexon / Yostar 的版权素材，一律不上传。

---

## 尚未支持

- **分支选项**（`selectionGroup`）—— 所有样本工程都是线性的，没有参照
- `bgmId` 完整对照表 —— 只知道 999 = 静音
- 背景图片极限尺寸、JPEG/ICC/CMYK 的完整兼容矩阵
- OGG/MP3 自定义音效以及更多 WAV 编码组合的完整兼容矩阵
- Spine 3.x/4.0/4.1 等其他版本的完整兼容矩阵
