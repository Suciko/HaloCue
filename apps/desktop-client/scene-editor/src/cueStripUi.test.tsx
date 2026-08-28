import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";

import App from "./App";
import { demoProject } from "./demoProject";
import { useProjectStore } from "./projectStore";
import { evaluateScene } from "./sceneEvaluation";

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

  it("returns focus to a newly inserted Cue for continuous authoring", () => {
    const insertAfter = container.querySelector<HTMLButtonElement>(
      'button[aria-label="在后面插入"]',
    );
    expect(insertAfter).not.toBeNull();
    const before = useProjectStore.getState();
    const revision = before.revision;
    const historyLength = before.history.length;

    act(() => insertAfter?.click());

    const cues = Array.from(container.querySelectorAll<HTMLButtonElement>(".cue-item"));
    expect(cues).toHaveLength(4);
    expect(document.activeElement).toBe(cues[1]);
    expect(cues.map((cue) => cue.tabIndex)).toEqual([-1, 0, -1, -1]);
    expect(cues[1].getAttribute("aria-pressed")).toBe("true");
    expect(useProjectStore.getState().selectedCueId).toMatch(/^cue\//);
    expect(useProjectStore.getState().revision).toBe(revision + 1);
    expect(useProjectStore.getState().history).toHaveLength(historyLength + 1);
  });

  it("returns focus to the repaired Cue after deleting the selection", () => {
    let cues = Array.from(container.querySelectorAll<HTMLButtonElement>(".cue-item"));
    act(() => cues[1].click());
    const before = useProjectStore.getState();
    const revision = before.revision;
    const historyLength = before.history.length;
    const deleteCue = container.querySelector<HTMLButtonElement>(
      'button[aria-label="删除当前 Cue"]',
    );
    expect(deleteCue).not.toBeNull();

    act(() => deleteCue?.click());

    cues = Array.from(container.querySelectorAll<HTMLButtonElement>(".cue-item"));
    expect(cues).toHaveLength(2);
    expect(document.activeElement).toBe(cues[0]);
    expect(useProjectStore.getState().selectedCueId).toBe("cue/conference/001");
    expect(cues.map((cue) => cue.tabIndex)).toEqual([0, -1]);
    expect(cues[0].getAttribute("aria-pressed")).toBe("true");
    expect(useProjectStore.getState().revision).toBe(revision + 1);
    expect(useProjectStore.getState().history).toHaveLength(historyLength + 1);
  });

  it("shows the selected Cue range and task context in Simple mode", () => {
    const state = useProjectStore.getState();
    act(() => state.setInspectorTab("character"));
    const cue = state.project.chapters[0].scenes[0].cues[1];
    const evaluation = evaluateScene(state.project, cue.cue_id, {
      sceneId: state.selectedSceneId,
    });
    const eventIds = new Set(cue.events.map((event) => event.event_id));
    const segments = evaluation.timeline.events.filter((event) => eventIds.has(event.event_id));
    const start = Math.min(...segments.map((event) => event.start_frame));
    const end = Math.max(...segments.map((event) => event.end_frame));

    const cueButton = Array.from(container.querySelectorAll<HTMLButtonElement>(".cue-item"))
      .find((button) => button.textContent?.includes("意外来客"));
    expect(cueButton).not.toBeNull();
    act(() => cueButton?.click());

    const range = container.querySelector<HTMLElement>("[data-preview-selection-range]");
    expect(range?.textContent).toBe(`Cue F${start}-${end}`);
    expect(range?.getAttribute("data-preview-selection-kind")).toBe("cue");
    expect(useProjectStore.getState().inspectorTab).toBe("dialogue");
    expect(container.querySelector<HTMLButtonElement>('.inspector-tabs [role="tab"][aria-selected="true"]')?.textContent)
      .toContain("对白");

    const revision = useProjectStore.getState().revision;
    const locate = container.querySelector<HTMLButtonElement>("[data-preview-locate]");
    expect(locate).not.toBeNull();
    act(() => locate?.click());
    expect(useProjectStore.getState().previewPlayheadFrame).toBe(start);
    expect(useProjectStore.getState().revision).toBe(revision);
  });
});
