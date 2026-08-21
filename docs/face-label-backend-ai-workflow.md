# 表情标注：后端与视觉 AI 协作流程

## 权责边界

后端负责确定性事实：角色 `ident`、精确骨骼/服装变体、真实 `face_id`、官方语料中的中文台词、无对话框反应、气泡、动作、特写和来源 UID。官方用法写入 `aa_assets.db.face_official_usage`，不写入视觉标注表。

视觉 AI 负责看图：眼睛、眉毛、嘴巴、脸红、眼泪、特殊瞳色等客观面部事实，并完成整体情绪、强度、台词状态、常用程度和适用拍点的结构化表情标注。后端不看图，但负责把视觉事实与语义标注分开保存、检查冲突、汇总官方证据、生成运行时可检索的紧凑选择记录。官方语境只作为弱证据；它不能覆盖图片事实，冲突时降低置信度并进入复核。

剧情 AI 不搜索全库。后端只为当前演员和可用 face 检索少量代表性证据，再与有效视觉标注一起注入。

运行时由后端先按当前台词的 `delivery / beat / intensity`，结合 `delivery_fit / beat_fit / usage_frequency / 官方用法 / 上一张脸` 生成少量候选。人格硬禁、视觉语义冲突和未达到门槛的记录不会进入候选；剧情 AI 只在候选内结合潜台词择一，也可以判断本拍无需换脸。独立无对话框反应使用按事件、锚点和参与角色单独生成的 shortlist，不把说话者候选错套到听者身上。

## 运行时语义别名协议

剧情 AI 不再直接选择 `00/05/99`。提示词只暴露当前行或当前无对话框反应真正相关的语义别名，例如：

```text
[Emo:平静回应]
[Emo:认真报告]
[Emo:慌乱抗议]
```

AI 原样返回一个别名，后端再按当前角色、装束/骨骼和本次 shortlist 解析为真实 `face_id`。因此：

- 同一个 `face_id` 可以通过 `semantic_modes` 拥有多个真实成立的语义别名，例如同一张脸既可表示“生气”，也可表示“认真”。
- 不同角色的 `[Emo:开心]` 可以解析为各自不同的编号，不存在跨角色共用编号的假设。
- AI 返回原始编号、候选外别名或其他人物的别名时，协议会拒绝并只回显当前可用的语义别名，不向 AI 泄露真实编号。
- 没有必要换脸时允许留空；没有生成 silent shortlist 的无对话框节点不得猜表情。

这个别名层只负责运行时选择，不能替代 `visual_facts`。眼睛开合、眉形、嘴型、瞳色、泪、汗、阴影等客观事实仍是人格隔离、特殊脸门槛和人工复核的依据。

## 数据流

```text
官方 JSONL 语料
  -> 后端确定性抽取
  -> face_text_examples.json（构建产物）
  -> tools/import_official_face_usage.py
  -> aa_assets.db.face_official_usage（运行时权威）

当前角色 + 精确骨骼变体 + 当前九宫格 face_id
  -> 后端 official_face_usage() 过滤
  -> 图片 + 同角色比较缓存 + 少量官方语境
  -> 视觉 AI：visual_facts + 结构化语义标注
  -> 后端：事实归一化/冲突诊断/官方证据摘要/运行时门槛
  -> face_visual_label.observation_json + backend_json（新 model 版本，不覆盖旧版本）
  -> 低置信度与冲突项人工复核

当前台词/无对话框事件 + 当前角色
  -> 后端过滤人格禁用与未投产记录
  -> 按结构化语义和官方画像生成 3–6 个相关候选
  -> 对剧情 AI 暴露 [Emo:语义]，隐藏真实 face_id
  -> AI 结合潜台词选择语义或留空
  -> 后端按角色、装束/骨骼和本次 shortlist 解析真实 face_id
```

## 重新标注原则

- 使用新的 `--label-version`，旧模型与人工 `manual_json` 保留。
- 普通 `run` 只写独立标注版本，默认不修改 active model。只有整批目标全部完成、无缺图、无失败，且显式传入 `--activate-on-complete` 时才允许切换运行时版本。
- 不使用 `--force-vision` 时可断点续跑，同一版本已完成的 face 会跳过。
- 先对桃井、绿、圣娅、爱丽丝、柚子做小样本验收，再扩展到 664 套骨骼、11,025 张表情。
- 不设置硬字符预算，也不在后端改小模型配置的输出 token；节省输入靠按角色/face 检索。
- 爱丽丝红眼等人格/身份安全规则由后端独立维护，不能从官方台词或编号反推。
- `observation_json` 是 AI 对当前图片的原始观察，不参与人工语义覆盖；`backend_json` 记录后端是否允许直接用于选择以及需要复核的原因。
- 客观观察使用固定枚举：`eye_openness/gaze/iris_color/eye_effect/brow_shape/mouth_openness/mouth_shape/blush_level/tears_level/sweat_level/face_shadow`，另有 `visual_tags/visual_confidence/review_note_cn`。完整枚举与人工复核规则见 `docs/face-component-relabel-prompt.md`。
- 后端发现候选与眼睛、脸红、眼泪等事实冲突时只标记 `review_flags`，不偷偷把 05 改成 06，也不把“闭眼”重新解释成“无神”。这样重标记结果可审计，人工可以只修冲突项。
- 官方使用画像中正常词汇台词占明显多数时，后端会拒绝“沉睡/入眠/熟睡专用”的语义候选并触发单脸重判；这只限制语义适用范围，不会反推或改写闭眼等视觉事实。
- 旧供应商只返回顶层 `eyes/brows/mouth/blush/tears` 时，后端会自动转换为 `visual_facts`，无需一次性升级所有调用方。

## 命令

重新导入官方证据：

```powershell
python tools/import_official_face_usage.py
```

生成只读计划：

```powershell
python batch_label_spine_faces.py plan
```

小样本重新标注示例（正式运行前替换为确定的新版本名）：

```powershell
python batch_label_spine_faces.py run --label-version face-official-context-v2 --ident "모모이" --limit 1
```

上面的命令不会激活新版本。完成人工验收后，如需在一次完整且无失败的批次结束时自动激活，才使用：

```powershell
python batch_label_spine_faces.py run --label-version gemini-3.6-flash:semantic-profile-v4 --activate-on-complete
```

若有任一目标失败、缺图、只完成部分 face，激活会被拒绝，原 active model 保持不变。

建议本轮重标记使用新的版本名，例如 `gemini-3.6-flash:semantic-profile-v4`。它会保留旧模型行和人工 `manual_json`，只把新一轮结果写入新 provenance 行；验收时同时查看 `backend.review_flags`、`observation`、`delivery_fit` 和 `usage_frequency`，不要只看 `primary_emotion`。

不要在未验收样本前直接启动全量任务。

## 当前 V4 只读试标

桃井、绿、圣娅、爱丽丝、柚子共 64 张已完成独立 V4 试标，文件位于 `output/face-label-v4-agent-sample/`：

- `aris.json`：爱丽丝 21 张；普通爱丽丝的 `12、14–19` 由后端人格规则隔离。
- `momoi-midori.json`：桃井 10 张、绿 12 张。
- `seia-yuzu.json`：圣娅 11 张、柚子 10 张。

生产 Schema 校验为 64/64；57 张可进入候选，另外 7 张均为预期的人格隔离，没有意外硬阻断。试标审计仍记录 26 个细小嘴形、泪/汗边界、像素等价或缺少官方样本的复核项，因此这些文件尚未写入 `aa_assets.db`，V4 也没有激活。
