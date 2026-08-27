import { describe, expect, it } from "vitest";

import {
  durationFramesFromKey,
  durationFramesFromPointer,
  durationMsForFrames,
  resizedDurationMs,
} from "./timelineResize";

describe("timeline duration resize", () => {
  it("converts pointer distance to whole frames using the captured segment scale", () => {
    expect(durationFramesFromPointer({
      startClientX: 100,
      clientX: 118,
      segmentWidthPx: 90,
      startDurationFrames: 5,
    })).toBe(6);
    expect(durationFramesFromPointer({
      startClientX: 100,
      clientX: 1,
      segmentWidthPx: 90,
      startDurationFrames: 5,
    })).toBe(1);
  });

  it("maps keyboard nudges and page steps to frame-snapped durations", () => {
    expect(durationFramesFromKey(15, "ArrowRight", 30)).toBe(16);
    expect(durationFramesFromKey(15, "ArrowLeft", 30)).toBe(14);
    expect(durationFramesFromKey(15, "PageUp", 30)).toBe(45);
    expect(durationFramesFromKey(15, "PageDown", 30)).toBe(1);
    expect(durationFramesFromKey(15, "Home", 30)).toBe(1);
    expect(durationFramesFromKey(15, "Escape", 30)).toBeNull();
  });

  it("encodes integer milliseconds that resolve to the requested frame count", () => {
    for (const frameRate of [24, 30, 60]) {
      for (let frames = 1; frames <= frameRate * 10; frames += 1) {
        const durationMs = durationMsForFrames(frames, frameRate);
        expect(Math.ceil((durationMs * frameRate) / 1000)).toBe(frames);
      }
    }
  });

  it("preserves the authored millisecond value when a gesture stays on its baseline frame", () => {
    expect(resizedDurationMs(17, 17, 550, 30)).toBe(550);
    expect(resizedDurationMs(18, 17, 550, 30)).toBe(600);
    expect(resizedDurationMs(17, 17, 550, 30)).toBe(550);
  });
});
