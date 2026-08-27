import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";

import App from "./App";
import { demoProject } from "./demoProject";
import { useProjectStore } from "./projectStore";

const actEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

describe("simple stage slot interactions", () => {
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
    useProjectStore.getState().setMode("simple");
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    act(() => root.render(<App />));
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it("navigates five visible slots with one roving tab stop", () => {
    const slots = Array.from(container.querySelectorAll<HTMLButtonElement>(".stage-slot"));
    expect(slots).toHaveLength(5);
    expect(slots.map((slot) => slot.tabIndex)).toEqual([0, -1, -1, -1, -1]);

    const before = useProjectStore.getState();
    const revision = before.revision;
    const historyLength = before.history.length;

    act(() => {
      slots[0].focus();
      slots[0].dispatchEvent(new KeyboardEvent("keydown", {
        bubbles: true,
        cancelable: true,
        key: "ArrowRight",
      }));
    });

    expect(document.activeElement).toBe(slots[1]);
    expect(useProjectStore.getState().selectedSlot).toBe(2);
    expect(useProjectStore.getState().inspectorTab).toBe("character");
    expect(slots.map((slot) => slot.tabIndex)).toEqual([-1, 0, -1, -1, -1]);
    expect(useProjectStore.getState().revision).toBe(revision);
    expect(useProjectStore.getState().history).toHaveLength(historyLength);

    act(() => slots[1].dispatchEvent(new KeyboardEvent("keydown", {
      bubbles: true,
      cancelable: true,
      key: "End",
    })));
    expect(document.activeElement).toBe(slots[4]);
    expect(useProjectStore.getState().selectedSlot).toBe(5);

    act(() => slots[4].dispatchEvent(new KeyboardEvent("keydown", {
      bubbles: true,
      cancelable: true,
      key: "Home",
    })));
    expect(document.activeElement).toBe(slots[0]);
    expect(useProjectStore.getState().selectedSlot).toBe(1);
  });
});
