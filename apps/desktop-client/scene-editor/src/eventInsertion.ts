export type EventInsertPlacement = "before" | "after";

export type EventInsertion = {
  anchorEventId: string | null;
  placement: EventInsertPlacement;
};

type StableEvent = { event_id: string };

export function eventInsertionIndex(
  events: readonly StableEvent[],
  insertion?: EventInsertion,
): number {
  if (!insertion?.anchorEventId) return events.length;
  const anchorIndex = events.findIndex((event) => event.event_id === insertion.anchorEventId);
  if (anchorIndex < 0) return events.length;
  return anchorIndex + (insertion.placement === "after" ? 1 : 0);
}
