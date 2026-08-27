import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { ProfessionalEventList } from "./App";
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

describe("professional event pointer reorder", () => {
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
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    act(() => root.render(<ProfessionalEventList />));
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
});
