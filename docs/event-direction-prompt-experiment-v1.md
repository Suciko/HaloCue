# 活动剧情演出实验提示词 v1

本模块只用于盲测提示词实验。它补充现有通用规则，不替代资源白名单、输出 Schema、人物站位几何校验或台词不可改写规则。
示例均为自写内容，不来自官方剧情。不要照搬示例的台词、人数、节拍数量或命令数量。

## 先按事件链导演，再逐行标注

读完整场后，先在心里把剧情拆成少量连续事件链。每条链只选择正文真实存在的阶段：

1. 刺激：新人物、新信息、画外声音、物件变化、提议或突发结果出现。
2. 察觉：谁最先注意到刺激；必要时使用单人、观察者镜头或画外空间。
3. 反应：刺激确实同时影响两三人时，用一个无对话框 beat 表现共同反应；各人的 face / emo / act 可以不同。
4. 承接：把焦点交给最重要的说话者、听者或关系双方。换说话人本身不等于换镜头。
5. 行动或决定：人物操作物件、提出邀请、接受、拒绝、开始行动或给出关键推断。
6. 结果与余波：结果先被看见，再让最受影响的人或小组消化；不要在爆点落下后立刻跳到无关镜头。

不是每条链都需要六个阶段，也不设置固定节点数、字符数、比例或每 N 行配额。但只要正文明确出现“发现、等待回应、共同受惊、操作确认、邀请后的犹豫、活动蒙太奇、爆点后的反差”，就不能以“克制”为理由把相应演出全部省掉。

完成草案后做一次事件覆盖检查，而不是命令计数：每个重要刺激是否被人看见，强反应是否有承受者，动作是否有结果，决定是否有停顿或回应，爆点是否有余波。没有叙事作用的节点删掉；有叙事作用但遗漏的节点补上。

## 镜头簇，而不是逐句换人

- 一个镜头簇对应一组正在发生的互动。先建立构图，在同一问答、争执、操作或笑点内保持它。
- 同组成员接入或让位时使用 expand / shrink 与 reframe；完整互动轴、焦点域或戏剧功能换了才 cut。
- 禁止把 `[A,B]` 直接变成 `[A,C]`，却让 A 像钉在原坐标、B 被 C 瞬间替换。若是另一拍摄小组，整镜 cut 并重建完整构图；若 C 真实加入当前互动，用 reveal 或 reframe 给出过程。
- 短时间内需要多人接话时，先判断能否把下一位说话者安全接入当前双人或三人镜头。能够保持同一互动轴就不要机械反打；新刺激、关键推断、爆点、发现结果和单人余波则应果断硬切。
- 单人和双人是默认构图，三人只用于确实共同动作或共同反应，任何镜头最多三人。沉默者没有关系压力、反应或即将接话理由时，不要长期挂在镜头中。
- 普通切镜只是观众改看另一组人，不代表人物走进或走出房间。真正进入空间才 enter，真正离开空间才 exit；本来就在空间里、第一次加入当前连续镜头可 reveal。右侧目标槽位从 right 出现，左侧目标槽位从 left 出现。

## face、气泡与身体动作共同构成反应阶段

- face 是持续状态。每次角色重新开口，都比较本句与该角色上一次可见状态；态度、潜台词、注意对象或情绪阶段可见地变化时换脸，相邻连续气口或刻意维持同一态度时保持。
- 选择 face 时同时读语义用途与眼睛、眉毛、嘴巴、泪、汗、眼效等视觉事实。`special / peak / flash` 差分只用于真正匹配的短拍，不能因台词有感叹号就使用，也不能长期保持。
- 无神、空白眼、人格切换等特殊脸必须有明确语境证据。普通询问、正式报告、正常兴奋和认真说明不能因为候选相近而退回无神脸。
- emo 是观众需要立刻读懂的瞬时心理符号。突然注意或被点名可用“反应”，普通不理解用“疑问”，预期被打破才用“惊疑”，真正发现值得期待的事才用“闪亮”。不要把所有高声台词都变成“惊叹”或“怒筋”。
- 同一刺激让两三人同时产生“？”“?!”等反应时，优先放进同一个无对话框 group_reaction beat，让每个人各自拥有合适的 face / emo / act；不要让其中一人说一条空台词，其他人像没看见。
- act 是可见身体表演，不要求原文逐字写出动作。正式致意、点头确认、接受邀请或柔和肯定可用 greeting；短促情绪跃升可用 jump；持续外放的欢呼、抗议或兴奋可用 hophop；身体僵住、压住反应可用 stiff；明显失去身体控制时可用 shake。动作不设固定次数或相邻冷却，但每一次都必须增加新的身体信息。
- 物件操作不能用 stiff / shake 冒充。AA 没有精细手部动画时，用稳定构图、真实音效、短停顿和结果换脸让观众理解操作。

## 无对话框节点

无对话框表示这一拍没有任何角色真正说话，所有可见角色保持高光。只有这种 beat 才使用 `wait_ms`；有对白的节点不加 Wait。常见用途：

- 第一次察觉后的共同反应；
- 一个人被问住、权衡或准备接受邀请；
- 物件被操作后等待结果；
- 连续活动的短蒙太奇；
- 爆点后的听者反应或安静余波。

一个无对话框 beat 必须能回答“观众这一拍具体看什么”。只有等待、没有换脸、动作、声音、构图目的或心理过程的空节点通常无效。连续静默可以拆成不同内容的微节拍，例如“注意到物件 -> 尝试操作 -> 僵住等待 -> 结果确认”，但不能复制同一个动作拖时长。

## 五种可复用的完整编排

### 1. 第一次建立联系

观察者单人或当前小组 -> 新人物从画外发声或在自己的台词节点从目标侧 reveal -> 观察者反应 -> 两人关系镜头。
若新人物只是被切镜看见，不做 reveal；若确实从房间外进入，才做 enter。

### 2. 发现与共同反应

发现者指出结果 -> 无对话框群体反应（最多三人、分别选表情与符号） -> 最重要的人单人确认 -> 另一人拆台或解释 -> 关系镜头收束。

### 3. 物件操作

操作者与物件所在的小组构图 -> 一次可信音效 -> 无对话框等待与表情变化 -> 结果被确认 -> 旁人反应。不要把“操作、等待、成功、欢呼”全压在同一句普通对白里。

### 4. 邀请与接受

提议者发起 -> 承受者单人或关系镜头 -> 无对话框犹豫/换脸 -> 接受或拒绝 -> 提议者单人爆点 -> 回到双人或小组余波。爆点可用一次特写、气泡、动作或集中线组合，但效果结束后必须收回。

### 5. 共同活动蒙太奇

开始行动 -> 隐去对话框 -> 两到数个有不同内容和节奏的声音/反应 beat -> 结果或时间推进 -> 分组评价与安静余波。蒙太奇期间不必把所有在场人物一直塞在同一镜。

## 自写完整示范

场景：三名学生在资料室寻找一张遗失的门禁卡，访客从门外加入。以下只展示导演决策，不是要求照抄的输出格式。

1. 甲在单人镜头中说“明明应该放在这里的……”，使用克制焦急的 face；保持常规景别。
2. 乙从画外说“你是在找这个吗？”这是第一次与甲建立联系。乙位于右侧，因此在自己的台词节点从 right reveal；不要让乙无过程瞬间出现在甲旁边。
3. 紧接一个无对话框 listener_reaction：镜头看甲，甲先注意到乙手中的东西，换成轻微意外 face，可用“反应”，等待一小拍。
4. reframe 为甲+乙的双人关系镜头。甲追问，乙解释；同一问答内保持构图，不逐句反打。
5. 丙听见“门禁卡已经折断”后加入同一刺激。若三人立绘可以安全排开，reframe 为三人；若太宽，cut 到丙单人反应。不能保留甲不动，只把乙替换成丙。
6. 三人同时看向断卡时，建立一个无对话框 group_reaction：甲是惊疑，乙是冷汗，丙是无语；三人的 face / emo / act 分别选择，不复制同一个符号。
7. 乙说“先试试备用读卡器。”切入物件操作链：稳定双人构图，播放一次真实按键或机械音；下一拍无对话框等待结果，不用 stiff 冒充刷卡。
8. 指示灯亮起后先让乙换成确认后的放松 face，再让甲说“居然还能用！”并短促 jump。结果先落地，欢呼后发生。
9. 丙邀请访客一起留下整理。访客先单人承受邀请，插入无对话框 decision_pause；访客接受后，丙才出现闪亮+hophop 的外放高兴。
10. 最后回到两人或三人的稳定关系镜头，用较轻的 face 与动作收束，不让特写、气泡或放大持续到普通闲聊。

### 对应的紧凑协议示范

下面只示范字段层级和事件顺序。`i` 是当前批次里的一基 TARGET 序号，`[Emo:...]` 必须替换成该 TARGET 或 silent shortlist 真正提供的完整候选字符串；人物名、槽位和音效也必须使用本轮资源。不要输出注释。

```json
{
  "lines": [
    {
      "i": 1,
      "face": "[Emo:克制焦急]",
      "scene_type": "event",
      "scene_function": "dialogue",
      "focus_kind": "speaker",
      "focus_character": "甲",
      "shot_operation": "switch_group",
      "shot_transition": "cut",
      "visible_characters": ["甲"],
      "positions": {"甲": 3},
      "reason": "new_stimulus"
    },
    {
      "i": 2,
      "face": "[Emo:从容确认]",
      "reveal": "right",
      "scene_type": "event",
      "scene_function": "entrance",
      "focus_kind": "speaker",
      "focus_character": "乙",
      "shot_operation": "expand_group",
      "reason": "new_stimulus"
    },
    {
      "i": 3,
      "face": "[Emo:惊疑追问]",
      "scene_type": "event",
      "scene_function": "dialogue",
      "focus_kind": "listener",
      "focus_character": "乙",
      "reaction_target": "甲",
      "shot_operation": "expand_group",
      "shot_transition": "reframe",
      "visible_characters": ["甲", "乙"],
      "positions": {"甲": 2, "乙": 4},
      "reason": "listener_reaction"
    },
    {
      "i": 7,
      "face": "[Emo:确认后的放松]",
      "se": "本轮资源中的机械确认音",
      "scene_type": "event",
      "scene_function": "action",
      "focus_kind": "speaker",
      "focus_character": "乙",
      "reason": "action_impact"
    },
    {
      "i": 9,
      "face": "[Emo:温和接受]",
      "scene_type": "event",
      "scene_function": "emotional_turn",
      "focus_kind": "speaker",
      "focus_character": "访客",
      "reason": "relation_shift"
    },
    {
      "i": 10,
      "face": "[Emo:外放高兴]",
      "emo": "闪亮",
      "act": "hophop",
      "fx": "特写",
      "scene_type": "event",
      "scene_function": "closing",
      "focus_kind": "speaker",
      "focus_character": "丙",
      "shot_operation": "impact_insert",
      "shot_transition": "cut",
      "visible_characters": ["丙"],
      "positions": {"丙": 3},
      "reason": "emotional_shift"
    }
  ],
  "beats": [
    {
      "anchor_id": 2,
      "position": "after",
      "who": "甲",
      "face": "[Emo:轻微意外]",
      "emo": "反应",
      "act": "",
      "wait_ms": 700,
      "reason": "listener_reaction",
      "visible_characters": ["甲"],
      "positions": {"甲": 3},
      "shot_operation": "impact_insert",
      "shot_transition": "cut",
      "reactions": []
    },
    {
      "anchor_id": 5,
      "position": "after",
      "who": "甲",
      "face": "[Emo:预期被打破]",
      "emo": "惊疑",
      "act": "stiff",
      "wait_ms": 900,
      "reason": "group_reaction",
      "visible_characters": ["甲", "乙", "丙"],
      "positions": {"甲": 1, "乙": 3, "丙": 5},
      "shot_operation": "expand_group",
      "shot_transition": "reframe",
      "reactions": [
        {"who": "乙", "face": "[Emo:尴尬冷汗]", "emo": "冷汗", "act": ""},
        {"who": "丙", "face": "[Emo:克制无语]", "emo": "沉默", "act": "stiff"}
      ]
    },
    {
      "anchor_id": 7,
      "position": "before",
      "who": "乙",
      "face": "[Emo:专注尝试]",
      "emo": "",
      "act": "",
      "wait_ms": 650,
      "reason": "object_operation",
      "visible_characters": ["乙", "丙"],
      "positions": {"乙": 2, "丙": 4},
      "shot_operation": "shrink_group",
      "shot_transition": "reframe",
      "se": "本轮资源中的按键音",
      "reactions": []
    },
    {
      "anchor_id": 9,
      "position": "before",
      "who": "访客",
      "face": "[Emo:吃惊犹豫]",
      "emo": "沉默",
      "act": "stiff",
      "wait_ms": 1100,
      "reason": "decision_pause",
      "visible_characters": ["访客"],
      "positions": {"访客": 3},
      "shot_operation": "impact_insert",
      "shot_transition": "cut",
      "reactions": []
    },
    {
      "anchor_id": 9,
      "position": "before",
      "who": "访客",
      "face": "[Emo:想通后放松]",
      "emo": "",
      "act": "",
      "wait_ms": 650,
      "reason": "decision_pause",
      "reactions": []
    }
  ],
  "state_delta": {},
  "memory_events": []
}
```

这个示范表达的是：同一人物可以在一个决定前拥有两个内容不同的 silent beat；共同反应必须在一个 beat 中完成；物件操作位于结论之前；重效果只落在邀请被接受后的回应爆点。它不是让每段剧情都照着生成相同节点。

## 最终自检

输出前逐项确认：

- 台词文字、说话人和顺序完全不变；
- 所有有立绘的说话者都在自己的对白画面中；
- Wait 只存在于无对话框 beat；
- 每镜最多三人，宽幅立绘没有重叠；
- 没有把普通硬切写成 enter / exit，也没有让新人物无过程替换旧人物；
- 重要刺激拥有察觉、反应、结果或余波中的必要阶段；
- 每个表情、气泡和动作都与当前反应阶段一致，特殊差分没有被当作普通脸；
- 没有为了“克制”漏掉正文明确支持的演出，也没有为了“热闹”虚构正文不支持的演出。
