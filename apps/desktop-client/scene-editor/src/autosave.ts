import type { EditorAutosaveState } from "./types";

type PendingAutosave<T> = {
  revision: number;
  snapshot: T;
};

export class AutosaveCoordinator<T> {
  private generation = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private latest: PendingAutosave<T> | null = null;
  private state: EditorAutosaveState;

  constructor(
    private readonly save: (snapshot: T) => void,
    private readonly publish: (state: EditorAutosaveState) => void,
    private readonly delayMs = 450,
    initialRevision = 0,
  ) {
    this.state = {
      status: "saved",
      savedRevision: initialRevision,
      pendingRevision: null,
      error: null,
    };
  }

  currentState(): EditorAutosaveState {
    return { ...this.state };
  }

  request(snapshot: T, revision: number): EditorAutosaveState {
    if (!Number.isInteger(revision) || revision < 0) {
      throw new Error("自动保存 revision 必须是非负整数");
    }
    this.cancelTimer();
    this.latest = { snapshot, revision };
    this.generation += 1;
    this.state = {
      status: "pending",
      savedRevision: this.state.savedRevision,
      pendingRevision: revision,
      error: null,
    };
    const generation = this.generation;
    this.timer = setTimeout(() => this.persist(generation), this.delayMs);
    return this.currentState();
  }

  flush(): void {
    if (!this.latest) return;
    this.cancelTimer();
    this.persist(this.generation);
  }

  retry(): void {
    if (this.state.status !== "failed" || !this.latest) return;
    this.generation += 1;
    this.state = {
      ...this.state,
      status: "pending",
      error: null,
    };
    this.publish(this.currentState());
    const generation = this.generation;
    this.timer = setTimeout(() => this.persist(generation), this.delayMs);
  }

  dispose(): void {
    this.cancelTimer();
    this.latest = null;
    this.generation += 1;
  }

  private cancelTimer(): void {
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
  }

  private persist(generation: number): void {
    if (generation !== this.generation || !this.latest) return;
    const pending = this.latest;
    this.timer = null;
    try {
      this.save(pending.snapshot);
    } catch (error) {
      if (generation !== this.generation) return;
      this.state = {
        status: "failed",
        savedRevision: this.state.savedRevision,
        pendingRevision: pending.revision,
        error: error instanceof Error ? error.message : "自动保存失败",
      };
      this.publish(this.currentState());
      return;
    }
    if (generation !== this.generation) return;
    this.latest = null;
    this.state = {
      status: "saved",
      savedRevision: pending.revision,
      pendingRevision: null,
      error: null,
    };
    this.publish(this.currentState());
  }
}
