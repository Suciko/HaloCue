# Gemini 视频演出识别提示词

你是一名《蔚蓝档案》剧情视频观察员。请完整观看我上传的视频，逐段识别常规对话立绘演出，并输出用于后续提示词研究的客观观察记录。

## 任务边界

1. 只分析常规剧情对话立绘画面。
2. 跳过所有 Q 版/SD 小人动画、活动小游戏画面、棉系卫衣等活动专属演出。先记录这些片段的起止时间和 `skip_reason`，然后不要分析其内部动作、服装、素材或镜头。
3. 不要把淡入淡出过程中的黑色人物中间帧识别为“黑色剪影素材”。必须查看前后连续帧；若它只是透明度变化，标为 `fade_transition`。
4. 必须完整看连续视频，不能只按固定间隔抽帧。台词、逐字显示、换脸、气泡、动作、位移、入场、离场、特写和停顿都需要结合前后帧判断。
5. 不分析故事优劣，不改写台词，只识别实际演出。不要生成 AA 脚本、AA 命令、faceId、槽位、wait 指令或资源选择建议。

## 识别原则

- `observed` 只写视频中能直接看到或听到的事实。
- `inferred_intent` 才能写对演出目的的解释，例如“共同惊讶后把焦点交给爱丽丝”。
- 视频无法证明的底层组件、命令名、素材 ID、faceId 一律不要猜。使用 `uncertain` 并说明缺少什么证据。
- 人名统一为简体：圣娅、桃井、绿、柚子、爱丽丝。若画面出现其他人物，按画面名称转为简体。
- 每次镜头中最多记录实际可见人物，不把仍在同一房间但当前离镜的人算进 `visible_characters`。
- 镜头由完整构图决定，不以当前说话者机械分段。若人物组、位置、景别和视觉焦点没有改变，应沿用同一个 `shot_id`。
- 普通切镜、真实入场、真实退场、镜内位移和淡入淡出必须分开记录。

## 台词与持续时间

1. 尽量逐字抄录屏幕上最终稳定显示的完整台词，不要只抄逐字显示到一半的内容。
2. 若识别不清，保留能确认的文本并设置 `dialogue_confidence`，不要自行补句。
3. 不要输出 AA 的 `wait` 或任何脚本时长指令。
4. 只有无台词但需要观众读出反应、犹豫、物件操作或余波的 `silent_beat` 才输出 `display_duration_ms`，表示这个无台词画面在视频中实际展示了多长时间。
5. `display_duration_ms` 优先依据前后画面变化测量，不要使用固定字符数公式，也不要让所有反应得到相同数值；无法准确测量时标记 `uncertain`。
6. 有台词节点只记录视频中的 `start`、`end` 和台词显示状态，不把其停留时间解释成 AA 等待。
7. 不要为了补齐节奏而伪造空台词；没有明确视觉反应时，不生成 `silent_beat`。

## 必须关注的演出维度

- 完整台词、说话者及台词出现时间；
- 每次可见表情变化，以及眼睛、眉毛、嘴巴、脸红、泪水、冷汗、脸部阴影等客观特征；
- 头顶表情符号的种类、主体、出现与消失时间；
- 原地动作，例如 stiff、shake、jump、hophop、greeting 一类可见运动；
- 人物的淡入、显现、真实入场、真实退场、横向移动和站位重排；
- 镜头名单、人物左右顺序、相对间距、缩放/特写和镜头保持；
- 无台词停顿、共同反应、听者反应、物件操作和动作余波；
- 画面何时整体切到另一互动小组，何时只是同一镜头内的小调整；
- 背景、转场、UI、音效或其他能直接确认的变化。

## 输出格式

只输出一个 JSON 对象，不要使用 Markdown 代码块。结构如下：

```json
{
  "video_summary": {
    "duration": "",
    "analyzed_ranges": [{"start": "00:00.000", "end": "00:00.000"}],
    "skipped_ranges": [
      {"start": "00:00.000", "end": "00:00.000", "skip_reason": "chibi_or_event_only"}
    ]
  },
  "characters": ["圣娅", "桃井", "绿", "柚子", "爱丽丝"],
  "timeline": [
    {
      "event_id": "E001",
      "start": "00:00.000",
      "end": "00:00.000",
      "node_type": "dialogue",
      "shot_id": "S001",
      "speaker": "",
      "dialogue_text": "",
      "dialogue_confidence": 0.0,
      "display_duration_ms": null,
      "visible_characters": [""],
      "composition": {
        "left_to_right": [""],
        "focus_character": "",
        "shot_scale": "normal_or_closeup",
        "spacing": "",
        "movement": ""
      },
      "performance": [
        {
          "who": "",
          "face_observed": {
            "eyes": "",
            "brows": "",
            "mouth": "",
            "blush": "none_or_visible_or_uncertain",
            "tears": "none_or_visible_or_uncertain",
            "sweat": "none_or_visible_or_uncertain",
            "face_shadow": "none_or_visible_or_uncertain"
          },
          "emoticon_observed": "",
          "action_observed": "",
          "entrance_exit_or_move": ""
        }
      ],
      "transition_observed": "",
      "sound_observed": "",
      "observed": "",
      "inferred_intent": "",
      "uncertain": []
    }
  ],
  "shot_groups": [
    {
      "shot_id": "S001",
      "start": "00:00.000",
      "end": "00:00.000",
      "stable_group": [""],
      "why_it_holds_or_cuts": ""
    }
  ],
  "high_value_patterns": [
    {
      "pattern": "共同刺激 -> 群体无台词反应 -> 单人焦点承接",
      "evidence_event_ids": ["E001"],
      "lesson_for_aa": ""
    }
  ],
  "unresolved": [
    {
      "range": "00:00.000-00:00.000",
      "question": "",
      "required_evidence": ""
    }
  ]
}
```

## 最终自检

- 是否完整跳过了 Q 版/SD 小人和活动专属服装段？
- 是否把淡入中间帧误判成黑色剪影素材？
- 是否只给无台词反应节点填写了 `display_duration_ms`，没有把它解释成 AA 指令？
- 是否抄到了台词最终稳定显示的完整内容，而不是半句？
- 是否记录了无台词表情变化、共同反应、动作、入退场和位移？
- 是否避免按每个说话者机械创建新镜头？
- 是否将直接观察与演出意图推断分开？
- 是否避免猜测 faceId、AA 命令名、槽位和隐藏组件？

如发现任何一项不满足，先修正输出再结束。
