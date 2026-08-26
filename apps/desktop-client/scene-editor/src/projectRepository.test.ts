import { describe, expect, it } from "vitest";

import { demoProject } from "./demoProject";
import {
  DRAFT_KEY,
  LocalStorageProjectRepository,
  MemoryProjectRepository,
} from "./projectRepository";
import { createProjectStore } from "./projectStore";

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

  it("does not publish an editor mutation when the repository rejects the save", () => {
    const repository = new MemoryProjectRepository(demoProject);
    const store = createProjectStore(repository);
    const before = store.getState().project;
    repository.rejectNextSave();

    expect(() => store.getState().updateProjectTitle("不可写入")).toThrow("项目草稿保存失败");
    expect(store.getState().project).toEqual(before);
    expect(repository.loadDraft()).toEqual(before);
  });

  it("validates replacement before changing the editor state", () => {
    const repository = new MemoryProjectRepository(demoProject);
    const store = createProjectStore(repository);
    const before = store.getState().project;

    expect(() => store.getState().replaceProject({} as never)).toThrow("halocue-project/1.1");
    expect(store.getState().project).toEqual(before);
  });
});
