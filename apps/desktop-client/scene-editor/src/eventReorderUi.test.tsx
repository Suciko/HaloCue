import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { demoProject } from "./demoProject";
import { firstScene, useProjectStore } from "./projectStore";

type MutableDataTransfer = {
  dropEffect: string;
  effectAllowed: string;
  getData: ReturnType<typeof vi.fn>;
  setData: ReturnType<typeof vi.fn>;
};

const actEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

function dragEvent(type: string, dataTransfer: MutableDataTransfer, clientY = 0): Event {
  const event = new MouseEvent(type, { bubbles: true, cancelable: true, clientY });
  Object.defineProperty(event, "dataTransfer", { value: dataTransfer });
  return event;
}

describe("professional event list interactions", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeAll(() => {
    actEnvironment.IS_REACT_ACT_ENVIRONMENT = true;
  });

  afterAll(() => {
    delete actEnvironment.IS_REACT_ACT_ENVIRONMENT;
  });

  beforeEach(() => {
    localStorage.clear();
    useProjectStore.getState().replaceProject(structuredClone(demoProject));
    useProjectStore.getState().setMode("professional");
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    act(() => root.render(<App />));
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it("shows the insertion target and commits one stable-ID drop", () => {
    const handles = Array.from(container.querySelectorAll<HTMLButtonElement>(".event-drag-handle"));
    const rows = Array.from(container.querySelectorAll<HTMLDivElement>(".event-row"));
    const originalOrder = firstScene(useProjectStore.getState().project).cues[0].events
      .map((event) => event.event_id);
    const revisionBefore = useProjectStore.getState().revision;
    const historyBefore = useProjectStore.getState().history.length;
    const dataTransfer: MutableDataTransfer = {
      dropEffect: "none",
      effectAllowed: "none",
      getData: vi.fn(),
      setData: vi.fn(),
    };
    vi.spyOn(rows[2], "getBoundingClientRect").mockReturnValue({
      top: 100,
      height: 50,
    } as DOMRect);

    act(() => handles[1].dispatchEvent(dragEvent("dragstart", dataTransfer)));
    act(() => rows[2].dispatchEvent(dragEvent("dragover", dataTransfer, 140)));

    expect(rows[1].classList.contains("is-dragging")).toBe(true);
    expect(rows[2].classList.contains("is-drop-after")).toBe(true);
    expect(dataTransfer.effectAllowed).toBe("move");
    expect(dataTransfer.dropEffect).toBe("move");

    act(() => rows[2].dispatchEvent(dragEvent("drop", dataTransfer, 140)));

    const state = useProjectStore.getState();
    expect(firstScene(state.project).cues[0].events.map((event) => event.event_id))
      .toEqual([originalOrder[0], originalOrder[2], originalOrder[1], originalOrder[3]]);
    expect(state.selectedEventId).toBe(originalOrder[1]);
    expect(state.revision).toBe(revisionBefore + 1);
    expect(state.history).toHaveLength(historyBefore + 1);
    expect(container.querySelector(".event-row.is-dragging")).toBeNull();
    expect(container.querySelector(".event-row.is-drop-after")).toBeNull();
    expect(container.querySelector(".sr-only")?.textContent).toBe("角色入场 已移动到第 3 项");
  });

  it("drags the selected range as one ordered block", () => {
    const originalOrder = firstScene(useProjectStore.getState().project).cues[0].events
      .map((event) => event.event_id);
    const historyBefore = useProjectStore.getState().history.length;
    let mains = Array.from(container.querySelectorAll<HTMLButtonElement>(".event-main"));
    act(() => mains[1].click());
    act(() => mains[2].dispatchEvent(new MouseEvent("click", {
      bubbles: true,
      cancelable: true,
      shiftKey: true,
    })));
    const handles = Array.from(container.querySelectorAll<HTMLButtonElement>(".event-drag-handle"));
    const rows = Array.from(container.querySelectorAll<HTMLDivElement>(".event-row"));
    const dataTransfer: MutableDataTransfer = {
      dropEffect: "none",
      effectAllowed: "none",
      getData: vi.fn(),
      setData: vi.fn(),
    };
    vi.spyOn(rows[3], "getBoundingClientRect").mockReturnValue({
      top: 100,
      height: 50,
    } as DOMRect);

    act(() => handles[1].dispatchEvent(dragEvent("dragstart", dataTransfer)));
    expect(rows[1].classList.contains("is-dragging")).toBe(true);
    expect(rows[2].classList.contains("is-dragging")).toBe(true);
    act(() => rows[3].dispatchEvent(dragEvent("dragover", dataTransfer, 140)));
    expect(rows[3].classList.contains("is-drop-after")).toBe(true);
    act(() => rows[3].dispatchEvent(dragEvent("drop", dataTransfer, 140)));

    let state = useProjectStore.getState();
    expect(firstScene(state.project).cues[0].events.map((event) => event.event_id))
      .toEqual([originalOrder[0], originalOrder[3], originalOrder[1], originalOrder[2]]);
    expect(state.selectedEventIds).toEqual(originalOrder.slice(1, 3));
    expect(state.selectedEventId).toBe(originalOrder[2]);
    expect(state.history).toHaveLength(historyBefore + 1);
    expect(container.querySelector(".sr-only")?.textContent)
      .toBe("2 个事件已移动到第 3–4 项");

    act(() => state.undo());
    state = useProjectStore.getState();
    expect(firstScene(state.project).cues[0].events.map((event) => event.event_id))
      .toEqual(originalOrder);
    expect(state.selectedEventIds).toEqual(originalOrder.slice(1, 3));
    mains = Array.from(container.querySelectorAll<HTMLButtonElement>(".event-main"));
    expect(mains[1].getAttribute("aria-pressed")).toBe("true");
    expect(mains[2].getAttribute("aria-pressed")).toBe("true");
  });

  it("uses the same selected-block command for keyboard and direction controls", () => {
    const originalOrder = firstScene(useProjectStore.getState().project).cues[0].events
      .map((event) => event.event_id);
    let mains = Array.from(container.querySelectorAll<HTMLButtonElement>(".event-main"));
    act(() => mains[1].click());
    act(() => mains[2].dispatchEvent(new MouseEvent("click", {
      bubbles: true,
      cancelable: true,
      shiftKey: true,
    })));
    let handles = Array.from(container.querySelectorAll<HTMLButtonElement>(".event-drag-handle"));
    act(() => handles[1].dispatchEvent(new KeyboardEvent("keydown", {
      bubbles: true,
      cancelable: true,
      key: "End",
    })));

    let state = useProjectStore.getState();
    expect(firstScene(state.project).cues[0].events.map((event) => event.event_id))
      .toEqual([originalOrder[0], originalOrder[3], originalOrder[1], originalOrder[2]]);
    expect(state.selectedEventIds).toEqual(originalOrder.slice(1, 3));

    act(() => state.undo());
    const moveUp = container.querySelector<HTMLButtonElement>(
      '.event-row:nth-of-type(3) .event-actions button[aria-label="上移已选 2 个事件"]',
    ) ?? Array.from(container.querySelectorAll<HTMLButtonElement>(
      '.event-actions button[aria-label="上移已选 2 个事件"]',
    ))[0];
    expect(moveUp).toBeDefined();
    act(() => moveUp?.click());

    state = useProjectStore.getState();
    expect(firstScene(state.project).cues[0].events.map((event) => event.event_id))
      .toEqual([originalOrder[1], originalOrder[2], originalOrder[0], originalOrder[3]]);
    expect(state.selectedEventIds).toEqual(originalOrder.slice(1, 3));
    expect(container.querySelector(".sr-only")?.textContent)
      .toBe("2 个事件已移动到第 1–2 项");
    handles = Array.from(container.querySelectorAll<HTMLButtonElement>(".event-drag-handle"));
    expect(handles[0].getAttribute("aria-label")).toContain("重排已选 2 个事件");
  });

  it("inserts before the selected stable event and restores the anchor on undo", () => {
    const originalOrder = firstScene(useProjectStore.getState().project).cues[0].events
      .map((event) => event.event_id);
    const anchorId = originalOrder[1];
    const historyBefore = useProjectStore.getState().history.length;
    const eventRows = Array.from(container.querySelectorAll<HTMLButtonElement>(".event-main"));
    const placementButtons = Array.from(
      container.querySelectorAll<HTMLButtonElement>(".event-insert-position button"),
    );
    const waitButton = Array.from(
      container.querySelectorAll<HTMLButtonElement>(".event-add-options > button"),
    ).find((button) => button.textContent?.trim() === "等待");

    act(() => eventRows[1].click());
    act(() => placementButtons[0].click());
    expect(container.querySelector(".event-add-menu summary")?.textContent).toContain("在 02 前添加");
    expect(waitButton).toBeDefined();
    act(() => waitButton?.click());

    let state = useProjectStore.getState();
    const insertedId = state.selectedEventId;
    const events = firstScene(state.project).cues[0].events;
    expect(events.map((event) => event.event_id))
      .toEqual([originalOrder[0], insertedId, ...originalOrder.slice(1)]);
    expect(events[1]).toEqual(expect.objectContaining({ event_id: insertedId, kind: "wait" }));
    expect(state.history).toHaveLength(historyBefore + 1);

    act(() => state.undo());
    state = useProjectStore.getState();
    expect(firstScene(state.project).cues[0].events.map((event) => event.event_id))
      .toEqual(originalOrder);
    expect(state.selectedEventId).toBe(anchorId);
  });

  it("selects a shift range and deletes the batch through one visible command", () => {
    const originalOrder = firstScene(useProjectStore.getState().project).cues[0].events
      .map((event) => event.event_id);
    const historyBefore = useProjectStore.getState().history.length;
    let eventRows = Array.from(container.querySelectorAll<HTMLButtonElement>(".event-main"));

    act(() => eventRows[1].click());
    act(() => eventRows[3].dispatchEvent(new MouseEvent("click", {
      bubbles: true,
      cancelable: true,
      shiftKey: true,
    })));

    let state = useProjectStore.getState();
    expect(state.selectedEventId).toBe(originalOrder[3]);
    expect(state.selectedEventIds).toEqual(originalOrder.slice(1));
    expect(state.eventSelectionAnchorId).toBe(originalOrder[1]);
    expect(state.history).toHaveLength(historyBefore);
    expect(container.querySelectorAll(".event-row.is-selected")).toHaveLength(3);
    const batchDelete = container.querySelector<HTMLButtonElement>(
      ".event-selection-toolbar button.is-danger",
    );
    expect(batchDelete).toBeDefined();

    act(() => batchDelete?.click());
    state = useProjectStore.getState();
    expect(firstScene(state.project).cues[0].events.map((event) => event.event_id))
      .toEqual([originalOrder[0]]);
    expect(state.selectedEventId).toBe(originalOrder[0]);
    expect(state.history).toHaveLength(historyBefore + 1);
    expect(container.querySelector(".sr-only")?.textContent).toBe("3 个事件已删除");

    act(() => state.undo());
    state = useProjectStore.getState();
    expect(firstScene(state.project).cues[0].events.map((event) => event.event_id))
      .toEqual(originalOrder);
    expect(state.selectedEventId).toBe(originalOrder[3]);
    expect(state.selectedEventIds).toEqual(originalOrder.slice(1));
    eventRows = Array.from(container.querySelectorAll<HTMLButtonElement>(".event-main"));
    expect(eventRows[3].getAttribute("aria-pressed")).toBe("true");
  });

  it("duplicates the selected range as one newly selected block", () => {
    const originalEvents = firstScene(useProjectStore.getState().project).cues[0].events;
    const originalOrder = originalEvents.map((event) => event.event_id);
    const historyBefore = useProjectStore.getState().history.length;
    let eventRows = Array.from(container.querySelectorAll<HTMLButtonElement>(".event-main"));
    act(() => eventRows[1].click());
    act(() => eventRows[3].dispatchEvent(new MouseEvent("click", {
      bubbles: true,
      cancelable: true,
      shiftKey: true,
    })));
    const duplicateButton = container.querySelector<HTMLButtonElement>(
      ".event-selection-toolbar button:not(.is-danger)",
    );
    expect(duplicateButton?.textContent?.trim()).toBe("复制");

    act(() => duplicateButton?.click());

    let state = useProjectStore.getState();
    const events = firstScene(state.project).cues[0].events;
    const duplicateIds = events.slice(4).map((event) => event.event_id);
    expect(events.map((event) => event.event_id)).toEqual([...originalOrder, ...duplicateIds]);
    expect(duplicateIds).toHaveLength(3);
    expect(state.selectedEventIds).toEqual(duplicateIds);
    expect(state.selectedEventId).toBe(duplicateIds[2]);
    expect(state.history).toHaveLength(historyBefore + 1);
    expect(container.querySelectorAll(".event-row.is-selected")).toHaveLength(3);
    expect(container.querySelector(".sr-only")?.textContent).toBe("3 个事件已复制");

    act(() => state.undo());
    state = useProjectStore.getState();
    expect(firstScene(state.project).cues[0].events.map((event) => event.event_id))
      .toEqual(originalOrder);
    expect(state.selectedEventIds).toEqual(originalOrder.slice(1));
    eventRows = Array.from(container.querySelectorAll<HTMLButtonElement>(".event-main"));
    expect(eventRows).toHaveLength(4);
  });
});
