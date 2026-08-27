import { describe, expect, it } from "vitest";

import { demoProject } from "./demoProject";
import {
  DRAFT_KEY,
  LocalStorageProjectRepository,
  MemoryProjectRepository,
} from "./projectRepository";
import { migratedCueId } from "./projectCodec";
import { createProjectStore } from "./projectStore";
import type { HaloCueProject } from "./types";

class CountingProjectRepository extends MemoryProjectRepository {
  saves = 0;

  override saveDraft(project: HaloCueProject): void {
    super.saveDraft(project);
    this.saves += 1;
  }
}

function transactionSnapshot(store: ReturnType<typeof createProjectStore>) {
  const state = store.getState();
  return {
    project: state.project,
    selectedChapterId: state.selectedChapterId,
    selectedSceneId: state.selectedSceneId,
    selectedCueId: state.selectedCueId,
    selectedEventId: state.selectedEventId,
    history: state.history,
    future: state.future,
    dirty: state.dirty,
    revision: state.revision,
    projectDiagnostics: state.projectDiagnostics,
  };
}

function storage(initial: Record<string, string> = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => values.delete(key),
    values,
  };
}

describe("project repository seam", () => {
  it("opens a 1.0 flat-event project through the deterministic codec", () => {
    const legacy = structuredClone(demoProject) as Record<string, any>;
    legacy.schema_version = "halocue-project/1.0";
    const scene = legacy.chapters[0].scenes[0];
    scene.events = scene.cues.flatMap((cue: any) => cue.events);
    delete scene.cues;
    const repository = new MemoryProjectRepository(demoProject);

    const restored = repository.parseProject(legacy);
    expect(restored.schema_version).toBe("halocue-project/1.1");
    expect(restored.chapters[0].scenes[0].cues.map((cue) => cue.cue_id)).toEqual(
      scene.events.map((event: any) => migratedCueId(event.event_id)),
    );
  });

  it("exposes warning diagnostics for preserved namespaced extensions", () => {
    const project = structuredClone(demoProject);
    project.chapters[0].scenes[0].cues[0].events.push({
      event_id: "event/future",
      kind: "vendor:future",
      curve: "ease-out",
    });
    const repository = new MemoryProjectRepository(project);

    expect(repository.getDiagnostics()).toEqual(expect.arrayContaining([
      expect.objectContaining({ code: "project.unknown_event_kind", severity: "warning" }),
    ]));
    expect(repository.loadDraft().chapters[0].scenes[0].cues[0].events.at(-1)?.kind)
      .toBe("vendor:future");
  });

  it("keeps corrupt local snapshots observable while recovering the demo", () => {
    const values = new Map<string, string>([[DRAFT_KEY, "not-json"]]);
    const repository = new LocalStorageProjectRepository({
      getItem: (key) => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, value),
      removeItem: (key) => values.delete(key),
    });

    expect(repository.loadDraft()).toEqual(demoProject);
    expect(repository.getDiagnostics()).toEqual(expect.arrayContaining([
      expect.objectContaining({ code: "project.invalid_stored_json", severity: "warning" }),
    ]));
  });

  it("round-trips a draft without exposing the stored object", () => {
    const repository = new MemoryProjectRepository(demoProject);
    const loaded = repository.loadDraft();
    loaded.title = "changed outside repository";

    expect(repository.loadDraft().title).toBe(demoProject.title);
    expect(repository.parseProject(JSON.parse(repository.serializeProject(demoProject))))
      .toEqual(demoProject);
  });

  it("recovers a pending local snapshot when the current snapshot is absent", () => {
    const pending = JSON.stringify(demoProject);
    const pendingStorage = storage({ [`${DRAFT_KEY}.pending`]: pending });
    const repository = new LocalStorageProjectRepository(pendingStorage);

    expect(repository.loadDraft()).toEqual(demoProject);
  });

  it("leaves the last local snapshot intact and recovers pending data", () => {
    const previous = JSON.stringify(demoProject);
    const values = new Map<string, string>([[DRAFT_KEY, previous]]);
    const failingStorage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => {
        if (key === DRAFT_KEY) throw new Error("quota");
        values.set(key, value);
      },
      removeItem: (key: string) => values.delete(key),
    };
    const repository = new LocalStorageProjectRepository(failingStorage);

    expect(() => repository.saveDraft({ ...demoProject, title: "new" })).toThrow("quota");
    expect(JSON.parse(values.get(DRAFT_KEY) || "null").title).toBe(demoProject.title);
    expect(repository.loadDraft().title).toBe("new");
    expect(values.has(`${DRAFT_KEY}.pending`)).toBe(true);
  });

  it("does not publish any editor transaction state when a commit save fails", () => {
    const repository = new MemoryProjectRepository(demoProject);
    const store = createProjectStore(repository);
    store.getState().updateProjectTitle("可撤销标题");
    store.getState().undo();
    const before = transactionSnapshot(store);
    repository.rejectNextSave();

    expect(() => store.getState().updateProjectTitle("不可写入")).toThrow("项目草稿保存失败");
    expect(transactionSnapshot(store)).toEqual(before);
    expect(repository.loadDraft()).toEqual(before.project);
  });

  it("keeps undo and redo atomic when their save fails", () => {
    const repository = new MemoryProjectRepository(demoProject);
    const store = createProjectStore(repository);
    store.getState().updateProjectTitle("已编辑");

    let before = transactionSnapshot(store);
    repository.rejectNextSave();
    expect(() => store.getState().undo()).toThrow("项目草稿保存失败");
    expect(transactionSnapshot(store)).toEqual(before);

    store.getState().undo();
    before = transactionSnapshot(store);
    repository.rejectNextSave();
    expect(() => store.getState().redo()).toThrow("项目草稿保存失败");
    expect(transactionSnapshot(store)).toEqual(before);
  });

  it("does not save or disturb history when a transaction changes nothing", () => {
    const repository = new CountingProjectRepository(demoProject);
    const store = createProjectStore(repository);
    store.getState().updateProjectTitle("临时标题");
    store.getState().undo();
    const before = transactionSnapshot(store);
    const savesBefore = repository.saves;

    const result = store.getState().updateProjectTitle(before.project.title || "");

    expect(result).toEqual({ status: "no-op", revision: before.revision });
    expect(repository.saves).toBe(savesBefore);
    expect(transactionSnapshot(store)).toEqual(before);
  });

  it("validates replacement before changing the editor state", () => {
    const repository = new MemoryProjectRepository(demoProject);
    const store = createProjectStore(repository);
    const before = store.getState().project;

    expect(() => store.getState().replaceProject({} as never)).toThrow("halocue-project/1.1");
    expect(store.getState().project).toEqual(before);
  });
});
