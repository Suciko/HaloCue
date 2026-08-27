import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";

import App from "./App";
import { demoProject } from "./demoProject";
import { firstScene, useProjectStore } from "./projectStore";

const actEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

describe("character capability trials", () => {
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
    useProjectStore.getState().setInspectorTab("character");
    useProjectStore.getState().selectSlot(1);
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    act(() => root.render(<App />));
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it("previews without history, cancels on leave, and commits once on click", () => {
    const base = structuredClone(useProjectStore.getState().project);
    const historyBefore = useProjectStore.getState().history.length;
    const revisionBefore = useProjectStore.getState().revision;
    const autosaveBefore = useProjectStore.getState().autosave;
    const expressionGroup = container.querySelector<HTMLDivElement>(
      '[role="group"][aria-label="表情能力"]',
    )!;
    const smile = Array.from(expressionGroup.querySelectorAll<HTMLButtonElement>("button"))
      .find((button) => button.textContent?.includes("微笑"))!;

    act(() => smile.dispatchEvent(new MouseEvent("pointerover", {
      bubbles: true,
      cancelable: true,
    })));

    let state = useProjectStore.getState();
    expect(state.activeTransaction?.interruption).toBe("cancel");
    expect(firstScene(state.project).cues[0].events
      .find((event) => event.kind === "enter" && event.slot === 1)?.expression_id)
      .toBe("expression/smile");
    expect(state.history).toHaveLength(historyBefore);
    expect(state.revision).toBe(revisionBefore);
    expect(state.autosave).toEqual(autosaveBefore);
    expect(expressionGroup.textContent).toContain("试演中 · 单击确认");

    act(() => expressionGroup.dispatchEvent(new MouseEvent("pointerout", {
      bubbles: true,
      cancelable: true,
      relatedTarget: document.body,
    })));
    state = useProjectStore.getState();
    expect(state.project).toEqual(base);
    expect(state.activeTransaction).toBeNull();
    expect(state.history).toHaveLength(historyBefore);
    expect(state.autosave).toEqual(autosaveBefore);

    const motionGroup = container.querySelector<HTMLDivElement>(
      '[role="group"][aria-label="动作能力"]',
    )!;
    const nod = Array.from(motionGroup.querySelectorAll<HTMLButtonElement>("button"))
      .find((button) => button.textContent?.includes("点头"))!;
    act(() => nod.click());

    state = useProjectStore.getState();
    expect(state.activeTransaction).toBeNull();
    expect(firstScene(state.project).cues[0].events
      .find((event) => event.kind === "enter" && event.slot === 1)?.motion_id)
      .toBe("motion/nod");
    expect(state.history).toHaveLength(historyBefore + 1);
    expect(state.revision).toBe(revisionBefore + 1);
    expect(state.autosave.pendingRevision).toBe(revisionBefore + 1);
    expect(motionGroup.textContent).toContain("已选");

    act(() => state.undo());
    expect(useProjectStore.getState().project).toEqual(base);
  });

  it("keeps an unknown authored state visible with an explicit diagnostic", () => {
    const project = structuredClone(demoProject);
    const enter = project.chapters[0].scenes[0].cues[0].events
      .find((event) => event.kind === "enter" && event.slot === 1)!;
    enter.expression_id = "expression/legacy";
    act(() => useProjectStore.getState().replaceProject(project));

    const unknown = Array.from(container.querySelectorAll<HTMLButtonElement>(
      '[role="group"][aria-label="表情能力"] button',
    )).find((button) => button.textContent?.includes("expression/legacy"));
    expect(unknown).toBeDefined();
    expect(unknown?.disabled).toBe(true);
    expect(unknown?.title).toContain("能力目录未注册");
    expect(unknown?.textContent).toContain("不可试演");
  });
});
