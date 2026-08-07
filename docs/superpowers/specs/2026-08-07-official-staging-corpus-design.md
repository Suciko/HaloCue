# 蔚蓝档案官方演出机器语料库设计

## 1. 目标

从 `官方剧情文档/bluearchive-data-global` 的官方 Global 数据中，建立一套可重复生成、可审计、面向 AA 自动写剧本工具和云端 Agent 的机器可读演出语料库。

本任务的重点不是再次导出纯台词，而是无损保存官方剧情节点中的演出信息，并补充便于程序和模型使用的结构化解释。语料库必须覆盖对白节点、无台词反应、纯走位、纯等待、标题、地点、转场、屏幕文字、视频及时间轴等所有场景节点。

正式输出目录：

`D:/桌面/蔚蓝档案二创/AA自动写剧本文件/05-官方演出语料库`

官方数据仓库作为只读输入，不在其中创建或修改文件。

## 2. 数据范围与全量定义

### 2.1 主输入

- `ExcelDB/ScenarioScriptExcel_0.json`
- `ExcelDB/ScenarioScriptExcel_1.json`
- `ExcelDB/ScenarioScriptExcel_2.json`

当前基线共 368,032 条记录。导出不得按是否存在中文、是否存在台词、命令是否已知或是否能映射到剧情目录进行过滤。

### 2.2 剧情归属输入

复用现有官方中文语料导出器已经验证过的故事目录构建规则，至少识别：

- 主线剧情及前半、后半分组
- 羁绊剧情及角色、好感等级、顺序
- 活动、短篇、任务及其他能够从官方目录表确定的类别
- 暂时无法归类的 `group_id`

一条记录可以拥有零个、一个或多个故事归属。无法归类不得影响记录进入主库。

### 2.3 资源反查输入

使用官方表为原始 ID 或哈希补充可读名称，至少包括：

- `ScenarioBGNameExcel.json`
- `ScenarioBGNameGlobalExcel.json`
- `ScenarioBGEffectExcel.json`
- `ScenarioTransitionExcel.json`
- `ScenarioCharacterNameExcel.json`
- `ScenarioCharacterEmotionExcel.json`
- `ScenarioEffectExcel.json`
- `ScenarioResourceInfoExcel.json`
- `BGMExcel.json`
- `BGMGlobalExcel.json`
- `AudioAnimatorExcel.json`

其他表只有在能提供稳定、可验证的映射时才加入。资源解析是附加信息，绝不覆盖或删除原始值。

## 3. 核心原则

### 3.1 原始层不可损失

每条记录必须完整保留官方字段和原始 `script_kr`。换行顺序、参数、大小写、拼写错误、未知命令、乱码式资源名均按源数据保存。

解析结果只能新增字段，不能替代原始字段。未来解析器规则变化时，可以仅凭导出记录重新解释，而不必再次寻找原始仓库。

### 3.2 解释层面向程序

将 `script_kr` 拆成有序语句，并解析为统一事件对象。每个事件保存原始文本、规范化命令名、参数、槽位、中文语义和解析状态。

解析器不猜测无法由语法或官方映射证明的含义。无法识别的内容使用 `unknown`、`partial` 或 `malformed` 状态保留。

### 3.3 顺序就是演出

同一 `script_kr` 内命令的先后顺序、同一 `group_id` 内记录顺序，以及跨节点的前后关系都必须保存。不能将事件整理成无序字典，因为例如“表情变化、气泡、动作、等待”的先后本身就是演出节奏。

### 3.4 不把散列值当垃圾

背景、转场、特效等原始数值继续保留。查到资源名时同时输出解析名、来源表和映射状态；查不到时保留数值并进入资源审计。

## 4. 输出结构

```text
05-官方演出语料库/
├─ manifest.json
├─ records/
│  ├─ scenario_0.jsonl
│  ├─ scenario_1.jsonl
│  └─ scenario_2.jsonl
├─ indexes/
│  ├─ story_units.jsonl
│  ├─ command_catalog.json
│  └─ resource_catalog.json
├─ audit/
│  ├─ extraction_report.json
│  ├─ unknown_commands.jsonl
│  ├─ unresolved_resources.jsonl
│  └─ unmapped_groups.jsonl
└─ tools/
   └─ extract_official_staging_corpus.py
```

JSON 和 JSONL 统一使用 UTF-8、简洁稳定的字段名、确定性排序和 `ensure_ascii=false`。JSONL 每行是一个完整 JSON 对象，支持流式读取，避免云端 Agent 必须一次载入数百 MB。

## 5. 主记录结构

每条 `records/scenario_N.jsonl` 记录包含以下字段组。

### 5.1 身份与顺序

- `schema_version`
- `record_uid`：由来源分片和源行号构成的稳定 ID
- `source_file`
- `source_shard`
- `source_row_index`
- `global_record_index`
- `group_id`
- `group_record_index`
- `previous_record_uid`
- `next_record_uid`

前后节点只在同一 `group_id` 内连接，不跨剧情组臆造连续关系。

### 5.2 故事归属

- `story_memberships`：零个或多个归属对象
- `primary_story_membership`：按稳定优先级选择的主要归属，便于普通检索

归属对象包含 `category`、`unit_id`、章节或角色元数据、分段名称、标题和排序键。原始 `group_id` 始终保留为最终事实。

### 5.3 官方原始字段

- `raw.script_kr`
- `raw.text_tw`
- `raw.text_jp`
- `raw.text_en`
- `raw.text_th`
- `raw.bgm_id`
- `raw.sound`
- `raw.transition`
- `raw.bg_name`
- `raw.bg_effect`
- `raw.popup_file_name`
- `raw.voice_id`
- `raw.selection_group`
- `raw.teen_mode`

若后续官方表新增字段，提取器应通过 `raw.extra_fields` 保存未纳入固定 Schema 的标量字段，而不是静默丢弃。

### 5.4 中文文本层

- `text.zh_tw`：官方繁中原文
- `text.zh_cn`：只做繁简转换的简体文本
- `text.kr_script_dialogue`：从 `script_kr` 角色记录或旁白命令中提取的韩文文本，仅作演出对应和缺失审计
- `text.localization_status`：`official_tw`、`empty_by_design`、`missing_tw_with_kr_text` 等

不得使用韩文自动翻译结果冒充官方中文。官方繁中为空但韩文含对白时，保留韩文并明确标记缺失状态。

### 5.5 结构化字段事件

将记录顶层的演出字段也转换为有类型的事件，至少包括：

- `bgm_change`
- `sound`
- `transition`
- `background`
- `background_effect`
- `popup`
- `voice`
- `selection_group`
- `teen_mode`

每个事件包含 `raw_value`、`resolved`、`semantic_zh` 和 `mapping_status`。默认值为零或空时仍在 `raw` 中保存，但一般不创建“变化事件”。

### 5.6 `script_kr` 有序事件

`script_events` 严格按原始行顺序保存。事件公共字段：

- `event_index`
- `raw_line`
- `line_type`
- `command_raw`
- `command_normalized`
- `parse_status`
- `semantic_zh`
- `arguments_raw`

按类型增加专用字段：

- 角色声明：槽位、韩文角色名、表情编号、韩文台词
- 槽位命令：槽位、动作、目标位置、气泡、特效参数
- 时间命令：毫秒数
- 镜头命令：模式、坐标、缩放、持续时间
- 屏幕文字：坐标、显示模式、字号、原始文本
- 标题和地点：命令内韩文及对应官方中文
- 视频和时间轴：资源 ID 或路径

命令规范化大小写和已知错拼仅用于聚合，例如 `#Title` 可归入 `title`；`command_raw` 永远保留原样。规范化不得让错误命令看起来已经被官方引擎正确执行，解析状态需反映它是别名、大小写变体或疑似错拼。

### 5.7 节点摘要

为方便检索，添加由结构化事件确定性生成的摘要：

- `node_kind`：对白、旁白、无台词反应、纯演出、标题、地点、流程控制等，可多标签
- `speakers`
- `visible_character_declarations`
- `has_dialogue`
- `has_official_zh`
- `has_staging`
- `command_families`
- `resource_types`

摘要不新增剧情推断，只是对已有字段建立索引。

## 6. 索引

### 6.1 `story_units.jsonl`

每行一个故事单元，记录分类、标题、角色、章节信息、涉及的 `group_id`、源记录范围和记录数量。它用于按主线章节、羁绊角色或活动快速取出完整连续片段。

### 6.2 `command_catalog.json`

按原始命令和规范化命令分别统计：

- 出现次数和涉及记录数
- 参数形态
- 大小写或拼写变体
- 各类示例的 `record_uid`
- 解析状态分布
- 中文语义和 AA 可表达性标签

示例只保存引用和少量结构信息，完整上下文由 `record_uid` 回查主库。

### 6.3 `resource_catalog.json`

按资源类型和原始 ID 建立映射，包含名称、来源表、命中次数、别名和解析状态。若同一 ID 在不同表中冲突，保留全部候选并标记 `ambiguous`，不擅自选一个覆盖。

## 7. 审计与验收

### 7.1 强制总量检查

- 输出主记录数必须等于三个源文件 `data_list` 数量之和。
- 每个源分片输出数量必须与对应输入一致。
- 每条输入都能通过分片和源行号唯一回查。
- 每条输出的 `raw.script_kr` 与源值逐字一致。

### 7.2 命令检查

- 对所有以 `#` 开头的原始行计数，输入总数与解析后总数必须一致。
- 所有非空 `script_kr` 行必须产生一个 `script_events` 项。
- 未知、部分解析和畸形事件必须进入审计文件，不能被跳过。
- 命令目录总数必须能由主记录重新计算得到。

### 7.3 资源检查

- 所有非默认资源字段必须进入已解析或未解析统计。
- 原始资源值必须保留，即使资源表无映射。
- 映射冲突必须显式报告。

### 7.4 故事归属检查

- 所有无法归类的 `group_id` 写入 `unmapped_groups.jsonl`。
- 主记录不因无法归类而缺失。
- 同一故事单元的记录顺序按官方组内顺序稳定复现。

### 7.5 确定性与回归

- 固定输入提交下重复执行应得到相同内容摘要。
- `manifest.json` 记录官方仓库提交、输入文件大小及 SHA-256、提取器版本、Schema 版本、生成时间和各输出文件摘要。
- 自动测试覆盖代表性命令、纯演出节点、韩文有字而繁中为空、大小写变体、未知命令、资源映射冲突和故事多重归属。

## 8. 与 AA 自动写剧本工具的关系

第一阶段只生产事实语料库和索引，不直接修改现有生成器、提示词或 UI。这样可以先验证官方数据是否完整可靠，避免在提取规则尚未稳定时污染现有演出系统。

后续 AA 工具可基于该库实现：

- 按场景类型检索连续官方演出片段
- 统计对白语义与表情、动作、停顿的共现
- 学习角色入镜、退镜、走位和特写节奏
- 将官方命令映射到 AA 当前可表达的字段
- 对模型生成结果进行官方分布和规则校验

AA 兼容性只能作为派生标签。官方存在但 AA 暂不支持的命令仍必须留在语料库中。

## 9. 非目标

- 不生成面向人阅读的 Markdown 教材。
- 不把全部语料一次拼成单个超大提示词文件。
- 不自动翻译缺失的韩文对白来冒充官方简中。
- 不修改官方数据仓库。
- 不在本阶段改写 AA 生成算法或自动套用官方演出。
- 不从资源包导出图片、音频、视频等二进制素材；本阶段只保存脚本引用和官方表映射。

## 10. 实施边界

提取器采用流式 JSONL 写出，输出先进入临时目录，全部审计通过后再替换正式生成目录。已有正式语料若存在，不在验证完成前覆盖。

提取逻辑优先复用现有 `render_global_chinese_corpus.py` 已验证的故事目录与繁简转换规则，但演出语料使用独立 Schema 和独立脚本，避免改变现有 GPTs 中文知识库的行为。
