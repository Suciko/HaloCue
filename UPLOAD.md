# 上传 GitHub 清单

一句话：**传代码和知识，不传素材和作品。**

跑 `python prepare_release.py` 会把该传的东西拷到一个干净目录，
剩下的活就是 `git init && git add . && git commit && git push`。

---

## 一、必须传（工具本体）

| 文件 | 说明 |
|---|---|
| `script2aap.py` | 主转换器 |
| `stage.py` | 舞台/走位引擎 |
| `camera.py` | 镜头切换算法 |
| `annotate.py` | 演出标注（调 LLM） |
| `prompt.py` | 系统提示词 |
| `llm.py` | 可插拔 API 接入层 |
| `tables.py` | 过渡/背景效果对照表 + xxHash32 |
| `aapaths.py` | 跨机器路径探测 |
| `assetdb.py` | 素材数据库读写 |
| `build_index.py` | 扫 AA 生成资源索引 |
| `label_assets.py` | 看图打标 |
| `verify.py` | 结构校验 |
| `webui.py` / `ui.html` | 本地网页界面 |
| `prepare_release.py` | 打包脚本 |

## 二、必须传（配置样例，注意是 .example）

| 文件 | 说明 |
|---|---|
| `llm.json.example` | 改名成 `llm.json` 用。里面只有环境变量名，**不含 key** |
| `cast.example.json` | 演员表样例，带注释 |

## 三、必须传（文档）

| 文件 | 说明 |
|---|---|
| `README.md` | 仓库首页 |
| `docs/format.md` | `.aap` 格式规范（逆向所得） |
| `docs/commands.md` | 额外指令与文字标记速查 |
| `docs/direction.md` | 演出与镜头语言指南 |
| `UPLOAD.md` | 本文件 |
| `LICENSE` | 建议 MIT 或 Apache-2.0 |
| `.gitignore` | 已写好 |
| `requirements.txt` | 依赖 |

---

## 四、绝对不能传

### 1. 蔚蓝档案的美术与音频资源

`overrides/` 下的 **1318 个文件、313 MB**：

```
bgs/         444 张背景     102 MB
characters/  637 个立绘文件  135 MB   （.skel / .atlas / .png / -avatar.png）
popups/      113 张剧情 CG   54 MB
sounds/      124 个音效      22 MB
```

这些是 Nexon / Yostar 的版权素材，从游戏包里提取出来的。**传上去大概率吃 DMCA，
也会连累仓库。**工具设计上也不需要它们——用户自己的 AA 里就有。

同理不能传：自定义骨骼（`凯伊骨骼/`）、配音音频（`voices/*.ogg`）。

### 2. 你自己的作品

`chapters/` `archives/` `prompts/` `settings/` `memory/` 里的剧本、章纲、
设定、伏笔表——这是你的创作，跟工具是两码事。想开源作品就单开一个仓库。

### 3. 机器相关与密钥

- `aa_config.json`：本机 AA 路径
- 任何含 API key 的文件（现在的设计是只读环境变量，本来就不会写进文件）

### 4. 生成物

`out/` `.thumbs/` `__pycache__/` `aa_resources.json`
（索引是从本机素材库扫出来的，含全部文件名，让使用者自己跑 `build_index.py`）

---

## 五、要自己拿主意的：`aa_assets.db`（652 KB）

里面是：

- 1014 个背景名 + 中文语义标签
- 113 张 CG 的描述
- 446 个角色、4292 个表情的对照
- emoticon / action / appear / shape 枚举表
- `name_alias` 角色对应记忆

**它不含任何图片或音频**，只有名字和文字描述——性质接近一份 wiki 索引。
传上去的好处是别人不用再花钱跑一遍视觉打标，这正是当初做这个库的目的。

两种做法：

- **想分享打标成果**：把 `.gitignore` 里 `aa_assets.db` 那行注释掉。
  建议同时在 README 写清楚"本库只含资源的名称与描述，不含资源本身"。
- **保守起见**：保持忽略，README 里写明让使用者自己跑
  `python label_assets.py --init && python label_assets.py --all`。

我的建议是**传**，因为它是纯派生元数据，且是这个工具最大的一次性成本。
但这是你的决定，我不替你拍板。

---

## 六、传之前逐项检查

```bash
python prepare_release.py --check      # 自动跑一遍下面这些检查
```

- [ ] 搜一遍绝对路径：`grep -rn "E:\\\\|D:\\\\|C:\\\\Users" *.py` 应该只在注释和示例里出现
- [ ] 搜一遍 key：`grep -rniE "sk-[a-z0-9]{20}|api[_-]?key\s*[:=]\s*[\"'][^\"']{20}" .`
- [ ] `git status` 里没有 `.skel` `.atlas` `.ogg` `.png` `.jpg`
- [ ] 仓库体积 < 5 MB（超了说明混进素材了）
- [ ] 在一台没装过这个工具的机器上跑 `python aapaths.py`，能自动找到 AA
- [ ] `llm.json.example` 里没有真 key
- [ ] README 里写明"需要自备 AzureArchive，本工具不分发游戏资源"

---

## 七、README 里必须写清楚的免责声明

```
本项目是 AzureArchive（foxxlight 制作的蔚蓝档案同人剧情工具）的第三方剧本编译器。

- 与 AzureArchive 作者、Nexon、Yostar 均无隶属关系
- 不分发任何游戏资源。使用者需自备 AzureArchive 及其素材库
- 工程文件格式由公开数据逆向分析得出，仅用于互操作
- 生成的作品版权归作者本人
```

## 八、建议的仓库结构

```
aa-script-compiler/
├── README.md
├── LICENSE
├── UPLOAD.md
├── .gitignore
├── requirements.txt
├── aa/
│   ├── script2aap.py  stage.py  camera.py  annotate.py  prompt.py
│   ├── llm.py  tables.py  aapaths.py  assetdb.py
│   ├── build_index.py  label_assets.py  verify.py
│   ├── webui.py  ui.html
│   ├── llm.json.example
│   └── cast.example.json
├── docs/
│   ├── format.md  commands.md  direction.md
└── examples/
    └── demo.txt          （几十行自造台词，不用你的作品）
```
