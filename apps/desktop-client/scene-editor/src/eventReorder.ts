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
  return reorderEventBlock(events, [sourceEventId], move);
}

export function reorderEventBlock<T extends StableEvent>(
  events: readonly T[],
  selectedEventIds: Iterable<string>,
  move: EventMove,
): readonly T[] {
  const selected = new Set(selectedEventIds);
  const sources = events.filter((event) => selected.has(event.event_id));
  if (sources.length === 0) return events;

  const sourceIds = new Set(sources.map((event) => event.event_id));
  let targetEventId: string | undefined;
  let placement: EventDropPlacement;

  if (typeof move === "number") {
    if (move < 0) {
      const firstSourceIndex = events.findIndex((event) => sourceIds.has(event.event_id));
      for (let index = firstSourceIndex - 1; index >= 0; index -= 1) {
        if (!sourceIds.has(events[index].event_id)) {
          targetEventId = events[index].event_id;
          break;
        }
      }
      placement = "before";
    } else {
      let lastSourceIndex = -1;
      for (let index = events.length - 1; index >= 0; index -= 1) {
        if (sourceIds.has(events[index].event_id)) {
          lastSourceIndex = index;
          break;
        }
      }
      targetEventId = events.slice(lastSourceIndex + 1)
        .find((event) => !sourceIds.has(event.event_id))?.event_id;
      placement = "after";
    }
  } else {
    targetEventId = move.targetEventId;
    placement = move.placement;
  }

  if (!targetEventId || sourceIds.has(targetEventId)) return events;

  const next = events.filter((event) => !sourceIds.has(event.event_id));
  const targetIndex = next.findIndex((event) => event.event_id === targetEventId);
  if (targetIndex < 0) return events;
  next.splice(targetIndex + (placement === "after" ? 1 : 0), 0, ...sources);

  return next.every((event, index) => event.event_id === events[index]?.event_id)
    ? events
    : next;
}
