import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";

import App from "./App";
import { demoProject } from "./demoProject";
import { useProjectStore } from "./projectStore";

const actEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

describe("simple Inspector tabs", () => {
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
    useProjectStore.getState().setInspectorTab("dialogue");
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    act(() => root.render(<App />));
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it("navigates tabs with one roving tab stop without changing project history", () => {
    const tabs = Array.from(container.querySelectorAll<HTMLButtonElement>(
      '.inspector-tabs [role="tab"]',
    ));
    expect(tabs).toHaveLength(3);
    expect(tabs.map((tab) => tab.tabIndex)).toEqual([-1, 0, -1]);
    expect(tabs.map((tab) => tab.getAttribute("aria-selected"))).toEqual([
      "false",
      "true",
      "false",
    ]);

    const before = useProjectStore.getState();
    const revision = before.revision;
    const historyLength = before.history.length;

    act(() => {
      tabs[1].focus();
      tabs[1].dispatchEvent(new KeyboardEvent("keydown", {
        bubbles: true,
        cancelable: true,
        key: "ArrowRight",
      }));
    });

    expect(document.activeElement).toBe(tabs[2]);
    expect(useProjectStore.getState().inspectorTab).toBe("environment");
    expect(tabs.map((tab) => tab.tabIndex)).toEqual([-1, -1, 0]);
    expect(tabs.map((tab) => tab.getAttribute("aria-selected"))).toEqual([
      "false",
      "false",
      "true",
    ]);
    expect(useProjectStore.getState().revision).toBe(revision);
    expect(useProjectStore.getState().history).toHaveLength(historyLength);

    act(() => tabs[2].dispatchEvent(new KeyboardEvent("keydown", {
      bubbles: true,
      cancelable: true,
      key: "Home",
    })));
    expect(document.activeElement).toBe(tabs[0]);
    expect(useProjectStore.getState().inspectorTab).toBe("character");
  });
});
