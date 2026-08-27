import { eventInsertionIndex } from "./eventInsertion";
import type { CueEvent } from "./types";

export type EventDuplicationResult = {
  events: CueEvent[];
  duplicateEventIds: string[];
};

export function duplicateEventBlock(
  events: readonly CueEvent[],
  selectedEventIds: Iterable<string>,
  createEventId: (source: CueEvent, index: number) => string,
): EventDuplicationResult {
  const selected = new Set(selectedEventIds);
  const sources = events.filter((event) => selected.has(event.event_id));
  if (sources.length === 0) return { events: events.slice(), duplicateEventIds: [] };

  const usedIds = new Set(events.map((event) => event.event_id));
  const duplicates = sources.map((source, index) => {
    const eventId = createEventId(source, index);
    if (!eventId || usedIds.has(eventId)) {
      throw new Error(`duplicated event ID must be fresh: ${eventId || "<empty>"}`);
    }
    usedIds.add(eventId);
    return { ...structuredClone(source), event_id: eventId };
  });
  const insertionIndex = eventInsertionIndex(events, {
    anchorEventId: sources.at(-1)!.event_id,
    placement: "after",
  });
  const next = events.slice();
  next.splice(insertionIndex, 0, ...duplicates);
  return {
    events: next,
    duplicateEventIds: duplicates.map((event) => event.event_id),
  };
}
