import { describe, expect, it } from "vitest";

import { buildRenderTimeline } from "./renderTimeline";
import type { SceneDescriptor } from "./types";

const descriptor = (events: SceneDescriptor["events"]): SceneDescriptor => ({
  schema_version: "scene-descriptor/1.0",
  scene_id: "scene/overlap",
  presentation: { frame_rate: 30 },
  background: null,
  initial_background: null,
  actors: [],
  initial_actors: [],
  events,
});

describe("render timeline overlap semantics", () => {
  it("starts the next event immediately when a character motion does not wait", () => {
    const timeline = buildRenderTimeline(descriptor([
      {
        event_id: "event/nod",
        kind: "character-motion",
        motion_id: "motion/nod",
        duration_ms: 500,
        wait_for_completion: false,
      },
      { event_id: "event/beat", kind: "wait", duration_ms: 100 },
    ]));

    expect(timeline.events).toEqual([
      expect.objectContaining({
        event_id: "event/nod",
        start_frame: 0,
        end_frame: 15,
        wait_for_completion: false,
      }),
      expect.objectContaining({
        event_id: "event/beat",
        start_frame: 0,
        end_frame: 3,
        wait_for_completion: true,
      }),
    ]);
    expect(timeline.total_frames).toBe(15);
  });

  it("keeps a non-blocking background pan active behind the following dialogue", () => {
    const timeline = buildRenderTimeline(descriptor([
      {
        event_id: "event/pan",
        kind: "halocue.ba:background-pan",
        duration_ms: 900,
        wait_for_completion: false,
      },
      {
        event_id: "event/line",
        kind: "dialogue",
        text: "镜头移动时继续对白。",
        duration_ms: 300,
      },
    ]));

    expect(timeline.events).toEqual([
      expect.objectContaining({
        event_id: "event/pan",
        start_frame: 0,
        end_frame: 27,
        wait_for_completion: false,
      }),
      expect.objectContaining({
        event_id: "event/line",
        start_frame: 0,
        end_frame: 9,
        wait_for_completion: true,
      }),
    ]);
    expect(timeline.total_frames).toBe(27);
  });

  it("keeps a non-blocking screen shake active behind the following dialogue", () => {
    const timeline = buildRenderTimeline(descriptor([
      {
        event_id: "event/shake",
        kind: "halocue.ba:screen-shake",
        duration_ms: 360,
        wait_for_completion: false,
      },
      {
        event_id: "event/line",
        kind: "dialogue",
        text: "震屏时继续对白。",
        duration_ms: 300,
      },
    ]));

    expect(timeline.events).toEqual([
      expect.objectContaining({
        event_id: "event/shake",
        start_frame: 0,
        end_frame: 11,
        wait_for_completion: false,
      }),
      expect.objectContaining({
        event_id: "event/line",
        start_frame: 0,
        end_frame: 9,
        wait_for_completion: true,
      }),
    ]);
    expect(timeline.total_frames).toBe(11);
  });

  it("keeps non-blocking screen text active behind the following dialogue", () => {
    const timeline = buildRenderTimeline(descriptor([
      {
        event_id: "event/screen-text",
        kind: "halocue.ba:screen-text",
        text: "三天后",
        duration_ms: 1800,
        wait_for_completion: false,
      },
      {
        event_id: "event/line",
        kind: "dialogue",
        text: "文字显示时继续对白。",
        duration_ms: 500,
      },
    ]));

    expect(timeline.events.map((event) => ({
      event_id: event.event_id,
      start_frame: event.start_frame,
      end_frame: event.end_frame,
      wait_for_completion: event.wait_for_completion,
    }))).toEqual([
      {
        event_id: "event/screen-text",
        start_frame: 0,
        end_frame: 54,
        wait_for_completion: false,
      },
      {
        event_id: "event/line",
        start_frame: 0,
        end_frame: 15,
        wait_for_completion: true,
      },
    ]);
    expect(timeline.total_frames).toBe(54);
  });

  it("rejects non-blocking timing on an event without that capability", () => {
    expect(() => buildRenderTimeline(descriptor([{
      event_id: "event/wait",
      kind: "wait",
      duration_ms: 100,
      wait_for_completion: false,
    }]))).toThrow(/does not support non-blocking timing/);
  });
});
