# AA 表情 V4 完整重标提示词

> 本文件定义视觉事实、结构化表情语义和人工复核口径。标注 AI 完成看图与语义标注，后端负责归一化、冲突诊断、人格安全和运行时门槛。完整运行说明见 `docs/face-label-backend-ai-workflow.md`。

## 实际规模

- 需要逐套查看的唯一骨骼：**664 套**
- 需要逐图查看的实际表情：**11,025 张**
- 角色身份绑定：805 组
- 共用骨骼：27 套，对应 141 组身份绑定
- 数据库约 12,573 条身份绑定后表情记录。它包含共用骨骼的重复身份，不代表要重复看 12,573 张图。
- 当前四图一组约需 3,012 次基础视觉请求，失败重试与人工复核另计。

统计来源：`output/face-label-v4-plan/plan.json`。权威数据是 `aa_assets.db`，运行时索引是 `aa_resources.json`。

## 当前阶段

这套客观字段已经接入 0.9x 后端。桃井、绿、圣亚、爱丽丝、柚子共 64 张 V3 样本已通过审计并写入正式库；新的 V4 会修正空白眼开合字段，并为运行时逐台词 shortlist 提供结构化语义。11,025 张全量 V4 任务尚未启动。

64 张独立 V4 只读试标已生成到 `output/face-label-v4-agent-sample/`，生产 Schema 为 64/64。由于审计仍有细小嘴形、泪/汗边界、像素等价和无官方样本等复核项，V4 尚未写入正式数据库，也未切换 active model。批处理默认不激活新版本；只有整批干净完成并显式使用 `--activate-on-complete` 才允许切换。

生产调用中，AI 同时返回客观视觉构成和完整结构化语义；后端把二者分栏落库并独立校验。`visual_confidence` 与 `semantic_confidence` 必须分开，旧语义和 `manual_json` 不会被新版本覆盖。

## 可直接复制给原标注对话的提示词

```text
你现在继续 AA 角色表情库的 V4 完整重标。标注 AI 同时负责客观视觉事实和结构化表情语义；后端负责绑定真实角色/骨骼/face_id、冲突诊断、人格安全、官方证据摘要和运行时门槛。先对少量角色独立试标、交叉复核，确认结构稳定后再断点扩展全量。

项目资料：
- 权威数据库：D:/桌面/蔚蓝档案二创/AA自动写剧本文件/01-完整程序/aa/aa_assets.db
- 运行时索引：D:/桌面/蔚蓝档案二创/AA自动写剧本文件/01-完整程序/aa/aa_resources.json
- 全量计划：D:/桌面/蔚蓝档案二创/AA自动写剧本文件/01-完整程序/aa/output/face-label-v4-plan/plan.json
- 人工试标：D:/桌面/蔚蓝档案二创/AA自动写剧本文件/01-完整程序/aa/output/face-component-sample/manual-objective-review.json

规模口径：664 套唯一骨骼、11,025 张实际表情图；805 组身份绑定。共用骨骼只看图一次，客观视觉结果可传播到绑定身份；演出语义和人格安全策略不能随骨骼盲目传播。

工作规则：
1. 每次只处理一套唯一骨骼，输入只带当前清晰对照图、准确 face_id 列表和必要的同角色视觉对照；不发送整库、其他角色或长篇语料。
2. 按 face_id 排序比较，但不能根据编号、文件名、角色名、服装、姿势或既有情绪标签猜面部构成。
3. `visual_facts` 只写画面事实；语义字段单独判断，不得用单一嘴型或眼睛状态直接推出情绪。
4. 视觉等价的 face_id 可以得到完全相同的结果，不为了区分编号硬造差异。
5. 看不清、被头发遮挡或像素不足时使用 unknown/occluded 并降低 visual_confidence，不硬猜。
6. 闭眼时瞳色不可见，iris_color 必须为 not_visible；不能写“蓝色瞳孔闭眼”。
7. 泪光、单滴泪和流泪分开；角色底图自带的淡腮红与剧情强化脸红分开。
8. 人格、身份与禁用规则不是视觉事实。爱丽丝红眼只标 iris_color=red、eye_effect=glow；凯伊身份和普通爱丽丝禁用集合由后端独立维护。
9. 不设置硬字符预算，不压低模型配置的最大输出 token。节省 token 靠结构化短枚举和相关输入选择，不靠截断。
10. `delivery_fit` 必须区分无对话框反应、倾听、轻声说话、普通说话、强调说话和喊叫；它不是嘴型检测。
11. 无神、人格切换、极端崩溃或高度特殊表情标为 `usage_frequency=rare`，不能作为普通对话默认候选。
12. 闭眼不等于沉睡。若官方使用画像显示正常词汇台词占明显多数，语义必须覆盖倾听或说话用途，不能把该脸限定成只能沉睡、入眠或熟睡；官方证据仍不得改变闭眼、瞳色、嘴型等视觉事实。
13. `semantic_modes.label_cn` 是运行时语义别名，不是 face_id 的中文翻译。同一张脸可以同时真实支持“认真说明”和“克制生气”等多个用途；不同角色也可以各自拥有“微笑”，由后端按当前角色、装束和骨骼解析到不同 face_id。
14. 不要为了让每个 face_id 的别名唯一而扭曲语义。运行时若同一角色当前候选中出现同名别名，后端按候选排序解析第一张，并保留真实编号映射审计。

每个 item 顶层输出：
- face_id：必须与输入完全一致。
- primary_emotion、usage_hint_cn：简短中文整体判断与实际使用语境。
- emotion_family：neutral / joy / surprise_fear / embarrassment / irritation_anger / sadness_hurt / confusion_resignation。
- intensity：0 到 3；expression_class：base / accent / peak / special；hold_policy：hold / short / flash。
- beat_fit：只能使用后端给出的受控枚举。
- delivery_fit：silent_reaction / listening / soft_speech / normal_speech / emphatic_speech / shout，可多选但不得全选。
- usage_frequency：default / common / conditional / rare。
- semantic_confidence：0 到 1，只表示语义适用范围的置信度。
- avoid_when_cn：一句明确的禁用语境；没有则为空字符串。
- semantic_modes：1 到 3 个真实成立的演出用途。每项包含 label_cn、beat_fit、delivery_fit、intensity、semantic_tags、avoid_when_cn；只有一种用途时只写一个，不能为凑数量编造差别。
- eyes、brows、mouth、blush、tears、confidence：兼容字段，必须与 `visual_facts` 一致。

`visual_facts` 内只输出这些客观字段：
- eye_openness：open / wide_open / half_open / squint / closed / wink / occluded / unknown。空白眼不占用开合字段，写入 eye_effect=blank。
- gaze：forward / left / right / up / down / away / not_visible / unknown。
- iris_color：blue / cyan / green / pink / red / purple / amber / gold / gray / heterochromia / other / not_visible / unknown。
- eye_effect：normal / glow / blank / stylized / occluded / unknown。
- brow_shape：relaxed / raised / inner_raised / lowered_inward / knitted / asymmetric / occluded / unknown。
- mouth_openness：closed / slightly_open / open / wide_open / occluded / unknown。
- mouth_shape：neutral / smile / downturned / round / gritted / wavy / other / occluded / unknown。
- blush_level：none / base / expressive / strong / unknown。
- tears_level：none / watery_eyes / tear_drop / streaming / unknown。
- sweat_level：none / single / multiple / unknown。
- face_shadow：none / upper / full / unknown。
- visual_tags：只放确实可见且上述字段无法表达的客观特征；通常应为空数组。
- visual_confidence：0 到 1，只表示客观视觉判断的置信度，不混入语义多解程度。
- review_note_cn：仅在 other、unknown、occluded 或需要人工复核时写一句短说明，否则为空字符串。

只返回一个 JSON 对象，根对象只允许 items，不要重复 identifier、spine_signature 或 outfit_key；这些由后端绑定，避免幻觉并节省输出 token：
{
  "items": [
    {
      "face_id": "00",
      "primary_emotion": "轻微微笑",
      "usage_hint_cn": "适合温和回应或安静听完对方的话",
      "emotion_family": "joy",
      "intensity": 1,
      "expression_class": "base",
      "beat_fit": ["dialogue", "listening"],
      "hold_policy": "hold",
      "delivery_fit": ["listening", "soft_speech", "normal_speech"],
      "usage_frequency": "default",
      "semantic_confidence": 0.91,
      "avoid_when_cn": "强烈冲突、惊吓或喊叫",
      "semantic_modes": [
        {
          "label_cn": "温和回应",
          "beat_fit": ["dialogue", "agreement"],
          "delivery_fit": ["soft_speech", "normal_speech"],
          "intensity": 1,
          "semantic_tags": ["gentle"],
          "avoid_when_cn": "强烈争吵或情绪崩溃"
        },
        {
          "label_cn": "安静倾听",
          "beat_fit": ["listening"],
          "delivery_fit": ["listening", "silent_reaction"],
          "intensity": 0,
          "semantic_tags": ["neutral"],
          "avoid_when_cn": "需要明显惊讶或激烈反应"
        }
      ],
      "eyes": "自然睁眼",
      "brows": "放松",
      "mouth": "闭嘴微笑",
      "blush": false,
      "tears": false,
      "confidence": 0.94,
      "visual_facts": {
        "eye_openness": "open",
        "gaze": "forward",
        "iris_color": "cyan",
        "eye_effect": "normal",
        "brow_shape": "relaxed",
        "mouth_openness": "closed",
        "mouth_shape": "smile",
        "blush_level": "base",
        "tears_level": "none",
        "sweat_level": "none",
        "face_shadow": "none",
        "visual_tags": [],
        "visual_confidence": 0.96,
        "review_note_cn": ""
      }
    }
  ]
}

输出前自检：items 数量和 face_id 与输入完全一致；视觉与语义字段没有混写；没有把泪光写成泪滴；闭眼没有填写可见瞳色，也没有自动写成沉睡；高频正常台词脸没有被限定为睡眠专用；人格/禁用策略没有混进 visual_tags；特殊脸没有误标成普通常用；两个 confidence 没有混用。

试验流程：让至少两个子 Agent 对桃井、绿、圣娅、爱丽丝、柚子的同一批图片独立输出；分别比较视觉字段和语义字段一致率。优先人工复核爱丽丝 01/02/05、桃井 04/05/06 等易混项，不以少数服从多数替代看图复核。样本通过后再启动 11,025 张全量断点任务。
```

## 后端接入前必须满足

1. 客观视觉 Schema 与语义 Schema 分开，新版本写入不能覆盖旧 AI 语义或 `manual_json`。
2. `visual_confidence` 与 `semantic_confidence` 分开，视觉和语义复核原因分别记录。
3. 客观字段可随共用骨骼传播；语义、人格和禁用策略按身份绑定保存。
4. `visual_tags` 必须有独立持久化位置，不能被语义归一化成检索词后删除。
5. 爱丽丝普通人格禁用 `12、14–19` 是后端硬规则；`13` 与 `99` 保持允许，并有自动化测试。
6. 全量运行前必须先报告预计调用数、失败重试、成本、备份和续跑方案。

## 人工样本

已人工检查桃井 10 张、绿 12 张、圣娅 11 张、爱丽丝 21 张、柚子 10 张，共 64 张。当前 JSON 是结构演进前的平铺审查结果，供核对图片事实使用，不应直接作为新 Schema 的导入文件：

`output/face-component-sample/manual-objective-review.json`
