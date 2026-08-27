import {
  ArrowDown,
  ArrowLeftToLine,
  ArrowRightToLine,
  ArrowUp,
  AlertTriangle,
  Box,
  Check,
  ChevronDown,
  ChevronRight,
  CircleGauge,
  Clapperboard,
  Copy,
  Download,
  GripVertical,
  Image,
  Layers3,
  LocateFixed,
  Menu,
  MessageSquareText,
  MoreHorizontal,
  Move,
  Play,
  Plus,
  Redo2,
  RotateCcw,
  Save,
  ScanLine,
  Sparkles,
  Trash2,
  Undo2,
  Upload,
  UserRound,
  UsersRound,
  WandSparkles,
  X,
  Zap,
  type LucideIcon,
} from "lucide-react";
import {
  type ChangeEvent,
  type DragEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { projectFileAdapter } from "./projectRepository";
import {
  capabilityStateOptionsFor,
  capabilityStatesFor,
  type CapabilityStateOption,
} from "./capabilities";
import { evaluateScene } from "./sceneEvaluation";
import {
  compilePreview,
  PreviewCompilationCoordinator,
  type PreviewCompilationRequest,
} from "./previewCompilation";
import { eventDurationMs } from "./renderTimeline";
import { parseNumericDraft } from "./fieldTransactions";
import { editorKeyboardCommand, isTextEditingTarget } from "./editorCommands";
import {
  eventDropPlacement,
  type EventDropPlacement,
  type EventMove,
} from "./eventReorder";
import type { EventInsertPlacement } from "./eventInsertion";
import {
  characterMotionEventForCue,
  projectCueState,
  sceneById,
} from "./cueStateProjection";
import { TimelineEventSegment } from "./TimelineEventSegment";
import {
  buildShotTimeline,
  type ShotTimelineClip,
  type ShotTimelineProjection,
} from "./shotTimeline";
import {
  eventEditorDefinition,
  eventEditorDefinitions,
  eventLabel,
  eventSummary,
  type EventEditorField,
  type EventIconKey,
} from "./eventEditorCatalog";
import {
  advancedEventCount,
  useProjectStore,
} from "./projectStore";
import type {
  Cue,
  CueEvent,
  CapabilityStateKind,
  InspectorTab,
  RenderTimeline,
  SceneDescriptor,
  SceneEvaluation,
  ScenePerformancePlan,
  ScenePreviewIntent,
} from "./types";

type PreviewController = {
  applyIntent: (intent: ScenePreviewIntent) => unknown;
  generation: number;
  isCurrent: () => boolean;
  scene_id: string;
  timeline: RenderTimeline;
  performance: ScenePerformancePlan;
  seekFrame: (frame: number) => void;
  play: (options?: { fromFrame?: number; toFrame?: number }) => void;
  dispose: () => void;
};

type PreviewWindow = Window & {
  HaloCueScenePreview?: {
    mount: (
      descriptor: SceneDescriptor,
      root?: Element | null,
      options?: {
        timeline?: RenderTimeline;
        performance?: ScenePerformancePlan;
        intent?: ScenePreviewIntent;
      },
    ) => PreviewController;
    controller?: PreviewController;
  };
};

function IconButton({
  label,
  children,
  disabled,
  onClick,
  tone,
}: {
  label: string;
  children: ReactNode;
  disabled?: boolean;
  onClick?: () => void;
  tone?: "danger";
}) {
  return (
    <button
      className={`icon-button${tone ? ` is-${tone}` : ""}`}
      type="button"
      title={label}
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

function TopBar({ onOpen, onSave }: { onOpen: () => void; onSave: () => void }) {
  const project = useProjectStore((state) => state.project);
  const mode = useProjectStore((state) => state.mode);
  const dirty = useProjectStore((state) => state.dirty);
  const activeTransaction = useProjectStore((state) => state.activeTransaction);
  const autosave = useProjectStore((state) => state.autosave);
  const retryAutosave = useProjectStore((state) => state.retryAutosave);
  const history = useProjectStore((state) => state.history);
  const future = useProjectStore((state) => state.future);
  const setMode = useProjectStore((state) => state.setMode);
  const undo = useProjectStore((state) => state.undo);
  const redo = useProjectStore((state) => state.redo);
  const projectDiagnostics = useProjectStore((state) => state.projectDiagnostics);
  const hasProjectError = projectDiagnostics.some((item) => item.severity === "error");
  const hasProjectWarning = projectDiagnostics.some((item) => item.severity === "warning");

  return (
    <header className="topbar">
      <div className="brand-lockup" aria-label="HaloCue">
        <span className="brand-mark"><Clapperboard size={18} /></span>
        <span className="brand-name">HaloCue</span>
        <span className="version-tag">1.1</span>
      </div>
      <div className="project-heading">
        <strong>{project.title || "未命名项目"}</strong>
        <span
          className={dirty || activeTransaction || autosave.status !== "saved" ? "save-state is-dirty" : "save-state"}
          title={autosave.error || undefined}
        >
          {hasProjectError
            ? "项目有待修复项"
            : autosave.status === "failed"
              ? "自动保存失败"
            : hasProjectWarning
              ? "项目有校验警告"
              : activeTransaction
                ? "正在预览调整"
                : autosave.status === "pending"
                  ? "正在自动保存"
                  : dirty ? "草稿已自动保存" : "已保存"}
        </span>
        {autosave.status === "failed" && (
          <button className="save-retry" type="button" onClick={retryAutosave}>重试</button>
        )}
      </div>
      <div className="mode-switch" role="group" aria-label="编辑模式">
        <button
          type="button"
          className={mode === "simple" ? "is-active" : ""}
          onClick={() => setMode("simple")}
        >
          <Zap size={15} />快速编辑
        </button>
        <button
          type="button"
          className={mode === "professional" ? "is-active" : ""}
          onClick={() => setMode("professional")}
        >
          <Layers3 size={15} />专业工作台
        </button>
      </div>
      <div className="top-actions">
        <IconButton label="撤销" disabled={!history.length} onClick={undo}><Undo2 /></IconButton>
        <IconButton label="重做" disabled={!future.length} onClick={redo}><Redo2 /></IconButton>
        <span className="toolbar-divider" />
        <button className="quiet-button" type="button" onClick={onOpen}><Upload />打开</button>
        <button className="primary-button" type="button" onClick={onSave}><Save />保存</button>
      </div>
    </header>
  );
}

function ProjectRail({ showCues }: { showCues: boolean }) {
  const project = useProjectStore((state) => state.project);
  const selectedChapterId = useProjectStore((state) => state.selectedChapterId);
  const selectedSceneId = useProjectStore((state) => state.selectedSceneId);
  const selectedCueId = useProjectStore((state) => state.selectedCueId);
  const selectChapter = useProjectStore((state) => state.selectChapter);
  const selectScene = useProjectStore((state) => state.selectScene);
  const selectCue = useProjectStore((state) => state.selectCue);

  return (
    <aside className="project-rail">
      <div className="rail-heading">
        <span>{showCues ? "项目" : "场景"}</span>
        <IconButton label="项目菜单"><MoreHorizontal /></IconButton>
      </div>
      <nav className="project-tree" aria-label={showCues ? "完整项目结构" : "场景导航"}>
        <div className="tree-row root"><ChevronDown /><Box />{project.title}</div>
        {project.chapters.map((chapter) => (
          <div className="tree-branch" key={chapter.chapter_id}>
            <button
              type="button"
              className={`tree-row depth-1${chapter.chapter_id === selectedChapterId ? " is-open" : ""}`}
              onClick={() => selectChapter(chapter.chapter_id)}
            >
              <ChevronDown /><Layers3 />{chapter.title || "章节"}
            </button>
            {chapter.scenes.map((scene) => (
              <div className="tree-branch" key={scene.scene_id}>
                <button
                  type="button"
                  className={`tree-row depth-2${scene.scene_id === selectedSceneId ? " is-open is-selected" : ""}`}
                  onClick={() => selectScene(scene.scene_id)}
                >
                  <ChevronDown /><Clapperboard />{scene.title || "场景"}
                </button>
                {showCues && scene.scene_id === selectedSceneId && <div className="tree-cues">
                  {scene.cues.map((cue, index) => (
                    <button
                      type="button"
                      key={cue.cue_id}
                      className={cue.cue_id === selectedCueId ? "tree-cue is-active" : "tree-cue"}
                      onClick={() => selectCue(cue.cue_id)}
                    >
                      <span>{String(index + 1).padStart(2, "0")}</span>
                      <span>{cue.title || "未命名演出"}</span>
                    </button>
                  ))}
                </div>}
              </div>
            ))}
          </div>
        ))}
      </nav>
      <div className="rail-footer">
        <span><UsersRound />{project.characters.length} 名角色</span>
        <span><Image />{project.resources.length} 个资源</span>
      </div>
    </aside>
  );
}

function PreviewFrame() {
  const project = useProjectStore((state) => state.project);
  const mode = useProjectStore((state) => state.mode);
  const selectedSceneId = useProjectStore((state) => state.selectedSceneId);
  const selectedCueId = useProjectStore((state) => state.selectedCueId);
  const selectedEventId = useProjectStore((state) => state.selectedEventId);
  const playheadFrame = useProjectStore((state) => state.previewPlayheadFrame);
  const setPlayheadFrame = useProjectStore((state) => state.setPreviewPlayheadFrame);
  const activeTransaction = useProjectStore((state) => state.activeTransaction);
  const frame = useRef<HTMLIFrameElement>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const controllerRef = useRef<PreviewController | null>(null);
  const mountedEvaluationRef = useRef<SceneEvaluation | null>(null);
  const request = useMemo<PreviewCompilationRequest>(() => ({
    project,
    mode,
    selectedSceneId,
    selectedCueId,
    selectedEventId,
    playheadFrame,
  }), [mode, playheadFrame, project, selectedCueId, selectedEventId, selectedSceneId]);
  const [compilation, setCompilation] = useState(() => compilePreview(request));
  const coordinatorRef = useRef<PreviewCompilationCoordinator | null>(null);
  if (!coordinatorRef.current) {
    coordinatorRef.current = new PreviewCompilationCoordinator(compilation, setCompilation);
  }
  const addressRef = useRef({ mode, selectedSceneId, selectedCueId, selectedEventId, playheadFrame });
  const wasTransactionActiveRef = useRef(Boolean(activeTransaction));
  const evaluation = compilation.evaluation;
  const intent = compilation.intent;
  const selectedTimelineEvent = evaluation.timeline.events.find(
    (event) => event.event_id === selectedEventId,
  );
  const intentRef = useRef(intent);
  intentRef.current = intent;
  const motionTrialKey = activeTransaction?.key.endsWith(":motion")
    ? activeTransaction.key
    : null;
  const intentLabel = {
    "selected-event": "所选事件起点",
    "cue-terminal": "Cue 完成态",
    "prior-renderable": "扩展事件前一画面",
    "scene-start": "场景起始画面",
    "explicit-frame": `精确帧 ${intent.target.frame}`,
  }[intent.target.resolution];

  useEffect(() => {
    const previous = addressRef.current;
    const addressChanged = previous.mode !== mode
      || previous.selectedSceneId !== selectedSceneId
      || previous.selectedCueId !== selectedCueId
      || previous.selectedEventId !== selectedEventId
      || previous.playheadFrame !== playheadFrame;
    addressRef.current = { mode, selectedSceneId, selectedCueId, selectedEventId, playheadFrame };
    coordinatorRef.current?.request(request, addressChanged ? "immediate" : "coalesced");
  }, [mode, playheadFrame, request, selectedCueId, selectedEventId, selectedSceneId]);

  useEffect(() => {
    const active = Boolean(activeTransaction);
    if (wasTransactionActiveRef.current && !active) {
      coordinatorRef.current?.flush();
    }
    wasTransactionActiveRef.current = active;
  }, [activeTransaction]);

  const mount = () => {
    const previewWindow = frame.current?.contentWindow as PreviewWindow | null;
    const preview = previewWindow?.HaloCueScenePreview;
    if (!preview) return;
    try {
      const controller = preview.mount(evaluation.descriptor, undefined, {
        timeline: evaluation.timeline,
        performance: evaluation.performance,
        intent: intentRef.current,
      });
      preview.controller = controller;
      controllerRef.current = controller;
      mountedEvaluationRef.current = evaluation;
      setError("");
      setReady(true);
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "预览更新失败");
      setReady(false);
    }
  };

  useEffect(() => {
    setReady(false);
    mount();
  }, [evaluation]);

  useEffect(() => {
    const controller = controllerRef.current;
    if (
      !ready
      || !controller?.isCurrent()
      || mountedEvaluationRef.current !== evaluation
    ) return;
    try {
      controller.applyIntent(intent);
      setError("");
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "预览定位失败");
    }
  }, [evaluation, intent, ready]);

  useEffect(() => {
    const controller = controllerRef.current;
    if (!ready || !motionTrialKey || !controller?.isCurrent()) return;
    const motionOperation = [...evaluation.performance.operations].reverse().find((operation) => (
      operation.kind === "numeric-keyframes"
      && operation.operation_id.includes("/operation/motion-")
    ));
    if (!motionOperation) return;
    controller.play({
      fromFrame: motionOperation.start_frame,
      toFrame: motionOperation.end_frame - 1,
    });
  }, [evaluation, motionTrialKey, ready]);

  useEffect(() => () => {
    coordinatorRef.current?.dispose();
    mountedEvaluationRef.current = null;
    controllerRef.current?.dispose();
  }, []);

  return (
    <section className="preview-region" aria-label="实时预览">
      <div className="preview-toolbar">
        <div>
          <span className="live-dot" />
          <strong>实时预览</strong>
          <span className="preview-meta" aria-live="polite">
            1280 × 720 · Spine · {intentLabel}
          </span>
          {selectedTimelineEvent && (
            <span className="preview-selection-range" data-preview-selection-range>
              F{selectedTimelineEvent.start_frame}-{selectedTimelineEvent.end_frame}
            </span>
          )}
        </div>
        <div className="preview-toolbar-actions">
          <button type="button" onClick={mount}><RotateCcw />刷新</button>
          {selectedTimelineEvent && (
            <button
              type="button"
              data-preview-locate
              title="定位到所选事件起点"
              onClick={() => setPlayheadFrame(selectedTimelineEvent.start_frame)}
            ><LocateFixed />定位</button>
          )}
          <button type="button" disabled={!ready} onClick={() => controllerRef.current?.play({ fromFrame: 0 })}><Play />从头播放</button>
        </div>
      </div>
      <div className="preview-viewport">
        <iframe
          ref={frame}
          title="HaloCue 场景实时预览"
          src="/scene-preview/index.html?embedded=1&renderer=realtime"
          onLoad={mount}
        />
        {!ready && !error && <div className="preview-loading"><CircleGauge />正在同步演出</div>}
        {error && <div className="preview-error"><X />{error}</div>}
      </div>
    </section>
  );
}

function StageSlots() {
  const project = useProjectStore((state) => state.project);
  const selectedSceneId = useProjectStore((state) => state.selectedSceneId);
  const selectedCueId = useProjectStore((state) => state.selectedCueId);
  const selectedSlot = useProjectStore((state) => state.selectedSlot);
  const selectSlot = useProjectStore((state) => state.selectSlot);
  const swapSlots = useProjectStore((state) => state.swapSlots);
  const [dragged, setDragged] = useState<number | null>(null);
  const slots = projectCueState(project, selectedCueId, { sceneId: selectedSceneId }).afterCue.slots;
  const characters = new Map(project.characters.map((character) => [character.character_id, character]));
  const slotRefs = useRef<Record<number, HTMLButtonElement>>({});
  const focusSlot = (slot: number) => {
    selectSlot(slot);
    slotRefs.current[slot]?.focus();
  };
  const navigateSlot = (event: ReactKeyboardEvent<HTMLButtonElement>, index: number) => {
    const nextIndex = event.key === "ArrowRight" || event.key === "ArrowDown"
      ? Math.min(slots.length - 1, index + 1)
      : event.key === "ArrowLeft" || event.key === "ArrowUp"
        ? Math.max(0, index - 1)
        : event.key === "Home"
          ? 0
          : event.key === "End"
            ? slots.length - 1
            : -1;
    if (nextIndex < 0 || nextIndex === index) return;
    event.preventDefault();
    focusSlot(nextIndex + 1);
  };

  const drop = (event: DragEvent, slot: number) => {
    event.preventDefault();
    if (dragged) swapSlots(dragged, slot);
    setDragged(null);
  };

  return (
    <section className="slot-strip" aria-label="五个可见栏位">
      <div className="strip-label">
        <UsersRound />
        <span><strong>舞台栏位</strong><small>拖动可交换位置</small></span>
      </div>
      <div className="slot-list">
        {slots.map((characterId, index) => {
          const slot = index + 1;
          const character = characterId ? characters.get(characterId) : undefined;
          return (
            <button
              ref={(element) => {
                if (element) slotRefs.current[slot] = element;
                else delete slotRefs.current[slot];
              }}
              type="button"
              draggable
              key={slot}
              className={`${selectedSlot === slot ? "stage-slot is-active" : "stage-slot"}${dragged === slot ? " is-dragging" : ""}`}
              aria-pressed={selectedSlot === slot}
              tabIndex={selectedSlot === slot ? 0 : -1}
              onClick={() => selectSlot(slot)}
              onKeyDown={(event) => navigateSlot(event, index)}
              onDragStart={() => setDragged(slot)}
              onDragEnd={() => setDragged(null)}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => drop(event, slot)}
            >
              <span className="slot-index">#{slot}</span>
              <span className="slot-avatar">
                {character
                  ? <>
                    <span className="slot-avatar-fallback">{(character.dialogue_name || character.name).slice(0, 1)}</span>
                    {character.avatar_key && <img
                      src={`/api/resources/preview?kind=avatar&key=${character.avatar_key}`}
                      alt=""
                      onError={(event) => { event.currentTarget.hidden = true; }}
                    />}
                  </>
                  : <UserRound />}
              </span>
              <span className="slot-copy">
                <strong>{character?.dialogue_name || character?.name || "空栏位"}</strong>
                <small>{character ? "舞台可见" : "点击添加角色"}</small>
              </span>
              <GripVertical className="slot-grip" />
            </button>
          );
        })}
      </div>
    </section>
  );
}

function CueStrip() {
  const project = useProjectStore((state) => state.project);
  const selectedSceneId = useProjectStore((state) => state.selectedSceneId);
  const selectedCueId = useProjectStore((state) => state.selectedCueId);
  const selectCue = useProjectStore((state) => state.selectCue);
  const addCue = useProjectStore((state) => state.addCue);
  const duplicateCue = useProjectStore((state) => state.duplicateCue);
  const deleteCue = useProjectStore((state) => state.deleteCue);
  const moveCue = useProjectStore((state) => state.moveCue);
  const scene = sceneById(project, selectedSceneId);
  const [dragged, setDragged] = useState<string | null>(null);
  const cueRefs = useRef<Record<string, HTMLButtonElement>>({});
  const pendingCueFocus = useRef<string | null>(null);
  useEffect(() => {
    if (pendingCueFocus.current !== selectedCueId) return;
    cueRefs.current[selectedCueId]?.focus();
    pendingCueFocus.current = null;
  }, [selectedCueId]);
  const focusCue = (cue: Cue) => {
    selectCue(cue.cue_id);
    cueRefs.current[cue.cue_id]?.focus();
  };
  const focusAfterCueCommand = (command: () => void) => {
    command();
    pendingCueFocus.current = useProjectStore.getState().selectedCueId;
  };
  const navigateCue = (event: ReactKeyboardEvent<HTMLButtonElement>, index: number) => {
    const nextIndex = event.key === "ArrowRight" || event.key === "ArrowDown"
      ? Math.min(scene.cues.length - 1, index + 1)
      : event.key === "ArrowLeft" || event.key === "ArrowUp"
        ? Math.max(0, index - 1)
        : event.key === "Home"
          ? 0
          : event.key === "End"
            ? scene.cues.length - 1
            : -1;
    if (nextIndex < 0 || nextIndex === index) return;
    event.preventDefault();
    focusCue(scene.cues[nextIndex]);
  };

  return (
    <section className="cue-strip" aria-label="演出节拍">
      <div className="cue-strip-toolbar">
        <div><Clapperboard /><strong>演出节拍</strong><span>{scene.cues.length} 个 Cue</span></div>
        <div>
          <IconButton label="在前面插入" onClick={() => focusAfterCueCommand(() => addCue("before"))}><ArrowLeftToLine /></IconButton>
          <IconButton label="在后面插入" onClick={() => focusAfterCueCommand(() => addCue("after"))}><ArrowRightToLine /></IconButton>
          <IconButton label="复制当前 Cue" onClick={() => focusAfterCueCommand(duplicateCue)}><Copy /></IconButton>
          <IconButton label="删除当前 Cue" disabled={scene.cues.length <= 1} tone="danger" onClick={() => focusAfterCueCommand(deleteCue)}><Trash2 /></IconButton>
        </div>
      </div>
      <div className="cue-list">
        {scene.cues.map((cue, index) => {
          const dialogue = projectCueState(project, cue.cue_id, { sceneId: selectedSceneId }).dialogueEvent;
          const advanced = advancedEventCount(cue);
          return (
            <button
              ref={(element) => {
                if (element) cueRefs.current[cue.cue_id] = element;
                else delete cueRefs.current[cue.cue_id];
              }}
              type="button"
              draggable
              key={cue.cue_id}
              className={cue.cue_id === selectedCueId ? "cue-item is-active" : "cue-item"}
              aria-pressed={cue.cue_id === selectedCueId}
              tabIndex={cue.cue_id === selectedCueId ? 0 : -1}
              onClick={() => selectCue(cue.cue_id)}
              onKeyDown={(event) => navigateCue(event, index)}
              onDragStart={() => setDragged(cue.cue_id)}
              onDragEnd={() => setDragged(null)}
              onDragOver={(event) => event.preventDefault()}
              onDrop={() => {
                if (dragged) moveCue(dragged, cue.cue_id);
                setDragged(null);
              }}
            >
              <span className="cue-number">{String(index + 1).padStart(2, "0")}</span>
              <span className="cue-copy">
                <strong>{cue.title || "未命名演出"}</strong>
                <small>{dialogue?.text || "无对白"}</small>
              </span>
              {advanced > 0 && <span className="advanced-badge" title="专业模式中的字段会原样保留"><Sparkles />高级演出</span>}
            </button>
          );
        })}
        <button className="cue-add" type="button" onClick={() => focusAfterCueCommand(() => addCue("after"))}><Plus />添加演出</button>
      </div>
    </section>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="field">
      <span className="field-label">{label}{hint && <small>{hint}</small>}</span>
      {children}
    </label>
  );
}

function TransactionalTextControl({
  transactionKey,
  value,
  placeholder,
  rows,
  preview,
}: {
  transactionKey: string;
  value: string;
  placeholder?: string;
  rows?: number;
  preview: (key: string, value: string) => void;
}) {
  const beginTransaction = useProjectStore((state) => state.beginTransaction);
  const commitTransaction = useProjectStore((state) => state.commitTransaction);
  const cancelTransaction = useProjectStore((state) => state.cancelTransaction);
  const change = (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    beginTransaction(transactionKey);
    preview(transactionKey, event.target.value);
  };
  const finish = () => {
    if (useProjectStore.getState().activeTransaction?.key === transactionKey) {
      commitTransaction(transactionKey);
    }
  };
  const keyDown = (event: ReactKeyboardEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    cancelTransaction(transactionKey);
    event.currentTarget.blur();
  };
  const common = {
    value,
    placeholder,
    onFocus: () => beginTransaction(transactionKey),
    onCompositionStart: () => beginTransaction(transactionKey),
    onChange: change,
    onBlur: finish,
    onKeyDown: keyDown,
  };
  return rows
    ? <textarea {...common} rows={rows} />
    : <input {...common} />;
}

function TransactionalNumberControl({
  transactionKey,
  value,
  min,
  max,
  step,
  preview,
}: {
  transactionKey: string;
  value: number | undefined;
  min?: number;
  max?: number;
  step?: number;
  preview: (key: string, value: number) => void;
}) {
  const canonical = value === undefined ? "" : String(value);
  const [draft, setDraft] = useState(canonical);
  const [focused, setFocused] = useState(false);
  const baselineRef = useRef(canonical);
  const beginTransaction = useProjectStore((state) => state.beginTransaction);
  const commitTransaction = useProjectStore((state) => state.commitTransaction);
  const cancelTransaction = useProjectStore((state) => state.cancelTransaction);
  const parsed = parseNumericDraft(draft, { min, max });

  useEffect(() => {
    if (!focused) setDraft(canonical);
  }, [canonical, focused]);

  const begin = () => {
    baselineRef.current = canonical;
    setFocused(true);
    beginTransaction(transactionKey);
  };
  const cancel = () => {
    cancelTransaction(transactionKey);
    setFocused(false);
    setDraft(baselineRef.current);
  };
  const finish = () => {
    const finalValue = parseNumericDraft(draft, { min, max });
    if (finalValue === null) {
      cancel();
      return;
    }
    beginTransaction(transactionKey);
    preview(transactionKey, finalValue);
    commitTransaction(transactionKey);
    setFocused(false);
    setDraft(String(finalValue));
  };

  return (
    <input
      type="number"
      min={min}
      max={max}
      step={step}
      value={draft}
      aria-invalid={focused && parsed === null}
      onFocus={begin}
      onChange={(event) => {
        const nextDraft = event.target.value;
        setDraft(nextDraft);
        beginTransaction(transactionKey);
        const nextValue = parseNumericDraft(nextDraft, { min, max });
        if (nextValue !== null) preview(transactionKey, nextValue);
      }}
      onBlur={finish}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          cancel();
          event.currentTarget.blur();
        } else if (event.key === "Enter") {
          event.preventDefault();
          event.currentTarget.blur();
        }
      }}
    />
  );
}

function CapabilityTrialPicker({
  label,
  kind,
  slot,
  value,
  authoredValue,
  options,
  transactionKey,
}: {
  label: string;
  kind: Exclude<CapabilityStateKind, "transition">;
  slot: number;
  value: string;
  authoredValue: string;
  options: CapabilityStateOption[];
  transactionKey: string;
}) {
  const activeTransaction = useProjectStore((state) => state.activeTransaction);
  const beginTransaction = useProjectStore((state) => state.beginTransaction);
  const previewCharacterState = useProjectStore((state) => state.previewCharacterState);
  const commitTransaction = useProjectStore((state) => state.commitTransaction);
  const cancelTransaction = useProjectStore((state) => state.cancelTransaction);
  const [notice, setNotice] = useState("");
  const trialActive = activeTransaction?.key === transactionKey;
  const field = `${kind}_id`;
  const trial = (option: CapabilityStateOption) => {
    if (option.availability !== "available") return;
    beginTransaction(transactionKey, { interruption: "cancel" });
    previewCharacterState(transactionKey, slot, { [field]: option.state_id });
    setNotice(`${label} ${option.label} 正在试演`);
  };
  const cancel = () => {
    if (useProjectStore.getState().activeTransaction?.key !== transactionKey) return;
    cancelTransaction(transactionKey);
    setNotice(`${label}试演已取消`);
  };
  const commit = (option: CapabilityStateOption) => {
    trial(option);
    const result = commitTransaction(transactionKey);
    setNotice(result.status === "committed"
      ? `${label}已设为 ${option.label}`
      : `${label}保持 ${option.label}`);
  };

  return (
    <div
      className="capability-trial-picker"
      role="group"
      aria-label={`${label}能力`}
      onPointerLeave={(event) => {
        if (useProjectStore.getState().activeTransaction?.key !== transactionKey) return;
        const focused = event.currentTarget.querySelector<HTMLButtonElement>("button:focus");
        const focusedOption = options.find((option) => option.state_id === focused?.dataset.stateId);
        if (focusedOption) trial(focusedOption);
        else cancel();
      }}
      onBlur={(event) => {
        if (event.relatedTarget instanceof Node && event.currentTarget.contains(event.relatedTarget)) return;
        cancel();
      }}
      onKeyDown={(event) => {
        if (event.key !== "Escape") return;
        event.preventDefault();
        cancel();
      }}
    >
      <div className="capability-trial-heading">
        <span>{label}</span>
        <small>{trialActive ? "试演中 · 单击确认" : "悬停或聚焦试演"}</small>
      </div>
      <div className="capability-trial-options">
        {options.map((option) => {
          const isCurrent = value === option.state_id;
          const isAuthored = authoredValue === option.state_id;
          return (
            <button
              type="button"
              key={option.state_id}
              data-state-id={option.state_id}
              className={`${isCurrent ? "is-current" : ""}${isAuthored ? " is-authored" : ""}${option.availability !== "available" ? " is-unavailable" : ""}`.trim()}
              aria-pressed={isCurrent}
              disabled={option.availability !== "available"}
              title={option.diagnostic || `${option.label} · ${option.state_id}`}
              onPointerEnter={() => trial(option)}
              onFocus={() => trial(option)}
              onClick={() => commit(option)}
            >
              <span>{option.label}</span>
              {option.availability !== "available"
                ? <small>不可试演</small>
                : isCurrent && trialActive && !isAuthored
                  ? <small>试演</small>
                  : isAuthored
                    ? <small>已选</small>
                    : null}
            </button>
          );
        })}
      </div>
      <p className="sr-only" aria-live="polite">{notice}</p>
    </div>
  );
}

function CharacterInspector() {
  const project = useProjectStore((state) => state.project);
  const selectedSceneId = useProjectStore((state) => state.selectedSceneId);
  const selectedSlot = useProjectStore((state) => state.selectedSlot);
  const activeTransaction = useProjectStore((state) => state.activeTransaction);
  const setSlotCharacter = useProjectStore((state) => state.setSlotCharacter);
  const updateCharacterState = useProjectStore((state) => state.updateCharacterState);
  const selectedCueId = useProjectStore((state) => state.selectedCueId);
  const projection = projectCueState(project, selectedCueId, { sceneId: selectedSceneId });
  const characterId = projection.afterCue.slots[selectedSlot - 1];
  const character = project.characters.find((item) => item.character_id === characterId);
  const stateEvent = projection.afterCue.actorStateEvents[selectedSlot - 1];
  const motionEvent = characterMotionEventForCue(projection.cue, selectedSlot, characterId);
  const trialPrefix = `capability-trial:${selectedSceneId}:${selectedCueId}:${selectedSlot}:`;
  const authoredProject = activeTransaction?.key.startsWith(trialPrefix)
    ? activeTransaction.base.project
    : project;
  const authoredProjection = projectCueState(authoredProject, selectedCueId, { sceneId: selectedSceneId });
  const authoredEvent = authoredProjection.afterCue.actorStateEvents[selectedSlot - 1];
  const authoredMotionEvent = characterMotionEventForCue(
    authoredProjection.cue,
    selectedSlot,
    characterId,
  );
  const expressionId = String(stateEvent?.expression_id || "expression/neutral");
  const motionId = String(motionEvent?.motion_id || "motion/idle");
  const emoticonId = String(stateEvent?.emoticon_id || "emoticon/none");
  const authoredExpressionId = String(authoredEvent?.expression_id || "expression/neutral");
  const authoredMotionId = String(authoredMotionEvent?.motion_id || "motion/idle");
  const authoredEmoticonId = String(authoredEvent?.emoticon_id || "emoticon/none");
  const expressionStates = capabilityStateOptionsFor(character, "expression", authoredExpressionId);
  const motionStates = capabilityStateOptionsFor(character, "motion", authoredMotionId);
  const emoticonStates = capabilityStateOptionsFor(character, "emoticon", authoredEmoticonId);

  return (
    <div className="inspector-content">
      <div className="selection-summary">
        <span className="selection-icon"><UserRound /></span>
        <span><small>当前栏位</small><strong>#{selectedSlot} · {project.characters.find((item) => item.character_id === characterId)?.dialogue_name || "空栏位"}</strong></span>
      </div>
      <Field label="角色">
        <select value={characterId || ""} onChange={(event) => setSlotCharacter(selectedSlot, event.target.value || null)}>
          <option value="">空栏位</option>
          {project.characters.map((character) => <option key={character.character_id} value={character.character_id}>{character.name}</option>)}
        </select>
      </Field>
      {characterId && <>
        <CapabilityTrialPicker
          label="表情"
          kind="expression"
          slot={selectedSlot}
          value={expressionId}
          authoredValue={authoredExpressionId}
          options={expressionStates}
          transactionKey={`${trialPrefix}expression`}
        />
        <CapabilityTrialPicker
          label="动作"
          kind="motion"
          slot={selectedSlot}
          value={motionId}
          authoredValue={authoredMotionId}
          options={motionStates}
          transactionKey={`${trialPrefix}motion`}
        />
        <CapabilityTrialPicker
          label="表情符号"
          kind="emoticon"
          slot={selectedSlot}
          value={emoticonId}
          authoredValue={authoredEmoticonId}
          options={emoticonStates}
          transactionKey={`${trialPrefix}emoticon`}
        />
        <label className="toggle-row">
          <span><strong>聚焦当前角色</strong><small>发言时压暗其他角色</small></span>
          <input type="checkbox" checked={stateEvent?.focus !== false} onChange={(event) => updateCharacterState(selectedSlot, { focus: event.target.checked })} />
        </label>
      </>}
    </div>
  );
}

function DialogueInspector() {
  const project = useProjectStore((state) => state.project);
  const selectedSceneId = useProjectStore((state) => state.selectedSceneId);
  const selectedCueId = useProjectStore((state) => state.selectedCueId);
  const updateDialogue = useProjectStore((state) => state.updateDialogue);
  const previewDialogue = useProjectStore((state) => state.previewDialogue);
  const dialogue = projectCueState(project, selectedCueId, { sceneId: selectedSceneId }).dialogueEvent
    || { event_id: "", kind: "dialogue", text: "" };
  const auto = dialogue.timing !== "fixed";
  const resolvedDuration = (() => {
    try {
      return eventDurationMs(dialogue);
    } catch {
      return 1000;
    }
  })();

  return (
    <div className="inspector-content">
      <Field label="发言者" hint="#0 为无舞台立绘的旁白或画外音">
        <select value={dialogue.character_id || "#0"} onChange={(event) => updateDialogue({ character_id: event.target.value === "#0" ? undefined : event.target.value })}>
          <option value="#0">#0 · 旁白 / 画外音</option>
          {project.characters.map((character) => <option key={character.character_id} value={character.character_id}>{character.dialogue_name || character.name}</option>)}
        </select>
      </Field>
      <Field label="显示名称">
        <TransactionalTextControl
          transactionKey={`dialogue.display-name:${selectedSceneId}:${selectedCueId}`}
          value={String(dialogue.display_name || "")}
          placeholder="默认使用角色名称"
          preview={(key, value) => previewDialogue(key, { display_name: value })}
        />
      </Field>
      <Field label="对白">
        <TransactionalTextControl
          transactionKey={`dialogue.text:${selectedSceneId}:${selectedCueId}`}
          rows={7}
          value={dialogue.text || ""}
          placeholder="输入这一拍的对白…"
          preview={(key, value) => previewDialogue(key, { text: value })}
        />
      </Field>
      <div className="field-grid two">
        <Field label="语音">
          <button className="resource-input" type="button"><Upload />选择语音<span>未设置</span></button>
        </Field>
        <Field label="时长">
          <div className="duration-input"><input type="number" disabled={auto} min={100} step={100} value={dialogue.duration_ms ?? resolvedDuration} onChange={(event) => updateDialogue({ duration_ms: Number(event.target.value) })} /><span>ms</span></div>
        </Field>
      </div>
      <label className="toggle-row">
        <span><strong>自动估算时长</strong><small>根据文字与语音长度更新</small></span>
        <input type="checkbox" checked={auto} onChange={(event) => updateDialogue({ timing: event.target.checked ? "auto" : "fixed" })} />
      </label>
    </div>
  );
}

function EnvironmentInspector() {
  const project = useProjectStore((state) => state.project);
  const selectedSceneId = useProjectStore((state) => state.selectedSceneId);
  const selectedCueId = useProjectStore((state) => state.selectedCueId);
  const updateEnvironment = useProjectStore((state) => state.updateEnvironment);
  const beginTransaction = useProjectStore((state) => state.beginTransaction);
  const previewEnvironment = useProjectStore((state) => state.previewEnvironment);
  const commitTransaction = useProjectStore((state) => state.commitTransaction);
  const cancelTransaction = useProjectStore((state) => state.cancelTransaction);
  const addQuickEffect = useProjectStore((state) => state.addQuickEffect);
  const projection = projectCueState(project, selectedCueId, { sceneId: selectedSceneId });
  const background = projection.cueBackgroundEvent || projection.beforeCue.backgroundEvent;
  const transitionId = typeof background?.transition_id === "string"
    ? background.transition_id
    : undefined;
  const transitionStates = capabilityStatesFor(undefined, "transition", transitionId);
  const zoomTransactionKey = `environment.zoom:${selectedSceneId}:${selectedCueId}`;
  const updateZoom = (zoom: number) => {
    if (useProjectStore.getState().activeTransaction?.key === zoomTransactionKey) {
      previewEnvironment(zoomTransactionKey, { zoom });
    } else {
      updateEnvironment({ zoom });
    }
  };
  const commitZoom = () => {
    if (useProjectStore.getState().activeTransaction?.key === zoomTransactionKey) {
      commitTransaction(zoomTransactionKey);
    }
  };

  return (
    <div className="inspector-content">
      <Field label="背景">
        <select value={background?.resource_id || ""} onChange={(event) => updateEnvironment({ resource_id: event.target.value })}>
          <option value="">沿用上一拍</option>
          {project.resources.filter((resource) => resource.role === "background").map((resource) => <option key={resource.resource_id} value={resource.resource_id}>{resource.logical_key}</option>)}
        </select>
      </Field>
      <div className="field-grid two">
        <Field label="过渡">
          <select value={String(background?.transition_id || "transition/cut")} onChange={(event) => updateEnvironment({ transition_id: event.target.value })}>
            {transitionStates.map((item) => <option key={item.state_id} value={item.state_id}>{item.label}</option>)}
          </select>
        </Field>
        <Field label="BGM">
          <select defaultValue="keep"><option value="keep">沿用</option><option value="none">停止</option></select>
        </Field>
      </div>
      <Field label="镜头缩放">
        <div className="range-field">
          <input
            type="range"
            min="0.75"
            max="1.5"
            step="0.01"
            value={Number(background?.zoom || 1)}
            onPointerDown={() => beginTransaction(zoomTransactionKey)}
            onPointerUp={commitZoom}
            onPointerCancel={() => cancelTransaction(zoomTransactionKey)}
            onBlur={commitZoom}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.preventDefault();
                cancelTransaction(zoomTransactionKey);
                return;
              }
              if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End"].includes(event.key)) {
                beginTransaction(zoomTransactionKey);
              }
            }}
            onKeyUp={commitZoom}
            onChange={(event) => updateZoom(Number(event.target.value))}
          />
          <output>{Number(background?.zoom || 1).toFixed(2)}×</output>
        </div>
      </Field>
      <div className="quick-effects">
        <span className="section-label">快速演出</span>
        <div>
          <button type="button" onClick={() => addQuickEffect("halocue.ba:background-pan")}><Move />背景移动</button>
          <button type="button" onClick={() => addQuickEffect("halocue.ba:screen-shake")}><Zap />画面震动</button>
          <button type="button" onClick={() => addQuickEffect("halocue.ba:screen-text")}><MessageSquareText />屏幕文字</button>
          <button type="button" onClick={() => addQuickEffect("halocue.ba:hit-effect")}><WandSparkles />中弹效果</button>
        </div>
      </div>
    </div>
  );
}

function SimpleInspector() {
  const project = useProjectStore((state) => state.project);
  const selectedSceneId = useProjectStore((state) => state.selectedSceneId);
  const selectedCueId = useProjectStore((state) => state.selectedCueId);
  const tab = useProjectStore((state) => state.inspectorTab);
  const setTab = useProjectStore((state) => state.setInspectorTab);
  const cue = sceneById(project, selectedSceneId)
    .cues.find((item) => item.cue_id === selectedCueId)!;
  const tabs: Array<[InspectorTab, ReactNode, string]> = [
    ["character", <UserRound key="character" />, "角色"],
    ["dialogue", <MessageSquareText key="dialogue" />, "对白"],
    ["environment", <Image key="environment" />, "环境"],
  ];
  const tabRefs = useRef<Partial<Record<InspectorTab, HTMLButtonElement>>>({});
  const focusTab = (value: InspectorTab) => {
    setTab(value);
    tabRefs.current[value]?.focus();
  };
  const navigateTab = (event: ReactKeyboardEvent<HTMLButtonElement>, index: number) => {
    const nextIndex = event.key === "ArrowRight" || event.key === "ArrowDown"
      ? Math.min(tabs.length - 1, index + 1)
      : event.key === "ArrowLeft" || event.key === "ArrowUp"
        ? Math.max(0, index - 1)
        : event.key === "Home"
          ? 0
          : event.key === "End"
            ? tabs.length - 1
            : -1;
    if (nextIndex < 0 || nextIndex === index) return;
    event.preventDefault();
    focusTab(tabs[nextIndex][0]);
  };

  return (
    <aside className="inspector simple-inspector">
      <div className="inspector-heading"><span><CircleGauge />当前演出</span><IconButton label="更多设置"><MoreHorizontal /></IconButton></div>
      <div className="inspector-tabs" role="tablist" aria-label="当前演出属性">
        {tabs.map(([value, icon, label], index) => <button
          ref={(element) => {
            if (element) tabRefs.current[value] = element;
            else delete tabRefs.current[value];
          }}
          key={value}
          type="button"
          role="tab"
          aria-selected={tab === value}
          tabIndex={tab === value ? 0 : -1}
          className={tab === value ? "is-active" : ""}
          onClick={() => setTab(value)}
          onKeyDown={(event) => navigateTab(event, index)}
        >{icon}{label}</button>)}
      </div>
      {tab === "character" && <CharacterInspector />}
      {tab === "dialogue" && <DialogueInspector />}
      {tab === "environment" && <EnvironmentInspector />}
      <div className="inspector-footer"><Check />所有修改已写入统一项目</div>
    </aside>
  );
}

function EventIcon({ kind }: { kind: string }) {
  const icons: Record<EventIconKey, LucideIcon> = {
    dialogue: MessageSquareText,
    background: Image,
    actor: UserRound,
    wait: CircleGauge,
    effect: Sparkles,
  };
  const Icon = icons[eventEditorDefinition(kind)?.icon || "effect"];
  return <Icon />;
}

function ProfessionalEventFields({
  event,
  fields,
  project,
  updateEvent,
  previewEvent,
}: {
  event: CueEvent;
  fields: readonly EventEditorField[];
  project: ReturnType<typeof useProjectStore.getState>["project"];
  updateEvent: (eventId: string, patch: Partial<CueEvent>) => void;
  previewEvent: (key: string, eventId: string, patch: Partial<CueEvent>) => void;
}) {
  return <>
    {fields.map((field) => {
      const value = event[field.key];
      if (field.control === "character") {
        return <Field key={field.key} label={field.label} hint={field.hint}>
          <select value={String(value || "")} onChange={(change) => updateEvent(event.event_id, { [field.key]: change.target.value || undefined })}>
            <option value="">{field.allowNarrator ? "#0 / 旁白 / 画外音" : "选择角色"}</option>
            {project.characters.map((character) => <option key={character.character_id} value={character.character_id}>{character.character_id}</option>)}
          </select>
        </Field>;
      }
      if (field.control === "slot") {
        return <Field key={field.key} label={field.label} hint={field.hint}>
          <TransactionalNumberControl
            transactionKey={`event.field:${event.event_id}:${field.key}`}
            min={field.min}
            max={field.max}
            step={field.step}
            value={typeof value === "number" ? value : field.min}
            preview={(key, nextValue) => previewEvent(key, event.event_id, { [field.key]: nextValue })}
          />
        </Field>;
      }
      if (field.control === "motion") {
        const character = project.characters.find((item) => item.character_id === event.character_id);
        const options = capabilityStateOptionsFor(
          character,
          "motion",
          String(value || "motion/idle"),
        ).filter((option) => option.state_id !== "motion/idle" || value === "motion/idle");
        return <Field key={field.key} label={field.label} hint={field.hint}>
          <select
            value={String(value || "motion/idle")}
            onChange={(change) => updateEvent(event.event_id, { motion_id: change.target.value })}
          >
            {options.map((option) => (
              <option
                key={option.state_id}
                value={option.state_id}
                disabled={option.availability !== "available"}
              >
                {option.label}{option.availability !== "available" ? "（不可用）" : ""}
              </option>
            ))}
          </select>
        </Field>;
      }
      if (field.control === "boolean") {
        return <Field key={field.key} label={field.label} hint={field.hint}>
          <span className="boolean-field">
            <input
              type="checkbox"
              checked={value !== false}
              onChange={(change) => updateEvent(event.event_id, {
                [field.key]: change.target.checked,
              })}
            />
            <span>{value !== false ? "顺序执行" : "与后续事件并行"}</span>
          </span>
        </Field>;
      }
      if (field.control === "background") {
        return <Field key={field.key} label={field.label} hint={field.hint}>
          <select value={String(value || "")} onChange={(change) => updateEvent(event.event_id, { resource_id: change.target.value || undefined })}>
            <option value="">沿用上一拍</option>
            {project.resources.filter((resource) => resource.role === "background").map((resource) => <option key={resource.resource_id} value={resource.resource_id}>{resource.resource_id}</option>)}
          </select>
        </Field>;
      }
      if (field.control === "number") {
        return <Field key={field.key} label={field.label} hint={field.hint}>
          <TransactionalNumberControl
            transactionKey={`event.field:${event.event_id}:${field.key}`}
            min={field.min}
            max={field.max}
            step={field.step}
            value={typeof value === "number" ? value : undefined}
            preview={(key, nextValue) => previewEvent(key, event.event_id, { [field.key]: nextValue })}
          />
        </Field>;
      }
      return <Field key={field.key} label={field.label} hint={field.hint}>
        <TransactionalTextControl
          transactionKey={`event.field:${event.event_id}:${field.key}`}
          rows={field.multiline ? 6 : undefined}
          value={String(value || "")}
          preview={(key, nextValue) => previewEvent(key, event.event_id, { [field.key]: nextValue })}
        />
      </Field>;
    })}
  </>;
}

function ProfessionalEventList() {
  const project = useProjectStore((state) => state.project);
  const selectedSceneId = useProjectStore((state) => state.selectedSceneId);
  const selectedCueId = useProjectStore((state) => state.selectedCueId);
  const selectedEventId = useProjectStore((state) => state.selectedEventId);
  const selectedEventIds = useProjectStore((state) => state.selectedEventIds);
  const selectEvent = useProjectStore((state) => state.selectEvent);
  const moveEvent = useProjectStore((state) => state.moveEvent);
  const deleteEvent = useProjectStore((state) => state.deleteEvent);
  const deleteSelectedEvents = useProjectStore((state) => state.deleteSelectedEvents);
  const duplicateSelectedEvents = useProjectStore((state) => state.duplicateSelectedEvents);
  const addEvent = useProjectStore((state) => state.addEvent);
  const cue = sceneById(project, selectedSceneId)
    .cues.find((item) => item.cue_id === selectedCueId)!;
  const [draggedEventIds, setDraggedEventIds] = useState<string[]>([]);
  const draggedEventIdRef = useRef<string | null>(null);
  const draggedEventIdsRef = useRef<string[]>([]);
  const [dropTarget, setDropTarget] = useState<{
    eventId: string;
    placement: EventDropPlacement;
  } | null>(null);
  const [reorderNotice, setReorderNotice] = useState("");
  const eventListRef = useRef<HTMLDivElement>(null);
  const [insertPlacement, setInsertPlacement] = useState<EventInsertPlacement>("after");
  const selectedEventIndex = cue.events.findIndex((event) => event.event_id === selectedEventId);
  const selectionFirstIndex = cue.events.findIndex((event) => selectedEventIds.includes(event.event_id));
  const selectionLastIndex = cue.events.reduce((lastIndex, event, index) => (
    selectedEventIds.includes(event.event_id) ? index : lastIndex
  ), -1);
  const addSummary = cue.events.length === 0
    ? "添加第一个事件"
    : selectedEventIndex < 0
      ? "添加到末尾"
      : `在 ${String(selectedEventIndex + 1).padStart(2, "0")} ${insertPlacement === "before" ? "前" : "后"}添加`;
  const moveAndAnnounce = (eventId: string, move: EventMove) => {
    const before = useProjectStore.getState();
    const movedEventIds = before.selectedEventIds.includes(eventId)
      ? before.selectedEventIds
      : [eventId];
    if (!before.selectedEventIds.includes(eventId)) selectEvent(eventId);
    const result = moveEvent(eventId, move);
    if (result.status !== "committed") return;
    const current = useProjectStore.getState();
    const currentCue = sceneById(current.project, current.selectedSceneId)
      .cues.find((item) => item.cue_id === current.selectedCueId);
    const nextIndexes = movedEventIds
      .map((id) => currentCue?.events.findIndex((item) => item.event_id === id) ?? -1)
      .filter((index) => index >= 0);
    const nextIndex = nextIndexes[0] ?? -1;
    const moved = currentCue?.events[nextIndex];
    if (movedEventIds.length > 1 && nextIndexes.length === movedEventIds.length) {
      setReorderNotice(`${movedEventIds.length} 个事件已移动到第 ${nextIndexes[0] + 1}–${nextIndexes.at(-1)! + 1} 项`);
    } else if (moved) {
      setReorderNotice(`${eventLabel(moved.kind) || "扩展演出"} 已移动到第 ${nextIndex + 1} 项`);
    }
  };
  const clearDrag = () => {
    draggedEventIdRef.current = null;
    draggedEventIdsRef.current = [];
    setDraggedEventIds([]);
    setDropTarget(null);
  };
  const deleteSelection = () => {
    const count = selectedEventIds.length;
    const result = deleteSelectedEvents();
    if (result.status === "committed") setReorderNotice(`${count} 个事件已删除`);
  };
  const duplicateSelection = () => {
    const count = useProjectStore.getState().selectedEventIds.length;
    const result = duplicateSelectedEvents();
    if (result.status === "committed") setReorderNotice(`${count} 个事件已复制`);
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target;
      const command = editorKeyboardCommand({
        key: event.key,
        ctrlKey: event.ctrlKey,
        metaKey: event.metaKey,
        shiftKey: event.shiftKey,
        altKey: event.altKey,
        composing: event.isComposing,
        textEditing: isTextEditingTarget(target),
        eventListActive: target instanceof Node && Boolean(eventListRef.current?.contains(target)),
      });
      if (!command || command === "save") return;
      event.preventDefault();

      if (command === "undo") {
        const result = useProjectStore.getState().undo();
        if (result.status === "committed") setReorderNotice("已撤销上一步编辑");
        return;
      }
      if (command === "redo") {
        const result = useProjectStore.getState().redo();
        if (result.status === "committed") setReorderNotice("已重做上一步编辑");
        return;
      }
      if (command === "duplicate-selection") {
        duplicateSelection();
        return;
      }
      if (command === "delete-selection") {
        deleteSelection();
        return;
      }

      const state = useProjectStore.getState();
      const eventId = state.selectedEventId;
      if (!eventId) return;
      if (command === "move-selection-up" || command === "move-selection-down") {
        moveAndAnnounce(eventId, command === "move-selection-up" ? -1 : 1);
        return;
      }

      const currentCue = sceneById(state.project, state.selectedSceneId)
        .cues.find((item) => item.cue_id === state.selectedCueId);
      if (!currentCue) return;
      const sourceIds = new Set(state.selectedEventIds.includes(eventId)
        ? state.selectedEventIds
        : [eventId]);
      const externalEvents = currentCue.events.filter((item) => !sourceIds.has(item.event_id));
      const targetEvent = command === "move-selection-start"
        ? externalEvents[0]
        : externalEvents.at(-1);
      if (!targetEvent) return;
      moveAndAnnounce(eventId, {
        targetEventId: targetEvent.event_id,
        placement: command === "move-selection-start" ? "before" : "after",
      });
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  });

  return (
    <section className="event-workbench">
      <header>
        <div><Layers3 /><span><strong>{cue.title}</strong><small>{cue.events.length} 个有序事件{selectedEventIds.length > 1 ? ` · 已选 ${selectedEventIds.length} 项` : ""}</small></span></div>
        <div className="event-workbench-actions">
          <details className="event-add-menu">
          <summary><Plus />{addSummary}</summary>
          <div className="event-add-options">
            {cue.events.length > 0 && selectedEventIndex >= 0 && (
              <div className="event-insert-position">
                <span>相对所选事件</span>
                <div role="group" aria-label="新事件插入位置">
                  <button
                    type="button"
                    className={insertPlacement === "before" ? "is-active" : ""}
                    aria-pressed={insertPlacement === "before"}
                    onClick={() => setInsertPlacement("before")}
                  ><ArrowUp />之前</button>
                  <button
                    type="button"
                    className={insertPlacement === "after" ? "is-active" : ""}
                    aria-pressed={insertPlacement === "after"}
                    onClick={() => setInsertPlacement("after")}
                  ><ArrowDown />之后</button>
                </div>
              </div>
            )}
            {eventEditorDefinitions().filter((definition) => definition.timelineSupported).map((definition) => (
              <button
                type="button"
                key={definition.kind}
                onClick={(event) => {
                  addEvent(definition.kind, {
                    anchorEventId: selectedEventId,
                    placement: insertPlacement,
                  });
                  event.currentTarget.closest("details")?.removeAttribute("open");
                }}
              >
                <EventIcon kind={definition.kind} />
                {definition.label}
              </button>
            ))}
          </div>
          </details>
        </div>
      </header>
      <div className="event-list" ref={eventListRef}>
        <p className="sr-only" aria-live="polite">{reorderNotice}</p>
        {selectedEventIds.length > 1 && (
          <div className="event-selection-toolbar" role="toolbar" aria-label={`${selectedEventIds.length} 个已选事件的批量操作`}>
            <span>{selectedEventIds.length} 项已选</span>
            <button type="button" onClick={duplicateSelection}><Copy />复制</button>
            <button className="is-danger" type="button" onClick={deleteSelection}><Trash2 />删除</button>
          </div>
        )}
        {cue.events.map((event, index) => (
          <div
            key={event.event_id}
            className={`${event.event_id === selectedEventId ? "event-row is-active" : "event-row"}${selectedEventIds.includes(event.event_id) ? " is-selected" : ""}${draggedEventIds.includes(event.event_id) ? " is-dragging" : ""}${dropTarget?.eventId === event.event_id ? ` is-drop-${dropTarget.placement}` : ""}`}
            onDragOver={(dragEvent) => {
              const sourceId = draggedEventIdRef.current;
              if (!sourceId || draggedEventIdsRef.current.includes(event.event_id)) {
                if (dropTarget?.eventId === event.event_id) setDropTarget(null);
                return;
              }
              dragEvent.preventDefault();
              dragEvent.dataTransfer.dropEffect = "move";
              const rect = dragEvent.currentTarget.getBoundingClientRect();
              const placement = eventDropPlacement(dragEvent.clientY, rect.top, rect.height);
              setDropTarget({ eventId: event.event_id, placement });
            }}
            onDragLeave={(dragEvent) => {
              if (dragEvent.relatedTarget instanceof Node && dragEvent.currentTarget.contains(dragEvent.relatedTarget)) return;
              if (dropTarget?.eventId === event.event_id) setDropTarget(null);
            }}
            onDrop={(dragEvent) => {
              dragEvent.preventDefault();
              const sourceId = draggedEventIdRef.current;
              if (sourceId && !draggedEventIdsRef.current.includes(event.event_id)) {
                const rect = dragEvent.currentTarget.getBoundingClientRect();
                moveAndAnnounce(sourceId, {
                  targetEventId: event.event_id,
                  placement: eventDropPlacement(dragEvent.clientY, rect.top, rect.height),
                });
              }
              clearDrag();
            }}
          >
            <button
              className="event-drag-handle"
              type="button"
              draggable
              aria-label={selectedEventIds.length > 1 && selectedEventIds.includes(event.event_id)
                ? `重排已选 ${selectedEventIds.length} 个事件，当前主项第 ${index + 1} 项，共 ${cue.events.length} 项`
                : `重排${eventLabel(event.kind) || "扩展演出"}，当前第 ${index + 1} 项，共 ${cue.events.length} 项`}
              aria-keyshortcuts="Alt+ArrowUp Alt+ArrowDown Alt+Home Alt+End"
              title={selectedEventIds.length > 1 && selectedEventIds.includes(event.event_id)
                ? `拖动或按 Alt+方向键重排已选 ${selectedEventIds.length} 个事件`
                : "拖动重排；Alt+方向键逐项移动，Alt+Home/End 移到首尾"}
              onClick={() => {
                if (!selectedEventIds.includes(event.event_id)) selectEvent(event.event_id);
              }}
              onDragStart={(dragEvent) => {
                const dragIds = selectedEventIds.includes(event.event_id)
                  ? selectedEventIds
                  : [event.event_id];
                dragEvent.dataTransfer.effectAllowed = "move";
                dragEvent.dataTransfer.setData("text/plain", event.event_id);
                draggedEventIdRef.current = event.event_id;
                draggedEventIdsRef.current = dragIds;
                setDraggedEventIds(dragIds);
                setDropTarget(null);
                if (!selectedEventIds.includes(event.event_id)) selectEvent(event.event_id);
              }}
              onDragEnd={clearDrag}
            >
              <GripVertical />
            </button>
            <button
              className="event-main"
              type="button"
              aria-pressed={selectedEventIds.includes(event.event_id)}
              aria-keyshortcuts="Control+D Meta+D Delete"
              onClick={(selectionEvent) => {
                const mode = selectionEvent.shiftKey
                  ? selectionEvent.ctrlKey || selectionEvent.metaKey ? "add-range" : "range"
                  : selectionEvent.ctrlKey || selectionEvent.metaKey ? "toggle" : "replace";
                selectEvent(event.event_id, mode);
              }}
            >
              <span className="event-icon"><EventIcon kind={event.kind} /></span>
              <span className="event-order">{String(index + 1).padStart(2, "0")}</span>
              <span className="event-copy">
                <strong>{eventLabel(event.kind) || "扩展演出"}</strong>
                <small>{eventSummary(event)}</small>
              </span>
              {!eventLabel(event.kind) && <span className="namespace-tag">{event.kind.split(":")[0]}</span>}
            </button>
            <div className="event-actions">
              <IconButton
                label={selectedEventIds.length > 1 && selectedEventIds.includes(event.event_id) ? `上移已选 ${selectedEventIds.length} 个事件` : "上移"}
                disabled={selectedEventIds.includes(event.event_id) ? selectionFirstIndex === 0 : index === 0}
                onClick={() => moveAndAnnounce(event.event_id, -1)}
              ><ArrowUp /></IconButton>
              <IconButton
                label={selectedEventIds.length > 1 && selectedEventIds.includes(event.event_id) ? `下移已选 ${selectedEventIds.length} 个事件` : "下移"}
                disabled={selectedEventIds.includes(event.event_id) ? selectionLastIndex === cue.events.length - 1 : index === cue.events.length - 1}
                onClick={() => moveAndAnnounce(event.event_id, 1)}
              ><ArrowDown /></IconButton>
              <IconButton
                label={selectedEventIds.length > 1 && selectedEventIds.includes(event.event_id) ? `复制已选 ${selectedEventIds.length} 个事件` : "复制事件"}
                onClick={() => {
                  if (!selectedEventIds.includes(event.event_id)) selectEvent(event.event_id);
                  duplicateSelection();
                }}
              ><Copy /></IconButton>
              <IconButton
                label={selectedEventIds.length > 1 && selectedEventIds.includes(event.event_id) ? `删除已选 ${selectedEventIds.length} 个事件` : "删除事件"}
                tone="danger"
                onClick={() => {
                  if (selectedEventIds.length > 1 && selectedEventIds.includes(event.event_id)) deleteSelection();
                  else deleteEvent(event.event_id);
                }}
              ><Trash2 /></IconButton>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function ProfessionalInspector() {
  const project = useProjectStore((state) => state.project);
  const selectedSceneId = useProjectStore((state) => state.selectedSceneId);
  const selectedCueId = useProjectStore((state) => state.selectedCueId);
  const selectedEventId = useProjectStore((state) => state.selectedEventId);
  const updateEvent = useProjectStore((state) => state.updateEvent);
  const previewEvent = useProjectStore((state) => state.previewEvent);
  const cue = sceneById(project, selectedSceneId)
    .cues.find((item) => item.cue_id === selectedCueId)!;
  const event = cue.events.find((item) => item.event_id === selectedEventId) || cue.events[0];
  if (!event) return <aside className="inspector professional-inspector"><div className="empty-state">选择一个事件</div></aside>;
  const resolvedDuration = (() => {
    try {
      return eventDurationMs(event);
    } catch {
      return 1000;
    }
  })();
  const editorDefinition = eventEditorDefinition(event.kind);
  const editorFields = editorDefinition?.fields || [];
  const advancedFields = Object.entries(event).filter(([key]) => (
    !["event_id", "kind", "duration_ms", ...editorFields.map((item) => item.key)].includes(key)
  ));
  const evaluation = useMemo(
    () => evaluateScene(project, selectedCueId, { sceneId: selectedSceneId }),
    [project, selectedCueId, selectedSceneId],
  );
  const eventIndex = cue.events.findIndex((item) => item.event_id === event.event_id);
  const eventDiagnostics = evaluation.diagnostics.filter((item) => (
    item.path.includes(`events[${eventIndex}]`)
    || item.path === `event:${event.event_id}`
    || item.severity === "error"
  ));
  const errorCount = eventDiagnostics.filter((item) => item.severity === "error").length;
  const warningCount = eventDiagnostics.filter((item) => item.severity === "warning").length;
  const timelineProjection = buildShotTimeline({
    sceneId: selectedSceneId,
    cue,
    timeline: evaluation.timeline,
  });
  const timelineTrack = timelineProjection.tracks.find((track) => (
    track.clips.some((clip) => clip.event_id === event.event_id)
  ));
  const timelineClip = timelineTrack?.clips.find((clip) => clip.event_id === event.event_id);

  return (
    <aside className="inspector professional-inspector">
      <div className="inspector-heading"><span><EventIcon kind={event.kind} />事件属性</span><IconButton label="属性菜单"><MoreHorizontal /></IconButton></div>
      <div className="inspector-content">
        <Field label="事件 ID"><input className="mono" value={event.event_id} readOnly /></Field>
        <Field label="事件类型"><input className="mono" value={event.kind} readOnly /></Field>
        <ProfessionalEventFields
          event={event}
          fields={editorFields}
          project={project}
          updateEvent={updateEvent}
          previewEvent={previewEvent}
        />
        <div className="field-grid two">
          <Field label="时长"><div className="duration-input">
            <TransactionalNumberControl
              transactionKey={`event.duration:${event.event_id}`}
              min={1}
              value={event.duration_ms ?? resolvedDuration}
              preview={(key, nextValue) => previewEvent(key, event.event_id, { duration_ms: nextValue })}
            />
            <span>ms</span>
          </div></Field>
          <Field label="开始帧">
            <output className="derived-field-value mono">{timelineClip ? `F${timelineClip.start_frame}` : "未映射"}</output>
          </Field>
        </div>
        {timelineClip && timelineTrack && (
          <section className="event-timing-projection" data-event-timing-projection aria-label="时间轴投影">
            <header><span><ScanLine />时间轴投影</span><strong>{timelineTrack.label}</strong></header>
            <dl>
              <div><dt>开始</dt><dd>F{timelineClip.start_frame}</dd></div>
              <div><dt>结束</dt><dd>F{timelineClip.end_frame}</dd></div>
              <div><dt>帧长</dt><dd>{timelineClip.duration_frames} 帧</dd></div>
            </dl>
            <p className={timelineClip.wait_for_completion ? "is-sequential" : "is-parallel"}>
              {timelineClip.wait_for_completion ? "顺序执行" : "与后续事件并行"}
            </p>
          </section>
        )}
        <details className="advanced-fields" open={!editorDefinition}>
          <summary><ChevronRight />高级字段</summary>
          <div className="property-table">
            {advancedFields.map(([key, value]) => (
              <div key={key}><span className="mono">{key}</span><code>{JSON.stringify(value)}</code></div>
            ))}
            {!advancedFields.length && <p>此事件没有额外字段。</p>}
          </div>
        </details>
      </div>
      <div className={`diagnostic-strip${errorCount ? " is-error" : warningCount ? " is-warning" : ""}`}>
        {errorCount ? <AlertTriangle /> : warningCount ? <AlertTriangle /> : <Check />}
        {errorCount ? `${errorCount} 个错误需要修复` : warningCount ? `${warningCount} 个警告` : "事件通过基础校验"}
      </div>
    </aside>
  );
}

function formatTimelineFrame(frame: number, frameRate: number): string {
  const totalSeconds = frame / frameRate;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds - minutes * 60;
  return `${String(minutes).padStart(2, "0")}:${seconds.toFixed(2).padStart(5, "0")}`;
}

function Timeline() {
  const project = useProjectStore((state) => state.project);
  const selectedSceneId = useProjectStore((state) => state.selectedSceneId);
  const selectedCueId = useProjectStore((state) => state.selectedCueId);
  const selectedEventId = useProjectStore((state) => state.selectedEventId);
  const playheadFrame = useProjectStore((state) => state.previewPlayheadFrame);
  const selectCue = useProjectStore((state) => state.selectCue);
  const setPlayheadFrame = useProjectStore((state) => state.setPreviewPlayheadFrame);
  const scene = sceneById(project, selectedSceneId);
  const evaluation = useMemo(
    () => evaluateScene(project, selectedCueId, { sceneId: selectedSceneId }),
    [project, selectedCueId, selectedSceneId],
  );
  const cue = scene.cues.find((item) => item.cue_id === selectedCueId);
  const cueEventIds = new Set(cue?.events.map((event) => event.event_id));
  const eventSegments = evaluation.timeline.events.filter((event) => cueEventIds.has(event.event_id));
  const cueStartFrame = eventSegments[0]?.start_frame || 0;
  const cueEndFrame = Math.max(
    cueStartFrame,
    (eventSegments.at(-1)?.end_frame || evaluation.timeline.total_frames) - 1,
  );
  const selectedEventFrame = eventSegments.find(
    (event) => event.event_id === selectedEventId,
  )?.start_frame;
  const visibleFrame = Math.max(
    cueStartFrame,
    Math.min(cueEndFrame, playheadFrame ?? selectedEventFrame ?? cueEndFrame),
  );
  const cueFrameSpan = Math.max(1, cueEndFrame - cueStartFrame);
  const playheadPercent = ((visibleFrame - cueStartFrame) / cueFrameSpan) * 100;
  const rulerFrames = Array.from({ length: 4 }, (_, index) => (
    Math.round(cueStartFrame + (cueFrameSpan * index) / 3)
  ));
  const scrubAt = (clientX: number, element: HTMLElement) => {
    const rect = element.getBoundingClientRect();
    const ratio = rect.width > 0
      ? Math.max(0, Math.min(1, (clientX - rect.left) / rect.width))
      : 0;
    setPlayheadFrame(Math.round(cueStartFrame + ratio * cueFrameSpan));
  };
  const nudgePlayhead = (frame: number) => {
    setPlayheadFrame(Math.max(cueStartFrame, Math.min(cueEndFrame, frame)));
  };
  return (
    <section className="timeline-panel">
      <div className="timeline-ruler">
        {rulerFrames.map((frame, index) => (
          <span key={`${index}:${frame}`}>{formatTimelineFrame(frame, evaluation.timeline.frame_rate)}</span>
        ))}
      </div>
      <div className="timeline-track timeline-scrub-track">
        <span className="track-label"><Play />播放头</span>
        <div
          className="timeline-scrubber"
          role="slider"
          tabIndex={0}
          aria-label="预览播放头"
          aria-valuemin={cueStartFrame}
          aria-valuemax={cueEndFrame}
          aria-valuenow={visibleFrame}
          aria-valuetext={`${formatTimelineFrame(visibleFrame, evaluation.timeline.frame_rate)}，第 ${visibleFrame} 帧`}
          onPointerDown={(event) => {
            event.currentTarget.setPointerCapture(event.pointerId);
            scrubAt(event.clientX, event.currentTarget);
          }}
          onPointerMove={(event) => {
            if (event.currentTarget.hasPointerCapture(event.pointerId)) {
              scrubAt(event.clientX, event.currentTarget);
            }
          }}
          onKeyDown={(event) => {
            const page = Math.max(1, evaluation.timeline.frame_rate);
            const target = {
              ArrowLeft: visibleFrame - 1,
              ArrowDown: visibleFrame - 1,
              ArrowRight: visibleFrame + 1,
              ArrowUp: visibleFrame + 1,
              PageDown: visibleFrame - page,
              PageUp: visibleFrame + page,
              Home: cueStartFrame,
              End: cueEndFrame,
            }[event.key];
            if (target !== undefined) {
              event.preventDefault();
              nudgePlayhead(target);
            } else if (event.key === "Escape") {
              event.preventDefault();
              setPlayheadFrame(null);
            }
          }}
        >
          <span className="scrub-progress" style={{ width: `${playheadPercent}%` }} />
          <span className="scrub-playhead" style={{ left: `${playheadPercent}%` }} />
          <output>{formatTimelineFrame(visibleFrame, evaluation.timeline.frame_rate)} · F{visibleFrame}</output>
        </div>
      </div>
      <div className="timeline-track">
        <span className="track-label"><Clapperboard />Cue</span>
        <div className="timeline-segments">
          {scene.cues.map((cue, index) => <button type="button" key={cue.cue_id} className={cue.cue_id === selectedCueId ? "is-active" : ""} onClick={() => selectCue(cue.cue_id)}><span>{index + 1}</span>{cue.title}</button>)}
        </div>
      </div>
      <div className="timeline-track event-timeline-track">
        <span className="track-label"><Layers3 />事件</span>
        <div className="timeline-segments">
          {eventSegments.map((event) => (
            <TimelineEventSegment
              key={event.event_id}
              event={event}
              frameRate={evaluation.timeline.frame_rate}
              selected={event.event_id === selectedEventId}
            />
          ))}
        </div>
      </div>
    </section>
  );
}

function shotTimelineClipLabel(clip: ShotTimelineClip): string {
  if (clip.track_id === "character" && clip.slot) return `${clip.label} · #${clip.slot}`;
  return clip.label;
}

function ShotTimelineWorkspace() {
  const project = useProjectStore((state) => state.project);
  const selectedSceneId = useProjectStore((state) => state.selectedSceneId);
  const selectedCueId = useProjectStore((state) => state.selectedCueId);
  const selectedEventId = useProjectStore((state) => state.selectedEventId);
  const playheadFrame = useProjectStore((state) => state.previewPlayheadFrame);
  const selectEvent = useProjectStore((state) => state.selectEvent);
  const setPlayheadFrame = useProjectStore((state) => state.setPreviewPlayheadFrame);
  const clipRefs = useRef<Record<string, HTMLButtonElement>>({});
  const scene = sceneById(project, selectedSceneId);
  const cue = scene.cues.find((item) => item.cue_id === selectedCueId);
  const evaluation = useMemo(
    () => evaluateScene(project, selectedCueId, { sceneId: selectedSceneId }),
    [project, selectedCueId, selectedSceneId],
  );
  const projection = useMemo<ShotTimelineProjection | null>(() => {
    if (!cue) return null;
    return buildShotTimeline({ sceneId: scene.scene_id, cue, timeline: evaluation.timeline });
  }, [cue, evaluation.timeline, scene.scene_id]);
  if (!cue || !projection) return <section className="shot-timeline-panel"><div className="empty-state">选择一个 Cue</div></section>;

  const rangeStart = projection.start_frame;
  const rangeEnd = Math.max(rangeStart + 1, projection.end_frame);
  const span = rangeEnd - rangeStart;
  const orderedClips = projection.tracks.flatMap((track) => track.clips);
  const selectedClip = orderedClips.find((clip) => clip.event_id === selectedEventId);
  const selectedUnmappedEvent = selectedEventId && projection.unmappedEventIds.includes(selectedEventId)
    ? cue.events.find((event) => event.event_id === selectedEventId)
    : undefined;
  const visibleFrame = Math.max(
    rangeStart,
    Math.min(rangeEnd - 1, playheadFrame ?? selectedClip?.start_frame ?? rangeStart),
  );
  const isClipActive = (clip: ShotTimelineClip) => (
    visibleFrame >= clip.start_frame && visibleFrame < clip.end_frame
  );
  const activeClips = orderedClips.filter(isClipActive);
  const activeContext = activeClips.length > 0
    ? `播放头 F${visibleFrame} · ${activeClips.map(shotTimelineClipLabel).join("、")}`
    : `播放头 F${visibleFrame} · 无活跃事件`;
  const playheadPercent = ((visibleFrame - rangeStart) / span) * 100;
  const rulerFrames = Array.from({ length: 5 }, (_, index) => (
    Math.round(rangeStart + (span * index) / 4)
  ));
  const scrubAt = (clientX: number, element: HTMLElement) => {
    const rect = element.getBoundingClientRect();
    const ratio = rect.width > 0
      ? Math.max(0, Math.min(1, (clientX - rect.left) / rect.width))
      : 0;
    setPlayheadFrame(Math.round(rangeStart + ratio * span));
  };
  const clipPosition = (clip: ShotTimelineClip) => ({
    left: `${Math.max(0, ((clip.start_frame - rangeStart) / span) * 100)}%`,
    width: `${Math.max(1.5, ((clip.end_frame - clip.start_frame) / span) * 100)}%`,
  });
  const focusClip = (clip: ShotTimelineClip) => {
    selectEvent(clip.event_id);
    setPlayheadFrame(clip.start_frame);
    clipRefs.current[clip.event_id]?.focus();
  };
  const navigateClip = (event: ReactKeyboardEvent<HTMLButtonElement>, clip: ShotTimelineClip) => {
    const index = orderedClips.findIndex((item) => item.event_id === clip.event_id);
    const nextIndex = event.key === "ArrowRight" || event.key === "ArrowDown"
      ? Math.min(orderedClips.length - 1, index + 1)
      : event.key === "ArrowLeft" || event.key === "ArrowUp"
        ? Math.max(0, index - 1)
        : event.key === "Home"
          ? 0
          : event.key === "End"
            ? orderedClips.length - 1
            : -1;
    if (nextIndex < 0 || nextIndex === index) return;
    event.preventDefault();
    focusClip(orderedClips[nextIndex]);
  };

  return (
    <section className="shot-timeline-panel" aria-label="镜头时间轴">
      <header className="shot-timeline-heading">
        <div>
          <Clapperboard />
          <span>
            <strong>镜头时间轴</strong>
            <small>{cue.title || "未命名演出"} · {projection.total_frames} 帧</small>
            <small data-shot-selection-context aria-live="polite" aria-atomic="true">
              {selectedClip
                ? `已选 ${shotTimelineClipLabel(selectedClip)} · F${selectedClip.start_frame}-${selectedClip.end_frame}`
                : selectedUnmappedEvent
                  ? `已选 ${selectedUnmappedEvent.kind} · ${selectedUnmappedEvent.event_id} · 未映射`
                : "未选择可渲染事件"}
            </small>
            <small data-shot-active-context aria-live="polite" aria-atomic="true">{activeContext}</small>
          </span>
        </div>
        <output aria-live="polite">{formatTimelineFrame(visibleFrame, projection.frame_rate)} · F{visibleFrame}</output>
      </header>
      <div className="shot-timeline-legend" data-shot-timeline-legend aria-label="执行语义图例">
        <span><i className="shot-legend-swatch is-sequential" aria-hidden="true" />顺序执行</span>
        <span><i className="shot-legend-swatch is-parallel" aria-hidden="true" />与后续事件并行</span>
      </div>
      {projection.unmappedEventIds.length > 0 && (
        <div className="shot-timeline-notice" role="status">
          <AlertTriangle />{projection.unmappedEventIds.length} 个高级事件暂未进入可渲染时间轴
        </div>
      )}
      <div className="shot-timeline-scroll">
        <div className="shot-timeline-inner">
          <div className="shot-ruler-row">
            <span className="shot-track-label">时间</span>
            <div
              className="shot-ruler"
              data-shot-ruler
              role="slider"
              tabIndex={0}
              aria-label="镜头时间轴播放头"
              aria-valuemin={rangeStart}
              aria-valuemax={rangeEnd - 1}
              aria-valuenow={visibleFrame}
              aria-valuetext={`${formatTimelineFrame(visibleFrame, projection.frame_rate)}，第 ${visibleFrame} 帧`}
              onPointerDown={(event) => {
                event.currentTarget.setPointerCapture(event.pointerId);
                scrubAt(event.clientX, event.currentTarget);
              }}
              onPointerMove={(event) => {
                if (event.currentTarget.hasPointerCapture(event.pointerId)) scrubAt(event.clientX, event.currentTarget);
              }}
              onClick={(event) => scrubAt(event.clientX, event.currentTarget)}
              onKeyDown={(event) => {
                const step = event.shiftKey ? projection.frame_rate : 1;
                const next = {
                  ArrowLeft: visibleFrame - step,
                  ArrowDown: visibleFrame - step,
                  ArrowRight: visibleFrame + step,
                  ArrowUp: visibleFrame + step,
                  Home: rangeStart,
                  End: rangeEnd - 1,
                }[event.key];
                if (next !== undefined) {
                  event.preventDefault();
                  setPlayheadFrame(Math.max(rangeStart, Math.min(rangeEnd - 1, next)));
                }
              }}
            >
              {rulerFrames.map((frame, index) => <span key={`${frame}:${index}`} style={{ left: `${(index / 4) * 100}%` }}>{formatTimelineFrame(frame, projection.frame_rate)}</span>)}
            </div>
          </div>
          <div className="shot-track-stack">
            <span className="shot-playhead" style={{ left: `calc(110px + (100% - 110px) * ${playheadPercent / 100})` }} />
            {projection.tracks.map((track) => (
              <div className="shot-track-row" key={track.id}>
                <div className="shot-track-label" title={track.label}><strong>{track.label}</strong><small>{track.clips.length || "—"}</small></div>
                <div
                  className="shot-track-lane"
                  data-shot-track={track.id}
                  onPointerDown={(event) => scrubAt(event.clientX, event.currentTarget)}
                  onClick={(event) => scrubAt(event.clientX, event.currentTarget)}
                >
                  {track.clips.map((clip) => {
                    const isActive = isClipActive(clip);
                    return <button
                      ref={(element) => {
                        if (element) clipRefs.current[clip.event_id] = element;
                        else delete clipRefs.current[clip.event_id];
                      }}
                      type="button"
                      className={`shot-clip${clip.event_id === selectedEventId ? " is-selected" : ""}${clip.wait_for_completion ? "" : " is-parallel"}${isActive ? " is-active" : ""}`}
                      data-shot-clip
                      data-shot-active={isActive ? "true" : undefined}
                      data-event-id={clip.event_id}
                      aria-pressed={clip.event_id === selectedEventId}
                      key={clip.event_id}
                      style={clipPosition(clip)}
                      title={`${shotTimelineClipLabel(clip)} · ${clip.start_frame}–${clip.end_frame} · ${clip.wait_for_completion ? "顺序执行" : "与后续事件并行"}`}
                      aria-label={`${track.label}，${shotTimelineClipLabel(clip)}，第 ${clip.start_frame} 至 ${clip.end_frame} 帧${isActive ? "，播放头当前" : ""}`}
                      onPointerDown={(event) => event.stopPropagation()}
                      onClick={(event) => {
                        event.stopPropagation();
                        focusClip(clip);
                      }}
                      onKeyDown={(event) => navigateClip(event, clip)}
                    >
                      <span>{shotTimelineClipLabel(clip)}</span>
                      {!clip.wait_for_completion && <small>并行</small>}
                    </button>;
                  })}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function SimpleWorkspace() {
  return (
    <div className="workspace-grid simple-grid">
      <ProjectRail showCues={false} />
      <main className="simple-main"><PreviewFrame /><StageSlots /><CueStrip /></main>
      <SimpleInspector />
    </div>
  );
}

function ProfessionalWorkspace() {
  type ProfessionalView = "script" | "shot";
  const [workspaceView, setWorkspaceView] = useState<ProfessionalView>("script");
  const tabRefs = useRef<Partial<Record<ProfessionalView, HTMLButtonElement>>>({});
  const views: ProfessionalView[] = ["script", "shot"];
  const focusView = (view: ProfessionalView) => {
    setWorkspaceView(view);
    tabRefs.current[view]?.focus();
  };
  const onTabKeyDown = (event: ReactKeyboardEvent<HTMLButtonElement>, current: ProfessionalView) => {
    const index = views.indexOf(current);
    const nextIndex = event.key === "ArrowRight" || event.key === "ArrowDown"
      ? (index + 1) % views.length
      : event.key === "ArrowLeft" || event.key === "ArrowUp"
        ? (index - 1 + views.length) % views.length
        : event.key === "Home"
          ? 0
          : event.key === "End"
            ? views.length - 1
            : -1;
    if (nextIndex < 0) return;
    event.preventDefault();
    focusView(views[nextIndex]);
  };
  return (
    <div className="workspace-grid professional-grid">
      <ProjectRail showCues />
      <main className="professional-main">
        <div className="professional-view-tabs" role="tablist" aria-label="专业工作区">
          <button
            ref={(element) => { tabRefs.current.script = element || undefined; }}
            id="professional-tab-script"
            type="button"
            role="tab"
            aria-selected={workspaceView === "script"}
            aria-controls="professional-panel-script"
            tabIndex={workspaceView === "script" ? 0 : -1}
            className={workspaceView === "script" ? "is-active" : ""}
            onClick={() => focusView("script")}
            onKeyDown={(event) => onTabKeyDown(event, "script")}
          ><MessageSquareText />脚本</button>
          <button
            ref={(element) => { tabRefs.current.shot = element || undefined; }}
            id="professional-tab-shot"
            type="button"
            role="tab"
            aria-selected={workspaceView === "shot"}
            aria-controls="professional-panel-shot"
            tabIndex={workspaceView === "shot" ? 0 : -1}
            className={workspaceView === "shot" ? "is-active" : ""}
            onClick={() => focusView("shot")}
            onKeyDown={(event) => onTabKeyDown(event, "shot")}
          ><Clapperboard />镜头时间轴</button>
        </div>
        <div className="professional-view-content">
          {workspaceView === "script"
            ? <div id="professional-panel-script" className="professional-script-layout" role="tabpanel" aria-labelledby="professional-tab-script" tabIndex={0}><div className="professional-upper"><PreviewFrame /><ProfessionalEventList /></div><Timeline /></div>
            : <div id="professional-panel-shot" className="professional-shot-layout" role="tabpanel" aria-labelledby="professional-tab-shot" tabIndex={0}><PreviewFrame /><ShotTimelineWorkspace /></div>}
        </div>
      </main>
      <ProfessionalInspector />
    </div>
  );
}

export default function App() {
  const mode = useProjectStore((state) => state.mode);
  const project = useProjectStore((state) => state.project);
  const replaceProject = useProjectStore((state) => state.replaceProject);
  const markSaved = useProjectStore((state) => state.markSaved);
  const input = useRef<HTMLInputElement>(null);
  const [notice, setNotice] = useState("");

  const save = () => {
    const state = useProjectStore.getState();
    if (state.activeTransaction) {
      if (state.activeTransaction.interruption === "cancel") {
        state.cancelTransaction(state.activeTransaction.key);
      } else {
        state.commitTransaction(state.activeTransaction.key);
      }
    }
    useProjectStore.getState().flushAutosave();
    const currentProject = useProjectStore.getState().project;
    projectFileAdapter.download(
      currentProject,
      `${(currentProject.title || "halocue-project").replace(/[\\/:*?\"<>|]/g, "-")}.halocue-project`,
    );
    markSaved();
    setNotice("项目文件已导出");
  };

  const open = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    try {
      replaceProject(await projectFileAdapter.read(file));
      setNotice(`已打开 ${file.name}`);
    } catch (exception) {
      setNotice(exception instanceof Error ? exception.message : "无法打开项目");
    }
  };

  useEffect(() => {
    const flush = () => useProjectStore.getState().flushAutosave();
    window.addEventListener("beforeunload", flush);
    return () => window.removeEventListener("beforeunload", flush);
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented) return;
      const command = editorKeyboardCommand({
        key: event.key,
        ctrlKey: event.ctrlKey,
        metaKey: event.metaKey,
        shiftKey: event.shiftKey,
        altKey: event.altKey,
        composing: event.isComposing,
        textEditing: isTextEditingTarget(event.target),
      });
      if (command === "save") {
        event.preventDefault();
        save();
      } else if (mode === "simple" && (command === "undo" || command === "redo")) {
        event.preventDefault();
        if (command === "redo") useProjectStore.getState().redo();
        else useProjectStore.getState().undo();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [mode, project]);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(""), 3200);
    return () => window.clearTimeout(timer);
  }, [notice]);

  return (
    <div className="app-shell">
      <TopBar onOpen={() => input.current?.click()} onSave={save} />
      <input ref={input} className="file-input" type="file" accept=".halocue-project,.json,application/json" onChange={open} />
      {mode === "simple" ? <SimpleWorkspace /> : <ProfessionalWorkspace />}
      {notice && <div className="toast" role="status"><Check />{notice}</div>}
    </div>
  );
}
