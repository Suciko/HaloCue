import { useRef } from "react";

import { eventLabel } from "./eventEditorCatalog";
import { useProjectStore } from "./projectStore";
import {
  durationFramesFromKey,
  durationFramesFromPointer,
  resizedDurationMs,
} from "./timelineResize";
import type { RenderTimelineEvent } from "./types";

type PointerResizeSession = {
  pointerId: number;
  startClientX: number;
  segmentWidthPx: number;
  startDurationFrames: number;
  startDurationMs: number;
};

type KeyboardResizeSession = {
  currentFrames: number;
  startDurationFrames: number;
  startDurationMs: number;
};

export function TimelineEventSegment({
  event,
  frameRate,
  selected,
}: {
  event: RenderTimelineEvent;
  frameRate: number;
  selected: boolean;
}) {
  const selectEvent = useProjectStore((state) => state.selectEvent);
  const beginTransaction = useProjectStore((state) => state.beginTransaction);
  const previewEvent = useProjectStore((state) => state.previewEvent);
  const commitTransaction = useProjectStore((state) => state.commitTransaction);
  const cancelTransaction = useProjectStore((state) => state.cancelTransaction);
  const pointerSession = useRef<PointerResizeSession | null>(null);
  const keyboardSession = useRef<KeyboardResizeSession | null>(null);
  const transactionKey = `timeline.duration:${event.event_id}`;
  const label = eventLabel(event.kind) || event.kind;

  const previewFrames = (frames: number, baselineFrames: number, baselineDurationMs: number) => {
    previewEvent(transactionKey, event.event_id, {
      duration_ms: resizedDurationMs(frames, baselineFrames, baselineDurationMs, frameRate),
    });
  };
  const finish = () => {
    if (useProjectStore.getState().activeTransaction?.key === transactionKey) {
      commitTransaction(transactionKey);
    }
  };
  const cancel = () => {
    pointerSession.current = null;
    keyboardSession.current = null;
    cancelTransaction(transactionKey);
  };
  const previewPointer = (clientX: number) => {
    const session = pointerSession.current;
    if (!session) return;
    const frames = durationFramesFromPointer({
      startClientX: session.startClientX,
      clientX,
      segmentWidthPx: session.segmentWidthPx,
      startDurationFrames: session.startDurationFrames,
    });
    previewFrames(frames, session.startDurationFrames, session.startDurationMs);
  };

  return (
    <div
      className={`timeline-event-segment${selected ? " is-active" : ""}`}
      style={{ flexGrow: event.duration_frames }}
      title={`${label} · ${event.duration_ms} ms`}
    >
      <button
        className="timeline-event-main"
        type="button"
        onClick={() => selectEvent(event.event_id)}
      >
        <span>{label}</span>
        <small>{event.duration_ms} ms · {event.duration_frames} 帧</small>
      </button>
      <button
        className="timeline-duration-handle"
        type="button"
        aria-label={`调整“${label}”时长，当前 ${event.duration_ms} 毫秒，共 ${event.duration_frames} 帧`}
        title="拖动调整时长；方向键逐帧，Page Up/Down 调整一秒，Home 设为一帧，Escape 取消"
        onClick={(pointerEvent) => pointerEvent.stopPropagation()}
        onPointerDown={(pointerEvent) => {
          pointerEvent.preventDefault();
          pointerEvent.stopPropagation();
          selectEvent(event.event_id);
          beginTransaction(transactionKey);
          const segment = pointerEvent.currentTarget.parentElement;
          pointerSession.current = {
            pointerId: pointerEvent.pointerId,
            startClientX: pointerEvent.clientX,
            segmentWidthPx: segment?.getBoundingClientRect().width || 1,
            startDurationFrames: event.duration_frames,
            startDurationMs: event.duration_ms,
          };
          pointerEvent.currentTarget.setPointerCapture(pointerEvent.pointerId);
        }}
        onPointerMove={(pointerEvent) => {
          const session = pointerSession.current;
          if (session?.pointerId === pointerEvent.pointerId) previewPointer(pointerEvent.clientX);
        }}
        onPointerUp={(pointerEvent) => {
          const session = pointerSession.current;
          if (session?.pointerId !== pointerEvent.pointerId) return;
          previewPointer(pointerEvent.clientX);
          pointerSession.current = null;
          finish();
        }}
        onPointerCancel={cancel}
        onLostPointerCapture={() => {
          if (!pointerSession.current) return;
          pointerSession.current = null;
          finish();
        }}
        onKeyDown={(keyEvent) => {
          if (keyEvent.key === "Escape") {
            keyEvent.preventDefault();
            cancel();
            return;
          }
          const session = keyboardSession.current ?? {
            currentFrames: event.duration_frames,
            startDurationFrames: event.duration_frames,
            startDurationMs: event.duration_ms,
          };
          const nextFrames = durationFramesFromKey(session.currentFrames, keyEvent.key, frameRate);
          if (nextFrames === null) return;
          keyEvent.preventDefault();
          if (keyboardSession.current === null) {
            selectEvent(event.event_id);
            beginTransaction(transactionKey);
          }
          keyboardSession.current = { ...session, currentFrames: nextFrames };
          previewFrames(nextFrames, session.startDurationFrames, session.startDurationMs);
        }}
        onKeyUp={(keyEvent) => {
          if (durationFramesFromKey(event.duration_frames, keyEvent.key, frameRate) === null) return;
          keyboardSession.current = null;
          finish();
        }}
        onBlur={() => {
          keyboardSession.current = null;
          finish();
        }}
      >
        <span aria-hidden="true" />
      </button>
    </div>
  );
}
