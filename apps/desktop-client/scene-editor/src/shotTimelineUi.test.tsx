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

  it("switches the active Cue inside Shot Timeline without project history", () => {
    const shotTab = Array.from(container.querySelectorAll<HTMLButtonElement>("[role=tab]"))
      .find((button) => button.textContent?.includes("镜头时间轴"));
    act(() => shotTab?.click());
    const before = useProjectStore.getState();
    const revision = before.revision;
    const historyLength = before.history.length;
    const project = JSON.stringify(before.project);
    const cueSelect = container.querySelector<HTMLSelectElement>("[data-shot-cue-select]");
    expect(cueSelect).not.toBeNull();
    expect(cueSelect?.value).toBe("cue/conference/001");

    act(() => {
      if (!cueSelect) return;
      cueSelect.value = "cue/conference/002";
      cueSelect.dispatchEvent(new Event("change", { bubbles: true }));
    });

    const after = useProjectStore.getState();
    expect(after.selectedCueId).toBe("cue/conference/002");
    expect(after.selectedEventId).toBe("event/enter/koyuki");
    expect(after.previewPlayheadFrame).toBeNull();
    expect(container.querySelector("[data-shot-selection-context]")?.textContent)
      .toContain("角色入场");
    expect(after.revision).toBe(revision);
    expect(after.history).toHaveLength(historyLength);
    expect(JSON.stringify(after.project)).toBe(project);
  });

  it("shows a derived legend for sequential and non-blocking clips", () => {
    const shotTab = Array.from(container.querySelectorAll<HTMLButtonElement>("[role=tab]"))
      .find((button) => button.textContent?.includes("镜头时间轴"));
    act(() => shotTab?.click());

    const legend = container.querySelector<HTMLElement>("[data-shot-timeline-legend]");
    expect(legend).not.toBeNull();
    expect(legend?.textContent).toContain("顺序执行");
    expect(legend?.textContent).toContain("与后续事件并行");
    expect(legend?.querySelector(".is-sequential")).not.toBeNull();
    expect(legend?.querySelector(".is-parallel")).not.toBeNull();
  });

  it("marks every clip active at the shared playhead, including overlapping events", () => {
    const shotTab = Array.from(container.querySelectorAll<HTMLButtonElement>("[role=tab]"))
      .find((button) => button.textContent?.includes("镜头时间轴"));
    act(() => shotTab?.click());

    const state = useProjectStore.getState();
    const evaluation = evaluateScene(state.project, state.selectedCueId, {
      sceneId: state.selectedSceneId,
    });
    const motion = evaluation.timeline.events.find((event) => event.event_id === "event/yuuka-nod")!;
    const dialogue = evaluation.timeline.events.find((event) => event.event_id === "event/dialogue/001")!;
    expect(motion.start_frame).toBe(dialogue.start_frame);

    act(() => state.setPreviewPlayheadFrame(motion.start_frame));
    expect(container.querySelector(`.shot-clip.is-active[data-event-id="${motion.event_id}"]`)).not.toBeNull();
    expect(container.querySelector(`.shot-clip.is-active[data-event-id="${dialogue.event_id}"]`)).not.toBeNull();

    act(() => state.setPreviewPlayheadFrame(motion.end_frame));
    expect(container.querySelector(`.shot-clip.is-active[data-event-id="${motion.event_id}"]`)).toBeNull();
    expect(container.querySelector(`.shot-clip.is-active[data-event-id="${dialogue.event_id}"]`)).not.toBeNull();
  });

  it("announces the active playhead context to keyboard and assistive-technology users", () => {
    const shotTab = Array.from(container.querySelectorAll<HTMLButtonElement>("[role=tab]"))
      .find((button) => button.textContent?.includes("镜头时间轴"));
    act(() => shotTab?.click());

    const state = useProjectStore.getState();
    const evaluation = evaluateScene(state.project, state.selectedCueId, {
      sceneId: state.selectedSceneId,
    });
    const motion = evaluation.timeline.events.find((event) => event.event_id === "event/yuuka-nod")!;
    const dialogue = evaluation.timeline.events.find((event) => event.event_id === "event/dialogue/001")!;
    const frame = motion.start_frame;
    act(() => state.setPreviewPlayheadFrame(frame));

    const context = container.querySelector<HTMLElement>("[data-shot-active-context]");
    expect(context?.getAttribute("aria-live")).toBe("polite");
    expect(context?.getAttribute("aria-atomic")).toBe("true");
    expect(context?.textContent).toContain(`播放头 F${frame}`);
    expect(context?.textContent).toContain("角色动作");
    expect(context?.textContent).toContain("对白");
    expect(container.querySelector<HTMLButtonElement>(
      `.shot-clip[data-event-id="${motion.event_id}"]`,
    )?.getAttribute("aria-label")).toContain("播放头当前");
    expect(container.querySelector<HTMLButtonElement>(
      `.shot-clip[data-event-id="${dialogue.event_id}"]`,
    )?.getAttribute("aria-label")).toContain("播放头当前");
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

  it("updates selected-clip context and removes stale highlights when the Cue changes", () => {
    const shotTab = Array.from(container.querySelectorAll<HTMLButtonElement>("[role=tab]"))
      .find((button) => button.textContent?.includes("镜头时间轴"));
    act(() => shotTab?.click());

    const oldClip = container.querySelector<HTMLButtonElement>(
      '.shot-clip[data-event-id="event/yuuka-nod"]',
    );
    expect(oldClip).not.toBeNull();
    act(() => oldClip?.click());
    expect(container.querySelector("[data-shot-selection-context]")?.textContent)
      .toContain("已选");

    const nextCue = Array.from(container.querySelectorAll<HTMLButtonElement>(".tree-cue"))
      .find((button) => button.textContent?.includes("意外来客"));
    expect(nextCue).not.toBeNull();
    act(() => nextCue?.click());

    const state = useProjectStore.getState();
    expect(state.selectedCueId).toBe("cue/conference/002");
    expect(state.selectedEventId).toBe("event/enter/koyuki");
    expect(state.previewPlayheadFrame).toBeNull();
    expect(container.querySelector('.shot-clip[data-event-id="event/yuuka-nod"]')).toBeNull();
    expect(container.querySelector(".shot-clip.is-selected[data-event-id=\"event/enter/koyuki\"]"))
      .not.toBeNull();
    expect(container.querySelector("[data-shot-selection-context]")?.textContent)
      .toContain("已选");
  });

  it("navigates shot clips by keyboard order and keeps selection editor-only", () => {
    const shotTab = Array.from(container.querySelectorAll<HTMLButtonElement>("[role=tab]"))
      .find((button) => button.textContent?.includes("镜头时间轴"));
    act(() => shotTab?.click());

    const clips = Array.from(container.querySelectorAll<HTMLButtonElement>(".shot-clip"));
    expect(clips.length).toBeGreaterThan(2);
    const first = clips[0];
    const second = clips[1];
    const last = clips.at(-1)!;
    const revision = useProjectStore.getState().revision;
    const historyLength = useProjectStore.getState().history.length;

    act(() => {
      first.focus();
      first.dispatchEvent(new KeyboardEvent("keydown", {
        bubbles: true,
        cancelable: true,
        key: "ArrowRight",
      }));
    });
    expect(document.activeElement).toBe(second);
    expect(second.getAttribute("aria-pressed")).toBe("true");
    expect(useProjectStore.getState().selectedEventId).toBe(second.dataset.eventId);
    expect(useProjectStore.getState().previewPlayheadFrame).not.toBeNull();

    act(() => second.dispatchEvent(new KeyboardEvent("keydown", {
      bubbles: true,
      cancelable: true,
      key: "End",
    })));
    expect(document.activeElement).toBe(last);
    expect(last.getAttribute("aria-pressed")).toBe("true");

    act(() => last.dispatchEvent(new KeyboardEvent("keydown", {
      bubbles: true,
      cancelable: true,
      key: "Home",
    })));
    expect(document.activeElement).toBe(first);
    expect(first.getAttribute("aria-pressed")).toBe("true");
    expect(useProjectStore.getState().revision).toBe(revision);
    expect(useProjectStore.getState().history).toHaveLength(historyLength);
  });

  it("announces a keyboard-selected clip's track and frame range", () => {
    const shotTab = Array.from(container.querySelectorAll<HTMLButtonElement>("[role=tab]"))
      .find((button) => button.textContent?.includes("镜头时间轴"));
    act(() => shotTab?.click());

    const second = container.querySelectorAll<HTMLButtonElement>(".shot-clip")[1];
    expect(second).toBeDefined();
    act(() => {
      second.focus();
      second.dispatchEvent(new KeyboardEvent("keydown", {
        bubbles: true,
        cancelable: true,
        key: "ArrowLeft",
      }));
    });

    expect(second.getAttribute("aria-label")).toContain("Character");
    expect(second.getAttribute("aria-label")).toMatch(/第 \d+ 至 \d+ 帧/);
    const context = container.querySelector<HTMLElement>("[data-shot-selection-context]");
    expect(context?.getAttribute("aria-live")).toBe("polite");
    expect(context?.getAttribute("aria-atomic")).toBe("true");
    expect(context?.textContent).toContain("已选");
  });

  it("keeps an unmapped advanced selection explicit without fabricating timing", () => {
    const project = structuredClone(useProjectStore.getState().project);
    const scene = project.chapters[0].scenes[0];
    scene.cues[0].events.push({
      event_id: "event/advanced/unmapped-shot",
      kind: "halocue.ba:reaction-beat",
      intensity: 0.35,
    });
    act(() => {
      useProjectStore.getState().replaceProject(project);
      useProjectStore.getState().selectEvent("event/advanced/unmapped-shot");
    });

    const shotTab = Array.from(container.querySelectorAll<HTMLButtonElement>("[role=tab]"))
      .find((button) => button.textContent?.includes("镜头时间轴"));
    act(() => shotTab?.click());

    const context = container.querySelector<HTMLElement>("[data-shot-selection-context]");
    expect(context?.textContent).toContain("未映射");
    expect(context?.textContent).toContain("event/advanced/unmapped-shot");
    expect(container.querySelector("[data-event-timing-projection]")).toBeNull();
    expect(useProjectStore.getState().selectedEventId).toBe("event/advanced/unmapped-shot");

    const renderableClip = container.querySelector<HTMLButtonElement>(
      '.shot-clip[data-event-id="event/dialogue/001"]',
    );
    expect(renderableClip).not.toBeNull();
    act(() => renderableClip?.click());
    expect(container.querySelector("[data-shot-selection-context]")?.textContent)
      .toContain("已选");
    expect(container.querySelector("[data-shot-selection-context]")?.textContent)
      .not.toContain("未映射");
    expect(container.querySelector("[data-event-timing-projection]")).not.toBeNull();
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
