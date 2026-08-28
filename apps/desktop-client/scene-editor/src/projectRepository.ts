import { demoProject } from "./demoProject";
import {
  inspectProject,
  parseProject as decodeProject,
  serializeProject as encodeProject,
  type ProjectDiagnostic,
} from "./projectCodec";
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
  getDiagnostics(): readonly ProjectDiagnostic[];
}

export interface ProjectFileAdapter {
  read(file: Blob): Promise<HaloCueProject>;
  download(project: HaloCueProject, filename: string): void;
}

export function isProject(value: unknown): value is HaloCueProject {
  return inspectProject(value).project !== null;
}

function clone<T>(value: T): T {
  return structuredClone(value);
}

function parseStored(value: string | null): { project: HaloCueProject | null; diagnostics: ProjectDiagnostic[] } | null {
  if (!value) return null;
  try {
    const parsed = JSON.parse(value);
    const result = inspectProject(parsed);
    return { project: result.project, diagnostics: result.diagnostics };
  } catch {
    return {
      project: null,
      diagnostics: [{
        code: "project.invalid_stored_json",
        severity: "warning",
        path: "$",
        message: "存储中的项目快照不是有效 JSON，已跳过。",
      }],
    };
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
  private lastDiagnostics: ProjectDiagnostic[] = [];

  constructor(private readonly storage: StorageLike | null = browserStorage()) {}

  loadDraft(): HaloCueProject {
    try {
      const pending = parseStored(this.storage?.getItem(PENDING_DRAFT_KEY) || null);
      if (pending?.project) {
        this.lastDiagnostics = pending.diagnostics;
        return pending.project;
      }
      const current = parseStored(this.storage?.getItem(DRAFT_KEY) || null);
      if (current?.project) {
        this.lastDiagnostics = [
          ...(pending?.diagnostics || []),
          ...current.diagnostics,
        ];
        return current.project;
      }
      this.lastDiagnostics = [
        ...(pending?.diagnostics || []),
        ...(current?.diagnostics || []),
      ];
      return clone(demoProject);
    } catch {
      this.lastDiagnostics = [];
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
    const result = inspectProject(value);
    this.lastDiagnostics = result.diagnostics;
    return decodeProject(value);
  }

  serializeProject(project: HaloCueProject): string {
    const result = inspectProject(project);
    this.lastDiagnostics = result.diagnostics;
    return encodeProject(project);
  }

  getDiagnostics(): readonly ProjectDiagnostic[] {
    return clone(this.lastDiagnostics);
  }
}

export class MemoryProjectRepository implements ProjectRepository {
  private draft: HaloCueProject;
  private failNextSave = false;
  private lastDiagnostics: ProjectDiagnostic[] = [];

  constructor(seed: HaloCueProject = demoProject) {
    const result = inspectProject(seed);
    this.lastDiagnostics = result.diagnostics;
    this.draft = decodeProject(seed);
  }

  loadDraft(): HaloCueProject {
    return clone(this.draft);
  }

  saveDraft(project: HaloCueProject): void {
    if (this.failNextSave) {
      this.failNextSave = false;
      throw new Error("项目草稿保存失败");
    }
    const result = inspectProject(project);
    this.lastDiagnostics = result.diagnostics;
    this.draft = decodeProject(project);
  }

  parseProject(value: unknown): HaloCueProject {
    const result = inspectProject(value);
    this.lastDiagnostics = result.diagnostics;
    return decodeProject(value);
  }

  serializeProject(project: HaloCueProject): string {
    const result = inspectProject(project);
    this.lastDiagnostics = result.diagnostics;
    return encodeProject(project);
  }

  getDiagnostics(): readonly ProjectDiagnostic[] {
    return clone(this.lastDiagnostics);
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
