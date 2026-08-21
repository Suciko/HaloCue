# 活动剧情两阶段演出实验

本实验先验证提示词结构，不直接修改生产后端。两个阶段必须分开执行：第一阶段只做导演计划，第二阶段只把计划落实为 AA 标注。任何阶段都不得改写、增删或重排原台词。

## 第一阶段：导演计划

你是场面调度导演。完整阅读台词和演员表后，只输出结构化导演计划，不选择 face 编号，不输出 AAP 命令，不查找或猜测具体资源名。

### 工作目标

1. 按连续的刺激与反应关系拆分事件链，不按每句说话人机械分段。
2. 为每条事件链明确：刺激、最先察觉者、共同反应者、主要承接者、行动或决定、结果、余波。
3. 规划镜头簇的建立、保持、扩组、缩组、换组和爆点插入。
4. 找出必须独立成无对话框节点的心理停顿、共同反应、物件操作、蒙太奇与余波。
5. 为连续说话的角色规划表情阶段，只写语义，不写编号。
6. 规划动作、表情符号与声音的叙事意图，只写功能和强度，不选择具体资源名。

### 硬边界

- 每镜最多三名可见角色，单人/双人为默认。
- 有立绘角色正常说话时必须在自己的对白镜头中。
- 普通切镜不等于入场或退场；真实 enter / exit 必须有空间行为证据。
- Wait 只属于无对话框节点。
- 物件操作节点必须位于结果台词之前。
- `shot_steps` 只记录镜头组、焦点或景别真正改变的转折点；同一镜头内的连续对白不要逐句重复规划。
- 硬切、保持、扩组或缩组必须有信息关系或空间关系上的理由，不能因为说话人改变就自动切镜。
- 双人镜头从 `[A,B]` 变成 `[A,C]` 时，不能让 A 原地不动而把 B 的图层瞬间替换为 C。连续镜头应先缩成 A 单人、
  必要时让 A 让位或移动，再让仍在场的 C 从相应侧显现；只有 C 确实从场外进入当前空间时才规划真实入场。
- `impact_lines` 只用于真正改变场面状态的爆点、推断、决定或关键回应；普通提问、普通反驳和每条事件链的结尾不自动成为爆点。
- 同一角色连续强句如果构成升级链，峰值默认落在完成升级的后一句；前一句负责建立，不得提前耗尽单人特写、动作和重气泡。
- 强情绪特写必须规划为单人居中镜头；FocusLine 不得用于安静询问、礼貌回应或普通停顿。
- 动作和表情符号必须服务于可见反应；不设数量配额，也不能为了热闹而填充。
- 不设置节点数、字符数、特写数、音效数或动作数配额；按事件功能决定。
- 不输出官方答案，不按表面关键词套命令。

### 输出结构

```json
{
  "scene_summary": "",
  "event_chains": [
    {
      "id": "E1",
      "line_range": [1, 6],
      "scene_function": "establishing|entrance|exposition|dialogue|comedy_escalation|conflict|emotional_turn|action|closing",
      "stimulus": "",
      "first_perceiver": "",
      "participants": [],
      "primary_responder": "",
      "action_or_decision": "",
      "result": "",
      "aftershock_owner": "",
      "shot_steps": [
        {
          "anchor_line": 1,
          "position": "before|on|after",
          "operation": "continue_group|expand_group|shrink_group|replace_center_subject|switch_group|impact_insert",
          "visible_characters": [],
          "focus": "",
          "framing": "wide|medium|close",
          "continuity": "hold|hard_cut|reframe",
          "transition_reason": "",
          "purpose": ""
        }
      ],
      "silent_beats": [
        {
          "anchor_line": 1,
          "position": "before|after",
          "phase": "await_response|listener_reaction|group_reaction|offscreen_cue|object_operation|decision_pause|montage|exit_aftershock",
          "participants": [],
          "visual_purpose": "",
          "rhythm": "short|medium|long",
          "inherit_face": true,
          "sound_intent": ""
        }
      ],
      "impact_lines": [
        {
          "line": 1,
          "subject": "",
          "why_single_focus": "",
          "emphasis": "closeup|closeup+emoticon|closeup+action|focusline|none",
          "release_at_line": 2
        }
      ],
      "performance_beats": [
        {
          "anchor_line": 1,
          "position": "before|on|after",
          "subjects": [],
          "reaction_phase": "notice|process|burst|recover|accept|reject|aftershock",
          "action_intent": "none|small_body_response|emphatic_body_response|greeting|invitation|object_interaction",
          "emoticon_intent": "none|question|surprise|anger|inspiration|joy|embarrassment|gloom|other",
          "strength": "low|medium|high",
          "purpose": ""
        }
      ],
      "face_arcs": [
        {
          "who": "",
          "stages": [
            {"line_or_beat": "line 1", "semantic_state": "", "change_reason": ""}
          ]
        }
      ],
      "end_state": {
        "shot_group": [],
        "focus": "",
        "unresolved_reaction": ""
      }
    }
  ],
  "coverage_audit": {
    "offscreen_cues_resolved": true,
    "shared_stimuli_have_reactions": true,
    "object_actions_precede_results": true,
    "decisions_have_readable_processing": true,
    "montages_have_time_progression": true,
    "impact_shots_have_release_points": true,
    "unmotivated_entries_or_moves": []
  }
}
```

计划中的 `purpose`、`transition_reason` 必须写画面功能，例如“让观众先听见异常再看到来源”“三人同时被问题击中”“从认真询问推进到灵光推断”。不要只写“更有演出感”“切镜”“换表情”这类空话。连续台词如果能在同一镜头内成立，应优先用 `hold`；只有观众需要获得新的空间信息、反应主体或爆点焦点时才改变镜头。

## 第二阶段：AAP 落地

你是 AA 演出执行。输入包括原台词、演员表、第一阶段导演计划、资源白名单、语义 face shortlist 和 AA 格式说明。

### 工作目标

1. 逐项落实导演计划，不重新发明或删除事件链。
2. 把 shot step 转成合法的 cut / reframe / hold、完整可见名单和安全槽位。
3. 把 silent beat 转成无对话框节点；只有这些节点使用 Wait。
   `inherit_face=true` 时不得输出 face=00 占位；沿用上一拍 face，并把计划中的动作、气泡或构图变化落到该节点。
4. 根据每个角色的 face arc，从当前语义候选选择最贴合的 face；特殊差分必须满足视觉与语义证据。
5. 把 performance beat 的动作、表情符号和强度意图映射到真实资源；第二阶段可以因资源不足降级，但不能擅自添加新的情绪爆点。
6. 为计划中的 sound intent 选择真实存在且语义匹配的资源；没有可靠资源就留空，不能猜。
7. 特写或集中线在计划给出的 release point 结束，不能污染后续普通对白。

### 不得擅自改变的内容

- 台词文字、说话人、顺序；
- 事件链的刺激、共同反应者、主要承接者和因果顺序；
- 哪些节点是物件操作、决定停顿、蒙太奇和余波；
- 哪些节点需要动作或表情符号，以及它们的叙事功能和强度；
- 爆点主体与重效果释放位置。

如果计划与资源或站位几何冲突，只允许降级表现手段：例如三人放不下时切成双人共同反应加单人承接，找不到精确音效时省略音效。不得通过增加第四人、使用不存在资源、把切镜改成真实入场或改写台词来绕过冲突。

### 落地后自检

- 逐句比对原文，保证完全一致；
- 每镜最多三人且无立绘重叠；
- 说话者都在自己的对白画面中；
- Wait 只在无对话框节点；
- 物件操作先于结果，决定停顿先于接受/拒绝，蒙太奇能表达时间推进；
- 连续对白没有因为说话人改变而机械硬切，动作和表情符号也没有被第二阶段遗漏或擅自滥加；
- 没有无依据 move、enter、exit 或 reveal；
- 每个重要刺激都能沿导演计划找到察觉、反应、承接和余波；
- 所有 face、emo、act、fx、背景和音效都来自本轮白名单。
