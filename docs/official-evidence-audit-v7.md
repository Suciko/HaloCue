# 0.9x 官方证据链审计（V7）

## 结论

V7 之前的对照链不能把早期自动解析当成完整官方答案。原始命令流可以证明命令发生过，但不能单独证明
“真实入场”“真实退场”“一个独立视觉节点”或“某个角色必须在释放锚点出现”。这些语义需要视频或人工标注
确认。V7 的三段生成请求没有读取官方 AAP、官方解析、人工标注或旧模型结果；污染发生在生成前编写的抽象提示词
和 G1/G2 质量门，而不是盲测输入泄露。

## 已核对的证据

- 主线 3-1-7 原始人工合并稿：`output/manual-annotation-main-3-1-7-备考-merged-preserving-user-annotations.txt`
- 主线 3-1-7 数组槽修正版：`output/main-3-1-7-official-details-v7-array-state.txt`
- 主线研究笔记：`output/manual-annotation-main-3-1-7-备考-study.md`
- Code:BOX 原始边界：`output/official-codebox-raw-boundaries.txt`
- Code:BOX 研究笔记：`docs/official-codebox-study.md`
- 原始官方 JSONL：`..\..\05-官方演出语料库\records\scenario_0.jsonl`
- V7 生成请求：`output/sol-shared-v7-blind-balanced/*/requests/*.request.json`

### 被人工/视频否定的早期解释

3-1-7 的节点 15 是黑色渐变转场，不是旁白；节点 16 是无文字的静默角色演出；节点 20-23、32-35 是
渐出、黑屏、重建和等待组成的连续视觉节拍；节点 25 是黑屏后恢复关系构图，不是普通空节点。合并稿多次明确
“机器字段不能替代视频观察”。因此，底层记录逐条翻译成旁白/等待/角色节点会改变事件顺序。

Code:BOX 的原始流也显示 `#all;hide` 是频繁使用的清镜/硬切语法；`al/ar/a` 只能证明立绘显现命令，不能
单独证明人物从物理空间外进入；`d/dl/dr` 只能证明淡出类命令，不能单独证明叙事退场。24452 以及 24496-24499
还证明无对白反应和等待是可合并的连续拍，而不是每条底层记录一个独立节点。

## 生成链路核验

V7 请求静态提示词只包含抽象演出语法和资源白名单，没有出现官方节点号、官方 AAP、人工标注原文或旧结果。
`include_official_face_context` 在 V7 为关闭，所有请求也未出现角色专属官方语境段。V7 的问题来自模型自己的 G1
规划和质量门：G1 把“arrival 必须独立静默拍”“decision 必须静默拍”等可选范式推成了硬需求，G2 再因不满足
这些计划要求发起返修。P03 复核还发现部分质量诊断读取渲染前状态，和最终 AAP 不一致。

## 已实施的防污染修正

1. `official_staging_benchmark.py`：`al/ar/a` 归入显现；只有显式 `enter/exit` 才计入真实进退场；只有
   `@camera_cut` 计入硬切；原始无对白记录数标为低置信，不能进入“缺失”列表。
2. `direction_quality.py` / `annotation_agent.py`：镜头计划、静默计划、释放 owner、表演载体和审美型连续性
   发现仍完整写入审计，但不再仅凭 G1 假设自动触发 G2 返修。人数、几何、生命周期和编译硬错误仍保持自动门。
3. `annotation_scene_planner.py` / `prompt.py`：arrival、decision_pause、feedback、montage 改为有正文证据
才规划；官方研究被标记为软先验，不得成为固定模板或质量门。

## 评分口径复核（本次）

V7 的旧 benchmark 仍把 `#all;hide` 的归一化命令直接命名为 `camera_cut`，并把表情、动作和无对白记录混在
不同口径中统计；它只能用于指出结构能力是否出现，不能换算成“与官方相似度百分比”。现已补充每个维度的
`feature_confidence` 和 `feature_evidence_basis`：`camera_cut` 降为 `medium`，因为命令本身不能证明最终画面的
独立剪辑边界；`silent_staging` 仍为 `low`，直到视频/人工稿完成合并。benchmark 输出现在明确标记
`not_similarity_percentage=true`，不得把缺失列表或计数当作 V7 的官方分数。

另外，当前生成提示词的两阶段路径不再把 `hold_until` 视为不可推翻的硬边界。它是第一阶段连续镜头假设；第二阶段
若正文、互动轴、承受者或峰值支持完整硬切，可以覆盖该假设，记录为审计偏离，不触发模板式返修。这样可以避免早期
机器解析形成的“固定镜头/固定静默”假设继续污染后续生成。

这些修改只改变后端和提示词的证据边界，没有重新调用模型，也没有改写或覆盖 V7 产物。需要新模型结果时，必须
在统一的新轮次中重新生成三段并保留原始 attempt。
