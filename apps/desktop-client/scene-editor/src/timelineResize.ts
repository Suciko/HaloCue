export type TimelineResizePointerInput = {
  startClientX: number;
  clientX: number;
  segmentWidthPx: number;
  startDurationFrames: number;
};

export function durationFramesFromPointer({
  startClientX,
  clientX,
  segmentWidthPx,
  startDurationFrames,
}: TimelineResizePointerInput): number {
  if (
    !Number.isFinite(startClientX)
    || !Number.isFinite(clientX)
    || !Number.isFinite(segmentWidthPx)
    || segmentWidthPx <= 0
    || !Number.isInteger(startDurationFrames)
    || startDurationFrames < 1
  ) {
    throw new RangeError("timeline resize pointer input must be finite and positive");
  }
  const pixelsPerFrame = segmentWidthPx / startDurationFrames;
  const frameDelta = Math.round((clientX - startClientX) / pixelsPerFrame);
  return Math.max(1, startDurationFrames + frameDelta);
}

export function durationFramesFromKey(
  currentFrames: number,
  key: string,
  frameRate: number,
): number | null {
  if (!Number.isInteger(currentFrames) || currentFrames < 1) {
    throw new RangeError("timeline duration must contain at least one frame");
  }
  if (!Number.isInteger(frameRate) || frameRate < 1) {
    throw new RangeError("timeline frame rate must be a positive integer");
  }
  const target = {
    ArrowLeft: currentFrames - 1,
    ArrowDown: currentFrames - 1,
    ArrowRight: currentFrames + 1,
    ArrowUp: currentFrames + 1,
    PageDown: currentFrames - frameRate,
    PageUp: currentFrames + frameRate,
    Home: 1,
  }[key];
  return target === undefined ? null : Math.max(1, target);
}

export function durationMsForFrames(durationFrames: number, frameRate: number): number {
  if (!Number.isInteger(durationFrames) || durationFrames < 1) {
    throw new RangeError("timeline duration must contain at least one frame");
  }
  if (!Number.isInteger(frameRate) || frameRate < 1 || frameRate > 1000) {
    throw new RangeError("timeline frame rate must be between 1 and 1000");
  }
  return Math.max(1, Math.floor((durationFrames * 1000) / frameRate));
}

export function resizedDurationMs(
  targetFrames: number,
  baselineFrames: number,
  baselineDurationMs: number,
  frameRate: number,
): number {
  if (!Number.isFinite(baselineDurationMs) || baselineDurationMs <= 0) {
    throw new RangeError("timeline baseline duration must be finite and positive");
  }
  return targetFrames === baselineFrames
    ? baselineDurationMs
    : durationMsForFrames(targetFrames, frameRate);
}
