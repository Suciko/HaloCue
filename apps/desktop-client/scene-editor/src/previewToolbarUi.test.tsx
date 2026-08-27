import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { demoProject } from "./demoProject";
import { evaluateScene } from "./sceneEvaluation";
import { useProjectStore } from "./projectStore";

const actEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

describe("preview toolbar selection playback", () => {
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
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const renderEditor = (mode: "simple" | "professional") => {
    useProjectStore.getState().replaceProject(structuredClone(demoProject));
    useProjectStore.getState().setMode(mode);
    act(() => root.render(<App />));
  };

  it("plays the selected event range without changing authored history", () => {
    renderEditor("professional");
    const play = vi.fn();
    const controller = {
      applyIntent: vi.fn(),
      generation: 1,
      isCurrent: () => true,
      scene_id: "scene/conference-room",
      timeline: null,
      performance: null,
      seekFrame: vi.fn(),
      play,
      dispose: vi.fn(),
    };
    const iframe = container.querySelector<HTMLIFrameElement>("iframe")!;
    Object.assign(iframe.contentWindow!, {
      HaloCueScenePreview: {
        mount: vi.fn((_descriptor, _root, options) => {
          controller.timeline = options?.timeline || null;
          controller.performance = options?.performance || null;
          return controller;
        }),
      },
    });
    act(() => iframe.dispatchEvent(new Event("load")));

    act(() => useProjectStore.getState().selectEvent("event/dialogue/001"));
    const state = useProjectStore.getState();
    const evaluation = evaluateScene(state.project, state.selectedCueId, {
      sceneId: state.selectedSceneId,
    });
    const selected = evaluation.timeline.events.find(
      (event) => event.event_id === "event/dialogue/001",
    )!;
    const playSelection = container.querySelector<HTMLButtonElement>(
      "[data-preview-play-selection]",
    );
    expect(playSelection).not.toBeNull();
    expect(playSelection?.textContent).toContain("播放所选");
    const revision = state.revision;
    const historyLength = state.history.length;

    act(() => playSelection?.click());

    expect(play).toHaveBeenCalledWith({
      fromFrame: selected.start_frame,
      toFrame: selected.end_frame - 1,
    });
    expect(useProjectStore.getState().revision).toBe(revision);
    expect(useProjectStore.getState().history).toHaveLength(historyLength);
  });

  it("plays the complete selected Cue range in Simple mode", () => {
    renderEditor("simple");
    const play = vi.fn();
    const controller = {
      applyIntent: vi.fn(),
      generation: 1,
      isCurrent: () => true,
      scene_id: "scene/conference-room",
      timeline: null,
      performance: null,
      seekFrame: vi.fn(),
      play,
      dispose: vi.fn(),
    };
    const iframe = container.querySelector<HTMLIFrameElement>("iframe")!;
    Object.assign(iframe.contentWindow!, {
      HaloCueScenePreview: {
        mount: vi.fn((_descriptor, _root, options) => {
          controller.timeline = options?.timeline || null;
          controller.performance = options?.performance || null;
          return controller;
        }),
      },
    });
    act(() => iframe.dispatchEvent(new Event("load")));

    const state = useProjectStore.getState();
    const scene = state.project.chapters[0].scenes[0];
    const cue = scene.cues.find((item) => item.cue_id === state.selectedCueId)!;
    const evaluation = evaluateScene(state.project, cue.cue_id, { sceneId: scene.scene_id });
    const cueEventIds = new Set(cue.events.map((event) => event.event_id));
    const cueEvents = evaluation.timeline.events.filter((event) => cueEventIds.has(event.event_id));
    const expectedStart = Math.min(...cueEvents.map((event) => event.start_frame));
    const expectedEnd = Math.max(...cueEvents.map((event) => event.end_frame));
    const playSelection = container.querySelector<HTMLButtonElement>(
      "[data-preview-play-selection]",
    );
    expect(playSelection?.textContent).toContain("播放所选");

    act(() => playSelection?.click());

    expect(play).toHaveBeenCalledWith({
      fromFrame: expectedStart,
      toFrame: expectedEnd - 1,
    });
  });
});
