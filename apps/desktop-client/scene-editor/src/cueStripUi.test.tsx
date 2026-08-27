import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";

import App from "./App";
import { demoProject } from "./demoProject";
import { useProjectStore } from "./projectStore";

const actEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

describe("simple Cue strip interactions", () => {
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

  it("navigates the Cue strip by keyboard with one roving tab stop", () => {
    const cues = Array.from(container.querySelectorAll<HTMLButtonElement>(".cue-item"));
    expect(cues).toHaveLength(3);
    expect(cues.map((cue) => cue.tabIndex)).toEqual([0, -1, -1]);
    expect(cues[0].getAttribute("aria-pressed")).toBe("true");

    const state = useProjectStore.getState();
    act(() => state.setPreviewPlayheadFrame(37));
    const revision = state.revision;
    const historyLength = state.history.length;

    act(() => {
      cues[0].focus();
      cues[0].dispatchEvent(new KeyboardEvent("keydown", {
        bubbles: true,
        cancelable: true,
        key: "ArrowRight",
      }));
    });

    expect(document.activeElement).toBe(cues[1]);
    expect(useProjectStore.getState().selectedCueId).toBe("cue/conference/002");
    expect(cues[1].getAttribute("aria-pressed")).toBe("true");
    expect(cues.map((cue) => cue.tabIndex)).toEqual([-1, 0, -1]);
    expect(useProjectStore.getState().previewPlayheadFrame).toBeNull();
    expect(useProjectStore.getState().revision).toBe(revision);
    expect(useProjectStore.getState().history).toHaveLength(historyLength);

    act(() => cues[1].dispatchEvent(new KeyboardEvent("keydown", {
      bubbles: true,
      cancelable: true,
      key: "End",
    })));
    expect(document.activeElement).toBe(cues[2]);
    expect(useProjectStore.getState().selectedCueId).toBe("cue/conference/003");

    act(() => cues[2].dispatchEvent(new KeyboardEvent("keydown", {
      bubbles: true,
      cancelable: true,
      key: "Home",
    })));
    expect(document.activeElement).toBe(cues[0]);
    expect(useProjectStore.getState().selectedCueId).toBe("cue/conference/001");
  });
});
