export type EventSelectionMode = "replace" | "toggle" | "range" | "add-range";

export type EventSelectionState = {
  selectedEventId: string | null;
  selectedEventIds: string[];
  eventSelectionAnchorId: string | null;
};

type StableEvent = { event_id: string };

function orderedIds(events: readonly StableEvent[], ids: Iterable<string>): string[] {
  const selected = new Set(ids);
  return events.filter((event) => selected.has(event.event_id)).map((event) => event.event_id);
}

export function repairEventSelection(
  events: readonly StableEvent[],
  selection: EventSelectionState,
): EventSelectionState {
  const eventIds = new Set(events.map((event) => event.event_id));
  let selectedEventIds = orderedIds(events, selection.selectedEventIds);
  let selectedEventId = selection.selectedEventId && eventIds.has(selection.selectedEventId)
    ? selection.selectedEventId
    : selectedEventIds[0] ?? events[0]?.event_id ?? null;
  if (selectedEventId && !selectedEventIds.includes(selectedEventId)) {
    selectedEventIds = orderedIds(events, [...selectedEventIds, selectedEventId]);
  }
  if (!selectedEventId) selectedEventIds = [];
  const eventSelectionAnchorId = selection.eventSelectionAnchorId
    && eventIds.has(selection.eventSelectionAnchorId)
    ? selection.eventSelectionAnchorId
    : selectedEventId;
  return { selectedEventId, selectedEventIds, eventSelectionAnchorId };
}

export function selectEventIds(
  events: readonly StableEvent[],
  current: EventSelectionState,
  targetEventId: string,
  mode: EventSelectionMode = "replace",
): EventSelectionState {
  if (!events.some((event) => event.event_id === targetEventId)) return current;
  const normalized = repairEventSelection(events, current);
  if (mode === "replace") {
    return {
      selectedEventId: targetEventId,
      selectedEventIds: [targetEventId],
      eventSelectionAnchorId: targetEventId,
    };
  }
  if (mode === "toggle") {
    if (!normalized.selectedEventIds.includes(targetEventId)) {
      return {
        selectedEventId: targetEventId,
        selectedEventIds: orderedIds(events, [...normalized.selectedEventIds, targetEventId]),
        eventSelectionAnchorId: targetEventId,
      };
    }
    if (normalized.selectedEventIds.length === 1) return normalized;
    const selectedEventIds = normalized.selectedEventIds.filter((eventId) => eventId !== targetEventId);
    const selectedEventId = normalized.selectedEventId === targetEventId
      ? selectedEventIds[0]
      : normalized.selectedEventId;
    return {
      selectedEventId,
      selectedEventIds,
      eventSelectionAnchorId: normalized.eventSelectionAnchorId === targetEventId
        ? selectedEventId : normalized.eventSelectionAnchorId,
    };
  }

  const anchorId = normalized.eventSelectionAnchorId ?? normalized.selectedEventId ?? targetEventId;
  const anchorIndex = events.findIndex((event) => event.event_id === anchorId);
  const targetIndex = events.findIndex((event) => event.event_id === targetEventId);
  const rangeIds = events
    .slice(Math.min(anchorIndex, targetIndex), Math.max(anchorIndex, targetIndex) + 1)
    .map((event) => event.event_id);
  return {
    selectedEventId: targetEventId,
    selectedEventIds: mode === "add-range"
      ? orderedIds(events, [...normalized.selectedEventIds, ...rangeIds])
      : rangeIds,
    eventSelectionAnchorId: anchorId,
  };
}

export function selectionAfterEventDeletion(
  events: readonly StableEvent[],
  deletedEventIds: Iterable<string>,
): EventSelectionState {
  const deleted = new Set(deletedEventIds);
  const firstDeletedIndex = events.findIndex((event) => deleted.has(event.event_id));
  const remaining = events.filter((event) => !deleted.has(event.event_id));
  const selectedEventId = firstDeletedIndex < 0 || remaining.length === 0
    ? remaining[0]?.event_id ?? null
    : remaining[Math.min(firstDeletedIndex, remaining.length - 1)].event_id;
  return {
    selectedEventId,
    selectedEventIds: selectedEventId ? [selectedEventId] : [],
    eventSelectionAnchorId: selectedEventId,
  };
}
