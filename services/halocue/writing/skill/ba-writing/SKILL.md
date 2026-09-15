---
name: ba-writing
description: 用于《蔚蓝档案》二创的主线、战斗、长篇喜剧、羁绊/MomoTalk 与小说化场景写作；需要依据角色卡保持人物声音、关系和官方 ACG 译文语体时使用。
---

# BA 写作

第一优先：主线、战斗与长篇喜剧。羁绊/MomoTalk 只是短场景模式。

## 模式路由

每次只加载一个模式文件：

| 场景 | 模式文件 |
|---|---|
| 主线、任务、危机、战斗 | `knowledge/modes/主线与战斗.md` |
| 长篇喜剧、群像闹剧、连续升级 | `knowledge/modes/长篇喜剧.md` |
| 羁绊、MomoTalk、短日常 | `knowledge/modes/羁绊短场景.md` |
| `text_reading` 小说化阅读 | `knowledge/modes/小说化阅读.md` |

无法判断时按用户指定；仍不确定只用共用内核。

只有用户明确要求发癫老师，且场景允许明显失控式喜剧时，才额外读取 `knowledge/老师人设双模式.md`。

## 强制加载契约

写正文前读取且只读取：

1. 本文件；
2. `agents/writer.md`；
3. `knowledge/写作内核.md`；
4. `knowledge/人味对话机制.md`；
5. 上表命中的一个模式文件；
6. 仅当 `has_sensei: true` 时读取 `knowledge/老师在场规则.md`；
7. `_character_cards/<角色>.json` 本场运行时人物卡；
8. `assemble_prompt.py` 生成的场景提示词。

缺一项不得写正文；不追加旧规则、完整附录或其他模式。

## 角色与老师

- `characters` 只列需要 JSON 角色卡的学生。
- 老师在场写 `has_sensei: true`；老师/Sensei 不属于 `characters`。
- 老师用内置克制模式；不得搜索 Sensei.json 或自制老师卡。
- 完整人物卡只供汇编；正文 Agent 只读运行时卡。
- 运行时卡抽取决策模式、1—2 个状态、关系、关键 OOC、4—8 条单句例句和最多 3 段连续话轮；样本只校准声音与承接，不可拼接。

## 双盲首次输出

正文 Agent 只收运行时卡。双盲按 `held_out_source_id` 同时排除目标 `voice_examples` 与 `voice_sequences`，只保留明确标为 `local_exact` 或 `local_variant` 的样本；无标签及 `external_unverified` 不得按旧卡回退。开放式人味双盲要求至少 2 个非目标来源的连续样本；受控复写缺少连续样本时可退回已核验单句并如实记录。

默认双盲协议为 `open_humanness`：候选只收原创场景种子并自由发展，封存后才登记官方对照；`controlled_rewrite` 仅用于测试给定剧情下的语言执行。

## Skill 维护

修改本 skill、人物卡结构、抽取器或双盲协议前，维护者先读项目根目录 `BA写作Skill_架构与协作记忆.md`；改完同步更新其变更记录。正文 Agent 不读取该记忆文档。

候选不得读官方、策展卡、答案或旧稿；只 Write 一次、零 Edit。`$ba-writing` 失败即停止，不降级续写。

## 工作流

- quick-scene：角色卡与场景合同齐全后直接组装、写作；作者明确要草稿时按 `skills/轻量模式.md`。
- long-form：先完成章纲、信息差和连续性，再逐场调用 writer；不一次生成整章后局部修补。
- 普通修改：只改用户指定范围；结构已错时整段重写，不靠追加句子补合规。
- 双盲：只生成首次候选与固定 trace，不执行审计层或润色。

## 输出模式

- `official_script`：`角色: 内容`，最小必要旁白。
- `text_reading`：允许读者必须看见的叙述与空间关系。
- `engine_script`：另读 `knowledge/演出契约.md`，只把已声明资源能表达的内容交给演出层。

保留成立的 ACG 译文语体；只处理生硬直译，不把人物对白统一清洗成现代网络口语。
