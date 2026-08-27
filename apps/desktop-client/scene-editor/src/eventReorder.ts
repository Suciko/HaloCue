export type EventDropPlacement = "before" | "after";

export type EventMove = -1 | 1 | {
  targetEventId: string;
  placement: EventDropPlacement;
};

type StableEvent = { event_id: string };

export function eventDropPlacement(clientY: number, top: number, height: number): EventDropPlacement {
  if (!Number.isFinite(clientY) || !Number.isFinite(top) || !Number.isFinite(height) || height <= 0) {
    throw new RangeError("event drop geometry must be finite with a positive height");
  }
  return clientY < top + height / 2 ? "before" : "after";
}

export function reorderEvents<T extends StableEvent>(
  events: readonly T[],
  sourceEventId: string,
  move: EventMove,
): readonly T[] {
  const sourceIndex = events.findIndex((event) => event.event_id === sourceEventId);
  if (sourceIndex < 0) return events;

  const targetEventId = typeof move === "number"
    ? events[sourceIndex + move]?.event_id
    : move.targetEventId;
  const placement: EventDropPlacement = typeof move === "number"
    ? move < 0 ? "before" : "after"
    : move.placement;
  if (!targetEventId || targetEventId === sourceEventId) return events;

  const next = events.slice();
  const [source] = next.splice(sourceIndex, 1);
  const targetIndex = next.findIndex((event) => event.event_id === targetEventId);
  if (targetIndex < 0) return events;
  next.splice(targetIndex + (placement === "after" ? 1 : 0), 0, source);

  return next.every((event, index) => event.event_id === events[index]?.event_id)
    ? events
    : next;
}
