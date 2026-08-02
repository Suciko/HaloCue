# AzureArchive 自定义素材调查与真实测试报告

测试日期：2026-07-27  
AA 程序：`E:\AzureArchive_084`  
AA 数据目录：`E:\AzureArchive\存储文件\data`  
隔离工程：`AA自动素材-组合测试`

## 结论

项目级 `manifest.json` 是本次自定义背景、音效和人物骨骼能够进入 AA 的有效注册入口。无需先在 AA 界面中手动选择素材。程序复制并登记素材后，AA 能直接打开 `.aap`、预览、播放音效、切换人物表情和执行动作；关闭并重启 AA 后仍然有效。

人物 `Identifier` 是用户填写的不透明字符串。本次使用原剧情素材已有的 `1516544`，程序没有计算、散列、随机生成或修改它。

## 实际测试输入

| 类型 | 输入 |
|---|---|
| 背景 | `E:\AzureArchive\存储文件\data\projects\凯伊二创第一幕-第一章\bgs\ChatGPT Image 2026年7月19日 01_00_25.png` |
| 音效原文件 | `E:\AzureArchive\存储文件\data\overrides\sounds\SE_Gear_06.wav` |
| 音效实验副本 | `D:\桌面\蔚蓝档案二创\AA自动写剧本文件\04-素材机制实验\输入\素材副本\AA_Custom_Gear_01.wav` |
| 凯伊骨骼 | `D:\桌面\蔚蓝档案二创\恋爱游戏里没有凯伊路线\凯伊骨骼\key -无武器` |
| 剧本文本 | `D:\桌面\蔚蓝档案二创\AA自动写剧本文件\04-素材机制实验\输入\最小组合剧本.txt` |
| 演员表 | `D:\桌面\蔚蓝档案二创\AA自动写剧本文件\04-素材机制实验\输入\最小组合cast.json` |

背景实际属性为 PNG、1672×941、RGB。音效实际属性为 PCM signed 16-bit WAV、22050 Hz、双声道、约 0.8 秒。凯伊骨骼版本字符串为 Spine 4.2.33，包含 `.skel`、`.atlas`、主纹理 `.png` 和 `-avatar.png`。

## 实际输出

| 文件 | SHA-256 |
|---|---|
| `E:\AzureArchive\存储文件\data\projects\AA自动素材-组合测试.aap` | `E1DFBD50D7387E6E4197AD75AADFFC6C586437DDA64C79E19ACA6FAEA98FFDBC` |
| `E:\AzureArchive\存储文件\data\projects\AA自动素材-组合测试\manifest.json` | `0E52FEA8FC5306219DF82C798803B0BA49535CC76377DA2DB9AE3B175D950D07` |
| `E:\AzureArchive\存储文件\data\saves\AA自动素材-组合测试.aas` | `1AD585F63F01E59E101E381F95DA0B137DEAE3348044B8A7FD7E1F05D7408AC3` |
| 预览截图 | `EF8A156EA92C34BDF8B7F05C38B1168E61272A2D740828437F84B986746DCAF3` |

截图保存于：

`D:\桌面\蔚蓝档案二创\AA自动写剧本文件\04-素材机制实验\证据\AA组合测试-预览.png`

## 已由文件或实验确认

### AA 资源缓存

- `E:\AzureArchive\资源文件` 是 Unity Addressables 下载缓存，而不是自定义素材注册目录。
- 目录结构为 `<outer hash>\<content hash>\__data`，样本 `__data` 为 `UnityFS` Bundle。
- 当前扫描到约 13,308 个 Bundle。已用 UnityPy 打开背景纹理 Bundle 和含 `scenariobgeffectexceltable` 的 FlatData Bundle。
- 官方资源 ID 和数据表应以 Addressables catalog、Bundle 内表、现有官方索引为准，不能统一按文件名计算。

### 自定义背景

- 文件最终复制到项目的 `bgs` 目录。
- `manifest.json` 中登记为：
  `bgs\ChatGPT Image 2026年7月19日 01_00_25.png`。
- `.aap` 中：
  - `bgFriendlyName` 为完整文件名 stem，空格和中文均被保留；
  - `bgName` 为 `3077983933`；
  - 该值等于精确 stem 的 `xxHash32(UTF-8, seed=0)`。
- 旧版 `@bg` 会在空格处截断，本次已修复为保留完整参数；过渡只使用独立 `@trans`。
- 没有在 AA 界面中手动选择该背景。登记完成后 AA 直接显示，重启后仍存在。
- 源文件与安装文件 SHA-256 均为
  `099305981F3F376E1077B7D461716C697B53174EBD534684804883D390DB9295`，
  证明注册、预览和重启没有改写图片。

### 自定义音效

- 文件最终复制到项目的 `sounds` 目录。
- `manifest.json` 中登记为 `sounds\AA_Custom_Gear_01.wav`。
- `.aap` 的 `sound` 字段使用不带扩展名的 stem：`AA_Custom_Gear_01`。
- AA 实际播放成功，用户确认声音正常；重启 AA 后仍可播放。
- 源副本与安装文件 SHA-256 均为
  `D20AC3B1BBA8BFD1DF4F4A13999A8074D90196842CD3276DBA6EB05A2F6D6CDC`。
  本次格式下 AA 没有复制后再转码或改写音频。

### 自定义人物骨骼

- 可用输入包含同一 stem 的：
  `.skel`、`.atlas`、`.png`、`-avatar.png`。
- `.atlas` 的页面名必须与实际纹理文件名精确匹配。
- 文件复制到：
  `characters\1516544\`。
- `manifest.json` 中：
  - `Identifier` 为用户填写的字符串 `1516544`；
  - `SpinePortraitPath` 不带扩展名；
  - `SmallPortraitPath` 指向 `-avatar.png`。
- `.aap` 人物 `name` 使用 `1516544`，`faceId` 使用两位字符串。
- AA 实际显示凯伊、名称和社团信息，第一句使用 `faceId=00`，第二句使用 `faceId=03` 并执行 `jump`。
- `Player.log` 实际记录：
  - `3;1516544;00;这是自定义背景、音效和人物骨骼的组合测试。`
  - `3;1516544;03;表情与动作切换测试完成。`
  - `#3;jump`
  - `#wait;800`
- 源 `.skel` 与安装 `.skel` SHA-256 均为
  `F3BA5EF135EB9EDB37507CBDF9933079E88E6253A37240D005A5B9436823CD82`。

### 幂等性和回归

- 连续运行注册器时，背景、音效和人物均返回 `changed=false`。
- 连续运行新版生成器后，项目 `manifest.json` 前后 SHA-256 完全相同。
- 新版生成器会合并已有注册清单，不再擦除 `BgOverrides` 和 `SoundOverrides`。
- 当前自动测试为 38 项，全部通过。
- 以下基线文件与调查开始前 SHA-256 一致：
  - 全局 `data\overrides\manifest.json`
  - `aa_resources.json`
  - `镜头版-第一章.aap` 及其 `manifest.json`
  - `镜头版-第二章.aap` 及其 `manifest.json`

### 已验证的失败处理

- 背景和音效同 stem、不同内容：拒绝覆盖。
- 人物同 Identifier、不同骨骼内容：拒绝覆盖。
- 缺少 `.skel`、`.atlas`、纹理或头像：返回具体缺失文件。
- `.atlas` 页面纹理不存在或大小写不一致：返回明确错误。
- 非 PCM signed 16-bit WAV：返回需要转码，而不是静默安装。
- 空人物 Identifier：拒绝验证。
- 空表情白名单：模型不得猜测 `faceId`。
- 重复导入相同内容：不增加重复清单记录。

## 高置信度推断

- 项目级覆盖清单足以完成日常自动化导入，不需要修改全局覆盖清单。
- 自定义背景的稳定身份由“精确 stem + xxHash32”共同决定；改名会改变 `bgFriendlyName` 和 `bgName`，应当视为新素材。
- 自定义音效的稳定身份是 stem；改名会改变 `.aap` 引用，重名必须在注册前拦截。
- 同一人物的不同服装或不同骨骼应使用不同的用户 Identifier。显示名可以相同，Identifier 不应复用。
- `E:\AzureArchive\资源文件` 应作为官方素材和官方表的来源；项目/global manifest 应作为自定义素材的来源，两者不能混成同一套 ID 规则。

## 尚未确认

- AA 对背景图片的最大/最小尺寸、宽高比和显存上限。
- JPEG 在 AA 自定义背景中的全部兼容范围；本次 AA 实测仅覆盖 RGB PNG。
- ICC profile、CMYK、灰度图、WebP 等色彩空间或格式的 AA 实际行为。
- AA 对 WAV 的全部采样率、声道组合，以及 OGG/MP3 的直接覆盖支持。
- 自定义音效、语音覆盖和 BGM 覆盖在所有编码格式下是否共用完全相同的加载器。
- Spine 3.x、4.0、4.1 等其他版本的兼容范围。
- 非数字 atlas region、skin、animation 与 `faceId` 的完整映射规则。
- 全局 `data\overrides` 与项目级覆盖在同名冲突时的精确优先级。

在这些项目得到新的文件或 AA 实验之前，工具采用保守策略：

- 背景只接受已验证可读取的 RGB/RGBA PNG/JPEG，发布验收以 RGB PNG 为准。
- 音效只自动安装 PCM signed 16-bit WAV。
- 人物必须包含四类必需文件，Identifier 必须由用户填写。
- 模型只接收当前目标工程中状态为 `registered` 或 `verified` 的自定义素材白名单。

## 2026-07-27 独立差分集成（待客户端验收）

已在隔离命名空间 `AA_WEB_NATIVE_COMBINED_20260727` 完成背景
`DIFF_BG_7F3A91`、音效 `DIFF_SE_7F3A91` 与人物 `92707271` 的 project/save
双镜像登记；重复登记三项均返回 `changed=false`。最小 AAP 使用
`bgName=2894617861`、`faceId=01`、Chat `emoticon=1` 和 Jump `action=6`，闭合
引用及结构校验通过，完整证据见
`04-素材机制实验/实施验证/sdd-aa-native-custom-assets/task-6-report.md`。

这只证明注册、镜像和 AAP 引用在文件层通过；该独立项目尚未由 AA 客户端打开、
预览、编译和重启复验，因此不得将它标记为客户端已接受。

镜头工程的回归结论现以 `原生导入差异/快照/T0.json` 的写前哈希逐项对比为准。
`aa_resources.json` 没有同一实施前的独立字节哈希基线，因而仅记录其当前完整性、
计数、测试通过及未观察到写入；不把该记录表述为字节级前后不变证明。
