import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";

import App from "./App";
import { demoProject } from "./demoProject";
import { useProjectStore } from "./projectStore";

const actEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

describe("ProjectRail interactions", () => {
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
    const project = structuredClone(demoProject);
    const chapter = project.chapters[0];
    const sourceScene = chapter.scenes[0];
    const libraryScene = {
      ...structuredClone(sourceScene),
      scene_id: "scene/library",
      title: "图书馆",
      cues: [{
        ...structuredClone(sourceScene.cues[0]),
        cue_id: "cue/library/001",
        title: "查找资料",
      }],
    };
    libraryScene.cues[0].events = libraryScene.cues[0].events.map((event, index) => ({
      ...event,
      event_id: `${event.event_id}/library-${index + 1}`,
    }));
    chapter.scenes.push(libraryScene);
    useProjectStore.getState().replaceProject(project);
    useProjectStore.getState().setMode("simple");
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    act(() => root.render(<App />));
  });

  afterEach(() => {
    act(() => root?.unmount());
    container.remove();
  });

  it("navigates visible tree items with one roving tab stop", () => {
    const nodes = Array.from(container.querySelectorAll<HTMLButtonElement>("[data-project-tree-item]"));
    expect(nodes.map((node) => node.textContent?.trim())).toEqual(["序章", "研讨会室", "图书馆"]);
    expect(nodes.map((node) => node.tabIndex)).toEqual([-1, 0, -1]);
    expect(nodes[1].getAttribute("aria-current")).toBe("page");

    const revision = useProjectStore.getState().revision;
    const historyLength = useProjectStore.getState().history.length;
    act(() => {
      nodes[1].focus();
      nodes[1].dispatchEvent(new KeyboardEvent("keydown", {
        bubbles: true,
        cancelable: true,
        key: "ArrowDown",
      }));
    });

    expect(document.activeElement).toBe(nodes[2]);
    expect(useProjectStore.getState().selectedSceneId).toBe("scene/library");
    expect(nodes.map((node) => node.tabIndex)).toEqual([-1, -1, 0]);
    expect(nodes[2].getAttribute("aria-current")).toBe("page");
    expect(useProjectStore.getState().revision).toBe(revision);
    expect(useProjectStore.getState().history).toHaveLength(historyLength);

    act(() => nodes[2].dispatchEvent(new KeyboardEvent("keydown", {
      bubbles: true,
      cancelable: true,
      key: "Home",
    })));
    expect(document.activeElement).toBe(nodes[0]);
    expect(useProjectStore.getState().selectedChapterId).toBe("chapter/prologue");
  });
});
