import { afterEach, describe, expect, it, vi } from "vitest";

import { demoProject } from "./demoProject";
import {
  compilePreview,
  PreviewCompilationCoordinator,
  type PreviewCompilationRequest,
} from "./previewCompilation";

function request(
  project = demoProject,
  patch: Partial<PreviewCompilationRequest> = {},
): PreviewCompilationRequest {
  return {
    project,
    mode: "simple",
    selectedSceneId: "scene/conference-room",
    selectedCueId: "cue/conference/001",
    selectedEventId: "event/dialogue/001",
    playheadFrame: null,
    ...patch,
  };
}

afterEach(() => vi.useRealTimers());

describe("preview compilation coordinator", () => {
  it("compiles only the latest project snapshot in a coalescing window", () => {
    vi.useFakeTimers();
    const published: ReturnType<typeof compilePreview>[] = [];
    const initial = compilePreview(request());
    const coordinator = new PreviewCompilationCoordinator(initial, (value) => {
      published.push(value);
    });
    const first = structuredClone(demoProject);
    const latest = structuredClone(demoProject);
    first.title = "中间值";
    latest.title = "最终值";

    coordinator.request(request(first));
    coordinator.request(request(latest));
    vi.advanceTimersByTime(71);
    expect(published).toEqual([]);

    vi.advanceTimersByTime(1);
    expect(published).toHaveLength(1);
    expect(published[0].request.project.title).toBe("最终值");
    expect(published[0].generation).toBe(2);
  });

  it("flushes the latest pending snapshot at a durable commit boundary", () => {
    vi.useFakeTimers();
    const published: ReturnType<typeof compilePreview>[] = [];
    const initial = compilePreview(request());
    const coordinator = new PreviewCompilationCoordinator(initial, (value) => {
      published.push(value);
    });
    const project = structuredClone(demoProject);
    project.title = "拖动终值";
    const latest = request(project);

    coordinator.request(latest);
    coordinator.request(latest, "immediate");

    expect(published).toHaveLength(1);
    expect(published[0].request).toBe(latest);
    vi.runAllTimers();
    expect(published).toHaveLength(1);
  });

  it("reuses scene evaluation for an intent-only selection change", () => {
    const initial = compilePreview(request());
    const selected = compilePreview(request(demoProject, {
      mode: "professional",
      selectedEventId: "event/enter/yuuka",
    }), 1, initial);

    expect(selected.evaluation).toBe(initial.evaluation);
    expect(selected.intent.target.resolution).toBe("selected-event");
    expect(selected.intent.selected_event_id).toBe("event/enter/yuuka");
  });

  it("reuses scene evaluation while scrubbing to an exact frame", () => {
    const initial = compilePreview(request());
    const scrubbed = compilePreview(request(demoProject, {
      mode: "professional",
      playheadFrame: 7,
    }), 1, initial);

    expect(scrubbed.evaluation).toBe(initial.evaluation);
    expect(scrubbed.intent).toEqual(expect.objectContaining({
      schema_version: "preview-intent/1.1",
      selection_kind: "playhead",
      selected_event_id: null,
      target: expect.objectContaining({
        frame: 7,
        alignment: "exact",
        resolution: "explicit-frame",
      }),
    }));
  });

  it("cancels pending work when disposed", () => {
    vi.useFakeTimers();
    const publish = vi.fn();
    const initial = compilePreview(request());
    const coordinator = new PreviewCompilationCoordinator(initial, publish);
    const project = structuredClone(demoProject);
    project.title = "不应发布";

    coordinator.request(request(project));
    coordinator.dispose();
    vi.runAllTimers();

    expect(publish).not.toHaveBeenCalled();
  });
});
