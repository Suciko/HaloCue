import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";

import App from "./App";
import { demoProject } from "./demoProject";
import { evaluateScene } from "./sceneEvaluation";
import { firstScene, useProjectStore } from "./projectStore";
import { buildShotTimeline } from "./shotTimeline";

const actEnvironment = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

describe("professional shot timeline workspace", () => {
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
    project.chapters[0].scenes[0].cues[0].events.splice(3, 0, {
      event_id: "event/yuuka-nod",
      kind: "character-motion",
      character_id: "character/yuuka",
      slot: 1,
      motion_id: "motion/nod",
      duration_ms: 500,
      wait_for_completion: false,
    });
    useProjectStore.getState().replaceProject(project);
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

  it("switches between script and shot views without touching project history", () => {
    const before = useProjectStore.getState();
    const revision = before.revision;
    const historyLength = before.history.length;
    const project = JSON.stringify(before.project);
    const shotTab = Array.from(container.querySelectorAll<HTMLButtonElement>("[role=tab]")
      .values()).find((button) => button.textContent?.includes("镜头时间轴"));

    expect(shotTab).toBeDefined();
    act(() => shotTab?.click());

    expect(container.querySelector(".shot-timeline-panel")).not.toBeNull();
    expect(container.querySelector(".event-workbench")).toBeNull();
    const after = useProjectStore.getState();
    expect(after.revision).toBe(revision);
    expect(after.history).toHaveLength(historyLength);
    expect(JSON.stringify(after.project)).toBe(project);
  });

  it("keeps the shared selection and playhead while keyboard navigation moves professional tabs", () => {
    const tabs = Array.from(container.querySelectorAll<HTMLButtonElement>("[role=tab]"));
    const scriptTab = tabs.find((button) => button.textContent?.includes("脚本"))!;
    const shotTab = tabs.find((button) => button.textContent?.includes("镜头时间轴"))!;

    expect(scriptTab.tabIndex).toBe(0);
    expect(shotTab.tabIndex).toBe(-1);
    expect(scriptTab.getAttribute("aria-controls")).toBe("professional-panel-script");
    expect(container.querySelector("#professional-panel-script[role=tabpanel]")).not.toBeNull();

    act(() => {
      useProjectStore.getState().selectEvent("event/dialogue/001");
      useProjectStore.getState().setPreviewPlayheadFrame(37);
      scriptTab.focus();
      scriptTab.dispatchEvent(new KeyboardEvent("keydown", {
        bubbles: true,
        cancelable: true,
        key: "ArrowRight",
      }));
    });

    expect(shotTab.getAttribute("aria-selected")).toBe("true");
    expect(shotTab.tabIndex).toBe(0);
    expect(document.activeElement).toBe(shotTab);
    expect(useProjectStore.getState().selectedEventId).toBe("event/dialogue/001");
    expect(useProjectStore.getState().previewPlayheadFrame).toBe(37);
    expect(container.querySelector("#professional-panel-shot[role=tabpanel]")).not.toBeNull();

    act(() => shotTab.dispatchEvent(new KeyboardEvent("keydown", {
      bubbles: true,
      cancelable: true,
      key: "Home",
    })));

    expect(document.activeElement).toBe(scriptTab);
    expect(scriptTab.getAttribute("aria-selected")).toBe("true");
    expect(useProjectStore.getState().selectedEventId).toBe("event/dialogue/001");
    expect(useProjectStore.getState().previewPlayheadFrame).toBe(37);
  });

  it("selects a clip and locates preview to its start frame", () => {
    const scene = firstScene(useProjectStore.getState().project);
    const cue = scene.cues[0];
    const evaluation = evaluateScene(useProjectStore.getState().project, cue.cue_id, { sceneId: scene.scene_id });
    const expectedFrame = evaluation.timeline.events.find((event) => event.event_id === "event/yuuka-nod")?.start_frame;
    const shotTab = Array.from(container.querySelectorAll<HTMLButtonElement>("[role=tab]")
      .values()).find((button) => button.textContent?.includes("镜头时间轴"));
    act(() => shotTab?.click());
    const clip = container.querySelector<HTMLButtonElement>('.shot-clip[data-event-id="event/yuuka-nod"]');

    expect(clip).not.toBeNull();
    act(() => clip?.click());

    expect(useProjectStore.getState().selectedEventId).toBe("event/yuuka-nod");
    expect(useProjectStore.getState().previewPlayheadFrame).toBe(expectedFrame);
    expect(clip?.classList.contains("is-selected")).toBe(true);
  });

  it("locates the playhead when a track lane is clicked", () => {
    const shotTab = Array.from(container.querySelectorAll<HTMLButtonElement>("[role=tab]")
      .values()).find((button) => button.textContent?.includes("镜头时间轴"));
    act(() => shotTab?.click());
    const lane = container.querySelector<HTMLElement>('[data-shot-track="dialogue"]');
    expect(lane).not.toBeNull();
    lane!.getBoundingClientRect = () => ({ left: 0, width: 100 } as DOMRect);

    act(() => lane?.dispatchEvent(new MouseEvent("click", { bubbles: true, clientX: 50 })));

    const state = useProjectStore.getState();
    const timeline = evaluateScene(state.project, state.selectedCueId, { sceneId: state.selectedSceneId }).timeline;
    const scene = firstScene(state.project);
    const cue = scene.cues.find((item) => item.cue_id === state.selectedCueId)!;
    const projection = buildShotTimeline({ sceneId: scene.scene_id, cue, timeline });
    expect(state.previewPlayheadFrame).toBe(Math.round(
      projection.start_frame + (projection.end_frame - projection.start_frame) / 2,
    ));
  });

  it("exposes the selected event range and an explicit preview locate action", () => {
    const scene = firstScene(useProjectStore.getState().project);
    const cue = scene.cues[0];
    const evaluation = evaluateScene(useProjectStore.getState().project, cue.cue_id, { sceneId: scene.scene_id });
    const selected = evaluation.timeline.events.find((event) => event.event_id === "event/yuuka-nod")!;
    const shotTab = Array.from(container.querySelectorAll<HTMLButtonElement>("[role=tab]")
      .values()).find((button) => button.textContent?.includes("镜头时间轴"));
    act(() => shotTab?.click());
    const clip = container.querySelector<HTMLButtonElement>('.shot-clip[data-event-id="event/yuuka-nod"]');
    act(() => clip?.click());

    const range = container.querySelector<HTMLElement>("[data-preview-selection-range]");
    const locate = container.querySelector<HTMLButtonElement>("[data-preview-locate]");
    expect(range?.textContent).toContain(`F${selected.start_frame}-${selected.end_frame}`);
    expect(locate).not.toBeNull();
    const revision = useProjectStore.getState().revision;
    act(() => locate?.click());
    expect(useProjectStore.getState().previewPlayheadFrame).toBe(selected.start_frame);
    expect(useProjectStore.getState().revision).toBe(revision);
  });

  it("shows selected event timing as a read-only timeline projection", () => {
    const scene = firstScene(useProjectStore.getState().project);
    const cue = scene.cues[0];
    const evaluation = evaluateScene(useProjectStore.getState().project, cue.cue_id, { sceneId: scene.scene_id });
    const selected = evaluation.timeline.events.find((event) => event.event_id === "event/yuuka-nod")!;
    const shotTab = Array.from(container.querySelectorAll<HTMLButtonElement>("[role=tab]")
      .values()).find((button) => button.textContent?.includes("镜头时间轴"));
    act(() => shotTab?.click());
    const clip = container.querySelector<HTMLButtonElement>('.shot-clip[data-event-id="event/yuuka-nod"]');
    act(() => clip?.click());

    const timing = container.querySelector<HTMLElement>("[data-event-timing-projection]");
    expect(timing?.textContent).toContain("Character");
    expect(timing?.textContent).toContain(`F${selected.start_frame}`);
    expect(timing?.textContent).toContain(`F${selected.end_frame}`);
    expect(timing?.textContent).toContain(`${selected.duration_frames} 帧`);
    expect(timing?.textContent).toContain("与后续事件并行");
    expect(timing?.querySelector("input, select, textarea, button")).toBeNull();
  });
});
