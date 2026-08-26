import type { HaloCueProject } from "./types";

export const demoProject: HaloCueProject = {
  schema_version: "halocue-project/1.1",
  project_id: "project/halocue-editor-demo",
  title: "千年校庆筹备",
  characters: [
    {
      character_id: "character/yuuka",
      name: "早濑优香",
      dialogue_name: "优香",
      club_name: "研讨会",
      avatar_key: "Student_Portrait_Yuuka",
      stage_media: {
        kind: "spine",
        bundle_key: "CharacterSpine_yuuka",
        animation: "06",
        anchor_x: 0.5,
        anchor_y: 1,
        scale: 1.704,
        offset_x: -60,
        offset_y: 1038,
      },
    },
    {
      character_id: "character/noa",
      name: "生盐诺亚",
      dialogue_name: "诺亚",
      club_name: "研讨会",
      avatar_key: "Student_Portrait_Noa",
      stage_media: {
        kind: "spine",
        bundle_key: "CharacterSpine_noa",
        animation: "00_default",
        anchor_x: 0.5,
        anchor_y: 1,
        scale: 1.72,
        offset_x: -60,
        offset_y: 960,
      },
    },
    {
      character_id: "character/koyuki",
      name: "黑崎小雪",
      dialogue_name: "小雪",
      club_name: "研讨会",
      avatar_key: "Student_Portrait_Koyuki",
      stage_media: {
        kind: "spine",
        bundle_key: "CharacterSpine_koyuki",
        animation: "00",
        anchor_x: 0.5,
        anchor_y: 1,
        scale: 2.266,
        offset_x: -60,
        offset_y: 766,
      },
    },
  ],
  resources: [
    {
      resource_id: "aa/background/bg_conference_room",
      role: "background",
      logical_key: "bg_conference_room",
      aa_key: "BG_ConferenceRoom",
      preview_uri: "/api/resources/stage/background?key=bg_conference_room",
      focus_x: 0.5,
      focus_y: 0.5,
    },
    {
      resource_id: "synthetic/background/classroom",
      role: "background",
      logical_key: "background/classroom",
      preview_uri: "/scene-preview/assets/demo-conference-room.jpg",
      focus_x: 0.42,
      focus_y: 0.68,
    },
  ],
  chapters: [
    {
      chapter_id: "chapter/prologue",
      title: "序章",
      scenes: [
        {
          scene_id: "scene/conference-room",
          title: "研讨会室",
          cues: [
            {
              cue_id: "cue/conference/001",
              title: "确认预算",
              events: [
                {
                  event_id: "event/background/001",
                  kind: "background",
                  resource_id: "aa/background/bg_conference_room",
                  duration_ms: 550,
                },
                {
                  event_id: "event/enter/yuuka",
                  kind: "enter",
                  character_id: "character/yuuka",
                  slot: 1,
                  expression_id: "expression/serious",
                },
                {
                  event_id: "event/enter/noa",
                  kind: "enter",
                  character_id: "character/noa",
                  slot: 3,
                },
                {
                  event_id: "event/dialogue/001",
                  kind: "dialogue",
                  character_id: "character/yuuka",
                  text: "老师，校庆预算的最终确认就拜托您了。",
                  duration_ms: 3200,
                },
              ],
            },
            {
              cue_id: "cue/conference/002",
              title: "意外来客",
              events: [
                {
                  event_id: "event/enter/koyuki",
                  kind: "enter",
                  character_id: "character/koyuki",
                  slot: 5,
                  motion_id: "motion/appear",
                },
                {
                  event_id: "event/dialogue/002",
                  kind: "dialogue",
                  character_id: "character/koyuki",
                  text: "嘿嘿，我也带来了一个绝对不会超支的好点子！",
                  emoticon_id: "emoticon/bulb",
                  duration_ms: 3400,
                },
              ],
            },
            {
              cue_id: "cue/conference/003",
              title: "沉默",
              events: [
                {
                  event_id: "event/dialogue/003",
                  kind: "dialogue",
                  character_id: "character/noa",
                  text: "优香，我们或许应该先听听看。",
                  duration_ms: 2800,
                },
                {
                  event_id: "event/advanced/beat",
                  kind: "halocue.ba:reaction-beat",
                  intensity: 0.35,
                },
              ],
            },
          ],
        },
      ],
    },
  ],
};
