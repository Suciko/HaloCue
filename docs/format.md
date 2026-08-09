# `.aap` 工程格式规范

全部由逆向分析得出，样本是 139 个真实工程、18932 条对白。
每条结论都标了验证方式与样本量；推测的地方明确写出来。

---

## 文件

| 后缀 | 是什么 | 要不要管 |
|---|---|---|
| `.aap` | 工程文件，**UTF-8 无 BOM 的 JSON**，Newtonsoft 带 `$type` | 生成这个 |
| `.aas` | 编译产物，FlatBuffers 二进制，内嵌蔚蓝档案原生脚本文本 | 不用管，AA 的 `autoCompile` 会自动生成 |

存储目录默认在 `%USERPROFILE%\AppData\LocalLow\foxxlight\AzureArchive\data`，
可以在 AA 设置里改到别处。改过之后默认位置只剩 `settings\user_settings.json`，
里面的 `workspacePath` 指向真正的位置。探测逻辑见 `aapaths.py`。

---

## 顶层结构

```jsonc
{ "$type": "ProjectData, Assembly-CSharp",
  "ProjectName": "第一章",
  "PreviewBgName": 1194944144,     // 封面背景的 ID
  "PreviewHeader": null,
  "PreviewTitle": null,
  "nodes": { "$type": "System.Collections.Generic.List`1[[NodeData, ...]], mscorlib",
             "$values": [ /* 节点 */ ] } }
```

三种节点，靠 `Guid` + `ConnectionsTo` 连成有向图：

| `$type` | 作用 | 关键字段 |
|---|---|---|
| `EntryNodeData` | 入口，**Guid 必须是全 0** | `Title` `Header` |
| `ScriptNodeData` | 正文 | `Scripts[]` `NodeName` |
| `ExitNodeData` | 结尾 | `IsEnding` `EndText` `NeHeader` `NeTitle` `NeScriptDirty` |

`ExitNodeData` 的 `additionalPrompt` 会被编译器自动填成
`#nextepisode;<NeHeader>;<NeTitle>`（3/3 验证），不是作者手写的。

---

## ScriptData（一行对白）

```jsonc
{ "$type": "ScriptData, Assembly-CSharp",
  "text": "还差十五分钟。",
  "popup": "",                     // 弹出图片名
  "bgEffect": 0,                   // 背景效果 ID，见 tables.BGEFFECT
  "bgName": 1194944144,            // 背景 ID = xxHash32(utf8(bgFriendlyName), seed=0)
  "bgFriendlyName": "BG_GameDevRoom",
  "sound": "SE_Typing_01",
  "voice": "8ef7c7b1-...-fe9c",    // 配音槽 GUID -> voices/<guid>.ogg
  "transition": 0,                 // 过渡 ID，见 tables.TRANSITION
  "bgmId": 999,                    // 999 = 静音
  "selectionGroup": 0,             // 分支选项组（本工具尚未支持）
  "additionalPrompt": "#wait;2000",
  "characters": { "$values": [ /* 恒 6 个 */ ] },
  "speakerSlotNum": 3,
  "highlightedSlotNums": { "$values": [1, 2] },
  "isDialogScript": true,
  "placeText": "" }                // 地点名称卡
```

字段顺序必须与上面一致（`verify.py` 会检查）。

### `bgName` 是 xxHash32

`bgName = xxHash32(utf8(bgFriendlyName), seed=0)`。579 组实测命中 **577**，
两个未命中是大小写漂移（`BG_SchoolFrontGate_SunSet` vs `..._Sunset`）。

所以新背景不需要查表，直接算即可（`tables.bg_id()`）。

> 早前一度以为破不出来 —— 那是因为只测了 crc32 / fnv / djb2 / sdbm / java31 /
> jenkins / elf / adler32 / murmur3 / .NET GetHashCode，**漏了 xxhash**。

### `transition` 与 `bgEffect` 不是哈希

它们是资源表主键：

- `transition` 的 61 条对照表硬编码在 `GameAssembly.dll` 的
  `Studio.Scripts.EnvProp.TransitionProp::Init()` 里（61 次 `Dictionary.Add`）。
  工程里出现的 29 个值 100% 命中。
- `bgEffect` 来自 `flatdata_assets_all.bundle` 里的 `ScenarioBGEffectExcel`，
  46 行、35 个具名效果，全部对应 catalog 里真实存在的 `UI_FX_<name>.prefab`。

两张表都在 `tables.py` 里。

---

## CharacterRecordData（每个立绘位）

```jsonc
{ "$type": "ScriptData+CharacterRecordData, Assembly-CSharp",
  "name": "모모이",        // 空串 = 该位无人
  "faceId": "03",          // 字符串，不是数字
  "startingPos": 3,        // 本行开始时的位置
  "endingPos": 4,          // 本行结束时的位置，不等就是走位
  "emoticon": -1,          // -1 = 无。0 是真实值（怒筋）
  "action": 0,
  "effect": 0,             // 恒为 0，未使用（112770 条全是 0）
  "appear": 0,
  "shapeOverride": 0 }
```

### 位置模型（核心）

`characters` 恒为 **6 个元素**。

- **下标 0 是"无立绘说话位"** —— 旁白、只出声的角色走这里。
  `characters[0].name` 为空 = 纯旁白，非空 = 该角色说话但不显示立绘。
  实测：`startingPos` 恒为 0（9796/9796）。
- **下标 1–5 是立绘位，下标就等于 `startingPos`。**

`startingPos` 完全确定，没有第三种情况（35493 条全覆盖）：

```
startingPos == 数组下标              34122 条
startingPos == 上一行同槽同角色的 endingPos   1371 条
无法解释                                0 条
```

同一角色留在同一数组槽时，`上一行.endingPos == 本行.startingPos`，
**29591/29591 = 100%，零违例**。

### 编译器行为（都是 100% 规则）

| 条件 | 编译出 | 命中 |
|---|---|---|
| `startingPos != endingPos` | `#N;m<endingPos>` | 741/741 |
| `startingPos == endingPos` | 不发 m | 27372/27372 |
| 上一行占着、本行为空的槽 | `#N;hide` | 1752/1756 |
| `appear != 0` | `#N;<al\|ar\|a\|dl\|dr\|d>` | 1852/1852 |

`#N` 里的 N **恒为数组下标**（9532/9532），不是位置。
`speakerSlotNum` 和 `highlightedSlotNums` 同样是下标。

**两条硬约束**，违反了角色会在数组里互相覆盖、凭空消失：

1. 同一行内各角色的 `startingPos` 两两不同（它是数组下标）
2. 入场角色的落点必须是**当前空着的槽** —— 它一出现就站在终点，
   若那个槽有人正要移走，两人下标会撞

---

## 枚举

由 `.aap` ↔ `.aas` 配对反推，逐条验证。

### emoticon（气泡）

| 值 | 符号 | 中文 | | 值 | 符号 | 中文 |
|---|---|---|---|---|---|---|
| 0 | `[빠직]` | 怒筋 | | 10 | `[땀]` | 冷汗 |
| 1 | `[재잘]` | 叽喳 | | 11 | `[반짝]` | 闪亮 |
| 2 | `…` | 沉默 | | 12 | `[속상함]` | 难过 |
| 3 | `[!]` | 惊叹 | | 13 | `[딴생각]` | 走神 |
| 4 | `[하트]` | 爱心 | | 14 | `{Bulb}` | 灵光一闪 |
| 5 | `[음표]` | 音符 | | 15 | `{Sad}` | 悲伤 |
| 6 | `[?]` | 疑问 | | 16 | `{Sigh}` | 叹气 |
| 7 | `[반응]` | 反应 | | 17 | `{Steam}` | 冒烟 |
| 8 | `[///]` | 脸红 | | 18 | `{Tear}` | 落泪 |
| 9 | `[?!]` | 惊疑 | | 19 | `{Zzz}` | 瞌睡 |

`-1` 表示无。注意 `0` 是真实值。

`[叽喳]`（原生符号 `[재잘]`）是 `emoticon=1`，不是动作。

### action（动作）

`1 greeting 向下确认 / 2 falldownl 向左倒 / 3 falldownr 向右倒 / 4 stiff 小颤抖 /
5 shake 大颤抖 / 6 jump 跳 / 7 hophop 蹦跳`

`{jump}` 是 `action=6`。气泡、走位、进出场或动作会让 AA 自动插入默认等待；
显式 `@wait` 会覆盖该默认等待。

### appear（进出场）

`1 al 从右入 / 2 ar 从左入 / 3 a 登场 / 4 dl 向左退 / 5 dr 向右退 / 6 d 退场`

本工具的生成规则：

- 角色第一次进入当前场景画面时，默认 `appear=3`，播放一次正常登场动画。
- 已经登场过的角色再次进镜时使用 `appear=0`，不重复播放渐入；剧本明确写出
  `@enter 角色 [位置] [al|ar|a]` 时，才以该指令指定的方式入场。
- 只有明确写出 `@exit 角色 [dl|dr|d]` 时，才写入退场动画。
- 场景或节点结束不会自动给最后一句添加 `appear=6`；镜头切换仍使用角色名单变化
  触发编译器的 `#N;hide`。

对应面板"位置"那一行的按钮，屏幕从左到右是：
`≪(dl) ▷(ar) ＋(a) [1][2][3][4][5] －(d) ◁(al) ≫(dr)`

（由 localPosition.x 等距单调 + sprite 图元 + NGUI `mFlip` 三重证据确定）

### shapeOverride（立绘效果）

`1 sig 剪影 / 2 black 变暗 / 4 closeup 特写`。未确认的 shape 数值仅保留为
观察证据，不能由模型或脚本生成。

面板上"效果"那一行的三个图标写的是这个字段，不是 `effect`。

---

## manifest.json（每个工程一份）

```jsonc
{ "CharacterOverrides": [
    { "Identifier": "1516544", "Name": "凯伊", "Nickname": "特殊现象调查部",
      "CharacterReference": null, "OriginalIdentifier": null,
      "SpinePortraitPath": "characters\\1516544\\CH0335_noweapon_spr",
      "SmallPortraitPath": "characters\\1516544\\CH0335_noweapon_spr-avatar.png" } ],
  "VoiceOverrides": ["voices/<guid>.ogg"],
  "PopupOverrides": [],
  "SoundOverrides": ["sounds\\AA_Custom_Gear_01.wav"],
  "BgOverrides": ["bgs\\自定义 夜景.png"],
  "BgmOverrides": [] }
```

自定义骨骼放在 `<工程名>/characters/<Identifier>/` 下，
需要 `.skel` `.atlas` `.png` `-avatar.png` 四个文件。
`Identifier` 是用户填写的不透明字符串，不由程序计算。

自定义背景放在 `<工程名>/bgs/`，`BgOverrides` 登记带扩展名的相对路径。
`.aap` 的 `bgFriendlyName` 使用精确文件名 stem，`bgName` 使用该 stem 的
`xxHash32(UTF-8, seed=0)`。文件名中的空格、中文和大小写都会参与计算。

自定义音效放在 `<工程名>/sounds/`，`SoundOverrides` 登记带扩展名的相对路径，
`.aap` 的 `sound` 字段只写文件名 stem。当前自动导入器保守接受 PCM signed
16-bit WAV；其他编码先报告需要转码。

## 配音

- 每行的 `voice` 是一个 GUID，对应 `<工程名>/voices/<guid>.ogg`
- 用到的要登记进 `manifest.json` 的 `VoiceOverrides`
- AA 会导出 `voices/voices.txt`，格式是 `<guid> => [角色] 台词`，
  给配音/TTS 用。本工具生成的 GUID 是**确定性的**（工程名+行号推导），
  重新生成不会让已做好的音频错位

## 表情表怎么读

标准 BA 模型的 `.atlas` 是纯文本，region 名自带语义：

```
00_default   00_eyeclose   01_normal   02_respond
03_smile     04_embarrassed  05_serious  06_depressed
```

`faceId` 就是这个前缀。官方美术拼写错误很多
（`embarassed` / `embrassed` / `nomal` / `defualt` / `depressde` …），
`build_index.py` 里的 `FACE_ALIAS` 做了归一化。

AA 内置角色（韩文名那批）的立绘在 Addressables 包里，磁盘上读不到 `.atlas`，
退而求其次从历史工程统计实际用过的 faceId。

---

## 尚未支持

- **分支选项**（`selectionGroup`）—— 手上所有工程都是线性的，没有样本
- `bgmId` 的完整对照表 —— 只知道 999 = 静音
