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

class RejectingValidationRepository extends MemoryProjectRepository {
  private rejectValidation = false;

  override serializeProject(project: HaloCueProject): string {
    if (this.rejectValidation) {
      this.rejectValidation = false;
      throw new Error("项目草稿校验失败");
    }
    return super.serializeProject(project);
  }

  rejectNextValidation(): void {
    this.rejectValidation = true;
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
    previewPlayheadFrame: state.previewPlayheadFrame,
    history: state.history,
    future: state.future,
    dirty: state.dirty,
    revision: state.revision,
    previewRevision: state.previewRevision,
    activeTransaction: state.activeTransaction,
    autosave: state.autosave,
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

  it("does not publish any editor transaction state when candidate validation fails", () => {
    const repository = new RejectingValidationRepository(demoProject);
    const store = createProjectStore(repository);
    store.getState().updateProjectTitle("可撤销标题");
    store.getState().undo();
    const before = transactionSnapshot(store);
    repository.rejectNextValidation();

    expect(() => store.getState().updateProjectTitle("不可提交")).toThrow("项目草稿校验失败");
    expect(transactionSnapshot(store)).toEqual(before);
  });

  it("keeps undo and redo atomic when candidate validation fails", () => {
    const repository = new RejectingValidationRepository(demoProject);
    const store = createProjectStore(repository);
    store.getState().updateProjectTitle("已编辑");

    let before = transactionSnapshot(store);
    repository.rejectNextValidation();
    expect(() => store.getState().undo()).toThrow("项目草稿校验失败");
    expect(transactionSnapshot(store)).toEqual(before);

    store.getState().undo();
    before = transactionSnapshot(store);
    repository.rejectNextValidation();
    expect(() => store.getState().redo()).toThrow("项目草稿校验失败");
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

  it("coalesces multiple durable editor revisions into the latest autosave", () => {
    const repository = new CountingProjectRepository(demoProject);
    const store = createProjectStore(repository);

    store.getState().updateProjectTitle("中间标题");
    store.getState().updateProjectTitle("最终标题");
    expect(repository.saves).toBe(0);
    expect(store.getState().autosave).toEqual({
      status: "pending",
      savedRevision: 0,
      pendingRevision: 2,
      error: null,
    });

    store.getState().flushAutosave();
    expect(repository.saves).toBe(1);
    expect(repository.loadDraft().title).toBe("最终标题");
    expect(store.getState().autosave).toEqual({
      status: "saved",
      savedRevision: 2,
      pendingRevision: null,
      error: null,
    });
  });

  it("commits a dialogue composition session as one revision", () => {
    const repository = new CountingProjectRepository(demoProject);
    const store = createProjectStore(repository);
    const key = "dialogue.text:test";
    const base = structuredClone(store.getState().project);
    const autosaveBefore = store.getState().autosave;

    store.getState().beginTransaction(key);
    store.getState().previewDialogue(key, { text: "中" });
    store.getState().previewDialogue(key, { text: "中文" });
    store.getState().previewDialogue(key, { text: "中文输入完成" });

    let state = store.getState();
    expect(state.project.chapters[0].scenes[0].cues[0].events.at(-1)?.text)
      .toBe("中文输入完成");
    expect(state.revision).toBe(0);
    expect(state.history).toEqual([]);
    expect(state.autosave).toEqual(autosaveBefore);
    expect(repository.saves).toBe(0);

    expect(state.commitTransaction(key)).toEqual({ status: "committed", revision: 1 });
    state = store.getState();
    expect(state.history).toHaveLength(1);
    expect(state.autosave.pendingRevision).toBe(1);
    expect(repository.saves).toBe(0);
    state.flushAutosave();
    expect(repository.saves).toBe(1);

    state.undo();
    expect(store.getState().project).toEqual(base);
  });

  it("previews many gesture values but commits one save and one undo entry", () => {
    const repository = new CountingProjectRepository(demoProject);
    const store = createProjectStore(repository);
    const key = "environment.zoom:test";
    const base = structuredClone(store.getState().project);

    store.getState().beginTransaction(key);
    store.getState().previewEnvironment(key, { zoom: 1.1 });
    store.getState().previewEnvironment(key, { zoom: 1.2 });

    let state = store.getState();
    expect(state.project.chapters[0].scenes[0].cues[0].events[0].zoom).toBe(1.2);
    expect(state.previewRevision).toBe(2);
    expect(state.revision).toBe(0);
    expect(state.history).toEqual([]);
    expect(state.dirty).toBe(false);
    expect(repository.saves).toBe(0);

    expect(state.commitTransaction(key)).toEqual({ status: "committed", revision: 1 });
    state = store.getState();
    expect(state.activeTransaction).toBeNull();
    expect(state.history).toHaveLength(1);
    expect(state.dirty).toBe(true);
    expect(state.autosave.status).toBe("pending");
    state.flushAutosave();
    expect(repository.saves).toBe(1);

    state.undo();
    expect(store.getState().project).toEqual(base);
  });

  it("keeps a complete gesture commit retryable when background persistence fails", () => {
    const repository = new CountingProjectRepository(demoProject);
    const store = createProjectStore(repository);
    const key = "environment.zoom:failure";
    const base = transactionSnapshot(store);

    store.getState().beginTransaction(key);
    store.getState().previewEnvironment(key, { zoom: 1.25 });
    repository.rejectNextSave();

    expect(store.getState().commitTransaction(key)).toEqual({ status: "committed", revision: 1 });
    store.getState().flushAutosave();
    let committed = transactionSnapshot(store);
    expect(committed.project).not.toEqual(base.project);
    expect(committed.history).toHaveLength(1);
    expect(committed.dirty).toBe(true);
    expect(committed.revision).toBe(1);
    expect(committed.activeTransaction).toBeNull();
    expect(committed.autosave).toEqual({
      status: "failed",
      savedRevision: 0,
      pendingRevision: 1,
      error: "项目草稿保存失败",
    });
    expect(repository.saves).toBe(0);

    store.getState().retryAutosave();
    store.getState().flushAutosave();
    committed = transactionSnapshot(store);
    expect(committed.autosave.status).toBe("saved");
    expect(committed.autosave.savedRevision).toBe(1);
    expect(repository.saves).toBe(1);
  });

  it("rolls a gesture back when its final candidate cannot be validated", () => {
    const repository = new RejectingValidationRepository(demoProject);
    const store = createProjectStore(repository);
    const key = "environment.zoom:invalid";
    const base = transactionSnapshot(store);

    store.getState().beginTransaction(key);
    store.getState().previewEnvironment(key, { zoom: 1.25 });
    repository.rejectNextValidation();

    expect(() => store.getState().commitTransaction(key)).toThrow("项目草稿校验失败");
    const restored = transactionSnapshot(store);
    expect(restored.project).toEqual(base.project);
    expect(restored.history).toEqual(base.history);
    expect(restored.future).toEqual(base.future);
    expect(restored.dirty).toBe(base.dirty);
    expect(restored.revision).toBe(base.revision);
    expect(restored.activeTransaction).toBeNull();
    expect(restored.autosave).toEqual(base.autosave);
  });

  it("cancels a gesture without making its preview durable", () => {
    const repository = new CountingProjectRepository(demoProject);
    const store = createProjectStore(repository);
    const key = "environment.zoom:cancel";
    const base = structuredClone(store.getState().project);

    store.getState().beginTransaction(key);
    store.getState().previewEnvironment(key, { zoom: 1.3 });
    store.getState().cancelTransaction(key);

    const state = store.getState();
    expect(state.project).toEqual(base);
    expect(state.activeTransaction).toBeNull();
    expect(state.history).toEqual([]);
    expect(state.revision).toBe(0);
    expect(repository.saves).toBe(0);
  });

  it("commits a gesture that returns to its baseline as a no-op", () => {
    const repository = new CountingProjectRepository(demoProject);
    const store = createProjectStore(repository);
    const key = "environment.zoom:baseline";
    const background = store.getState().project.chapters[0].scenes[0].cues[0].events[0];

    store.getState().beginTransaction(key);
    store.getState().previewEnvironment(key, { zoom: 1.4 });
    store.getState().previewEnvironment(key, { zoom: background.zoom });
    const result = store.getState().commitTransaction(key);

    expect(result).toEqual({ status: "no-op", revision: 0 });
    expect(store.getState().history).toEqual([]);
    expect(store.getState().activeTransaction).toBeNull();
    expect(repository.saves).toBe(0);
  });

  it("validates replacement before changing the editor state", () => {
    const repository = new MemoryProjectRepository(demoProject);
    const store = createProjectStore(repository);
    const before = store.getState().project;

    expect(() => store.getState().replaceProject({} as never)).toThrow("halocue-project/1.1");
    expect(store.getState().project).toEqual(before);
  });
});
