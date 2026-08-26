import { demoProject } from "./demoProject";
import type { EditorMode, HaloCueProject } from "./types";

export const DRAFT_KEY = "halocue.scene-editor.draft.v1";
const MODE_KEY = "halocue.scene-editor.mode";
const PENDING_DRAFT_KEY = `${DRAFT_KEY}.pending`;

export type StorageLike = Pick<Storage, "getItem" | "removeItem" | "setItem">;

export interface ProjectRepository {
  loadDraft(): HaloCueProject;
  saveDraft(project: HaloCueProject): void;
  parseProject(value: unknown): HaloCueProject;
  serializeProject(project: HaloCueProject): string;
}

export interface ProjectFileAdapter {
  read(file: Blob): Promise<HaloCueProject>;
  download(project: HaloCueProject, filename: string): void;
}

export function isProject(value: unknown): value is HaloCueProject {
  if (!value || typeof value !== "object") return false;
  const project = value as Partial<HaloCueProject>;
  return project.schema_version === "halocue-project/1.1"
    && typeof project.project_id === "string"
    && Array.isArray(project.characters)
    && Array.isArray(project.resources)
    && Array.isArray(project.chapters);
}

function clone<T>(value: T): T {
  return structuredClone(value);
}

function validatedProject(value: unknown): HaloCueProject {
  if (!isProject(value)) {
    throw new Error("当前编辑器需要 halocue-project/1.1；1.0 项目请先通过迁移服务打开");
  }
  return clone(value);
}

function parseStored(value: string | null): HaloCueProject | null {
  if (!value) return null;
  try {
    const parsed = JSON.parse(value);
    return isProject(parsed) ? clone(parsed) : null;
  } catch {
    return null;
  }
}

function browserStorage(): StorageLike | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

export function loadEditorMode(): EditorMode {
  try {
    return browserStorage()?.getItem(MODE_KEY) === "professional"
      ? "professional"
      : "simple";
  } catch {
    return "simple";
  }
}

export function saveEditorMode(mode: EditorMode): void {
  try {
    browserStorage()?.setItem(MODE_KEY, mode);
  } catch {
    // A private browsing profile may reject preference writes; mode is still usable in memory.
  }
}

export class LocalStorageProjectRepository implements ProjectRepository {
  constructor(private readonly storage: StorageLike | null = browserStorage()) {}

  loadDraft(): HaloCueProject {
    try {
      const pending = parseStored(this.storage?.getItem(PENDING_DRAFT_KEY) || null);
      if (pending) return pending;
      const current = parseStored(this.storage?.getItem(DRAFT_KEY) || null);
      return current || clone(demoProject);
    } catch {
      return clone(demoProject);
    }
  }

  saveDraft(project: HaloCueProject): void {
    const serialized = this.serializeProject(project);
    if (!this.storage) return;
    this.storage.setItem(PENDING_DRAFT_KEY, serialized);
    let committed = false;
    try {
      this.storage.setItem(DRAFT_KEY, serialized);
      committed = true;
    } finally {
      if (committed) this.storage.removeItem(PENDING_DRAFT_KEY);
    }
  }

  parseProject(value: unknown): HaloCueProject {
    return validatedProject(value);
  }

  serializeProject(project: HaloCueProject): string {
    return JSON.stringify(validatedProject(project), null, 2);
  }
}

export class MemoryProjectRepository implements ProjectRepository {
  private draft: HaloCueProject;
  private failNextSave = false;

  constructor(seed: HaloCueProject = demoProject) {
    this.draft = validatedProject(seed);
  }

  loadDraft(): HaloCueProject {
    return clone(this.draft);
  }

  saveDraft(project: HaloCueProject): void {
    if (this.failNextSave) {
      this.failNextSave = false;
      throw new Error("项目草稿保存失败");
    }
    this.draft = validatedProject(project);
  }

  parseProject(value: unknown): HaloCueProject {
    return validatedProject(value);
  }

  serializeProject(project: HaloCueProject): string {
    return JSON.stringify(validatedProject(project), null, 2);
  }

  rejectNextSave(): void {
    this.failNextSave = true;
  }
}

export class BrowserProjectFileAdapter implements ProjectFileAdapter {
  constructor(private readonly repository: ProjectRepository) {}

  async read(file: Blob): Promise<HaloCueProject> {
    return this.repository.parseProject(JSON.parse(await file.text()));
  }

  download(project: HaloCueProject, filename: string): void {
    const payload = new Blob([this.repository.serializeProject(project)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(payload);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
  }
}

export const projectRepository = new LocalStorageProjectRepository();
export const projectFileAdapter = new BrowserProjectFileAdapter(projectRepository);
