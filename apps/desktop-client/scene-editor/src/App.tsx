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
  Menu,
  MessageSquareText,
  MoreHorizontal,
  Move,
  Play,
  Plus,
  Redo2,
  RotateCcw,
  Save,
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
  type ReactNode,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { projectFileAdapter } from "./projectRepository";
import { capabilityStatesFor } from "./capabilities";
import { evaluateScene } from "./sceneEvaluation";
import { buildPreviewIntent } from "./previewIntent";
import { eventDurationMs } from "./renderTimeline";
import { firstScene, projectCueState } from "./cueStateProjection";
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
  play: (options?: { fromFrame?: number }) => void;
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
        <span className={dirty ? "save-state is-dirty" : "save-state"}>
          {hasProjectError ? "项目有待修复项" : hasProjectWarning ? "项目有校验警告" : dirty ? "草稿已自动保存" : "已保存"}
        </span>
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
  const selectedCueId = useProjectStore((state) => state.selectedCueId);
  const selectCue = useProjectStore((state) => state.selectCue);
  const scene = firstScene(project);
  const chapter = project.chapters[0];

  return (
    <aside className="project-rail">
      <div className="rail-heading">
        <span>{showCues ? "项目" : "场景"}</span>
        <IconButton label="项目菜单"><MoreHorizontal /></IconButton>
      </div>
      <nav className="project-tree" aria-label={showCues ? "完整项目结构" : "场景导航"}>
        <div className="tree-row root"><ChevronDown /><Box />{project.title}</div>
        <div className="tree-row depth-1"><ChevronDown /><Layers3 />{chapter?.title || "章节"}</div>
        <div className="tree-row depth-2 is-open"><ChevronDown /><Clapperboard />{scene.title || "场景"}</div>
        {showCues && <div className="tree-cues">
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
  const selectedCueId = useProjectStore((state) => state.selectedCueId);
  const selectedEventId = useProjectStore((state) => state.selectedEventId);
  const revision = useProjectStore((state) => state.revision);
  const frame = useRef<HTMLIFrameElement>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const controllerRef = useRef<PreviewController | null>(null);
  const mountedEvaluationRef = useRef<SceneEvaluation | null>(null);
  const evaluation = useMemo(
    () => evaluateScene(project, selectedCueId),
    [project, selectedCueId, revision],
  );
  const intent = useMemo(
    () => buildPreviewIntent(project, evaluation, {
      cueId: selectedCueId,
      kind: mode === "professional" ? "event" : "cue",
      eventId: mode === "professional" ? selectedEventId : null,
    }),
    [evaluation, mode, project, selectedCueId, selectedEventId],
  );
  const intentRef = useRef(intent);
  intentRef.current = intent;
  const intentLabel = {
    "selected-event": "所选事件起点",
    "cue-terminal": "Cue 完成态",
    "prior-renderable": "扩展事件前一画面",
    "scene-start": "场景起始画面",
  }[intent.target.resolution];

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
    const timer = window.setTimeout(mount, 140);
    return () => window.clearTimeout(timer);
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

  useEffect(() => () => {
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
        </div>
        <div className="preview-toolbar-actions">
          <button type="button" onClick={mount}><RotateCcw />刷新</button>
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
  const selectedCueId = useProjectStore((state) => state.selectedCueId);
  const selectedSlot = useProjectStore((state) => state.selectedSlot);
  const selectSlot = useProjectStore((state) => state.selectSlot);
  const swapSlots = useProjectStore((state) => state.swapSlots);
  const [dragged, setDragged] = useState<number | null>(null);
  const slots = projectCueState(project, selectedCueId).afterCue.slots;
  const characters = new Map(project.characters.map((character) => [character.character_id, character]));

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
              type="button"
              draggable
              key={slot}
              className={`${selectedSlot === slot ? "stage-slot is-active" : "stage-slot"}${dragged === slot ? " is-dragging" : ""}`}
              onClick={() => selectSlot(slot)}
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
  const selectedCueId = useProjectStore((state) => state.selectedCueId);
  const selectCue = useProjectStore((state) => state.selectCue);
  const addCue = useProjectStore((state) => state.addCue);
  const duplicateCue = useProjectStore((state) => state.duplicateCue);
  const deleteCue = useProjectStore((state) => state.deleteCue);
  const moveCue = useProjectStore((state) => state.moveCue);
  const scene = firstScene(project);
  const [dragged, setDragged] = useState<string | null>(null);

  return (
    <section className="cue-strip" aria-label="演出节拍">
      <div className="cue-strip-toolbar">
        <div><Clapperboard /><strong>演出节拍</strong><span>{scene.cues.length} 个 Cue</span></div>
        <div>
          <IconButton label="在前面插入" onClick={() => addCue("before")}><ArrowLeftToLine /></IconButton>
          <IconButton label="在后面插入" onClick={() => addCue("after")}><ArrowRightToLine /></IconButton>
          <IconButton label="复制当前 Cue" onClick={duplicateCue}><Copy /></IconButton>
          <IconButton label="删除当前 Cue" disabled={scene.cues.length <= 1} tone="danger" onClick={deleteCue}><Trash2 /></IconButton>
        </div>
      </div>
      <div className="cue-list">
        {scene.cues.map((cue, index) => {
          const dialogue = projectCueState(project, cue.cue_id).dialogueEvent;
          const advanced = advancedEventCount(cue);
          return (
            <button
              type="button"
              draggable
              key={cue.cue_id}
              className={cue.cue_id === selectedCueId ? "cue-item is-active" : "cue-item"}
              onClick={() => selectCue(cue.cue_id)}
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
        <button className="cue-add" type="button" onClick={() => addCue("after")}><Plus />添加演出</button>
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

function CharacterInspector() {
  const project = useProjectStore((state) => state.project);
  const selectedSlot = useProjectStore((state) => state.selectedSlot);
  const setSlotCharacter = useProjectStore((state) => state.setSlotCharacter);
  const updateCharacterState = useProjectStore((state) => state.updateCharacterState);
  const selectedCueId = useProjectStore((state) => state.selectedCueId);
  const projection = projectCueState(project, selectedCueId);
  const characterId = projection.afterCue.slots[selectedSlot - 1];
  const character = project.characters.find((item) => item.character_id === characterId);
  const stateEvent = projection.afterCue.actorStateEvents[selectedSlot - 1];
  const expressionStates = capabilityStatesFor(character, "expression", stateEvent?.expression_id);
  const motionStates = capabilityStatesFor(character, "motion", stateEvent?.motion_id);
  const emoticonStates = capabilityStatesFor(character, "emoticon", stateEvent?.emoticon_id);

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
        <div className="field-grid two">
          <Field label="表情">
            <select value={String(stateEvent?.expression_id || "expression/neutral")} onChange={(event) => updateCharacterState(selectedSlot, { expression_id: event.target.value })}>
              {expressionStates.map((item) => <option key={item.state_id} value={item.state_id}>{item.label}</option>)}
            </select>
          </Field>
          <Field label="动作">
            <select value={String(stateEvent?.motion_id || "motion/idle")} onChange={(event) => updateCharacterState(selectedSlot, { motion_id: event.target.value })}>
              {motionStates.map((item) => <option key={item.state_id} value={item.state_id}>{item.label}</option>)}
            </select>
          </Field>
        </div>
        <Field label="表情符号" hint="角色上方的独立叠加层">
          <select value={String(stateEvent?.emoticon_id || "emoticon/none")} onChange={(event) => updateCharacterState(selectedSlot, { emoticon_id: event.target.value })}>
            {emoticonStates.map((item) => <option key={item.state_id} value={item.state_id}>{item.label}</option>)}
          </select>
        </Field>
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
  const selectedCueId = useProjectStore((state) => state.selectedCueId);
  const updateDialogue = useProjectStore((state) => state.updateDialogue);
  const dialogue = projectCueState(project, selectedCueId).dialogueEvent
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
        <input value={String(dialogue.display_name || "")} placeholder="默认使用角色名称" onChange={(event) => updateDialogue({ display_name: event.target.value })} />
      </Field>
      <Field label="对白">
        <textarea rows={7} value={dialogue.text || ""} placeholder="输入这一拍的对白…" onChange={(event) => updateDialogue({ text: event.target.value })} />
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
  const selectedCueId = useProjectStore((state) => state.selectedCueId);
  const updateEnvironment = useProjectStore((state) => state.updateEnvironment);
  const addQuickEffect = useProjectStore((state) => state.addQuickEffect);
  const projection = projectCueState(project, selectedCueId);
  const background = projection.cueBackgroundEvent || projection.beforeCue.backgroundEvent;
  const transitionId = typeof background?.transition_id === "string"
    ? background.transition_id
    : undefined;
  const transitionStates = capabilityStatesFor(undefined, "transition", transitionId);

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
        <div className="range-field"><input type="range" min="0.75" max="1.5" step="0.01" value={Number(background?.zoom || 1)} onChange={(event) => updateEnvironment({ zoom: Number(event.target.value) })} /><output>{Number(background?.zoom || 1).toFixed(2)}×</output></div>
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
  const selectedCueId = useProjectStore((state) => state.selectedCueId);
  const tab = useProjectStore((state) => state.inspectorTab);
  const setTab = useProjectStore((state) => state.setInspectorTab);
  const cue = firstScene(project).cues.find((item) => item.cue_id === selectedCueId)!;
  const tabs: Array<[InspectorTab, ReactNode, string]> = [
    ["character", <UserRound key="character" />, "角色"],
    ["dialogue", <MessageSquareText key="dialogue" />, "对白"],
    ["environment", <Image key="environment" />, "环境"],
  ];

  return (
    <aside className="inspector simple-inspector">
      <div className="inspector-heading"><span><CircleGauge />当前演出</span><IconButton label="更多设置"><MoreHorizontal /></IconButton></div>
      <div className="inspector-tabs" role="tablist">
        {tabs.map(([value, icon, label]) => <button key={value} type="button" role="tab" aria-selected={tab === value} className={tab === value ? "is-active" : ""} onClick={() => setTab(value)}>{icon}{label}</button>)}
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
}: {
  event: CueEvent;
  fields: readonly EventEditorField[];
  project: ReturnType<typeof useProjectStore.getState>["project"];
  updateEvent: (eventId: string, patch: Partial<CueEvent>) => void;
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
          <input type="number" min={field.min} max={field.max} step={field.step} value={Number(value || field.min || 1)} onChange={(change) => updateEvent(event.event_id, { [field.key]: Number(change.target.value) })} />
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
          <input type="number" min={field.min} max={field.max} step={field.step} value={typeof value === "number" ? value : ""} onChange={(change) => updateEvent(event.event_id, { [field.key]: Number(change.target.value) })} />
        </Field>;
      }
      return <Field key={field.key} label={field.label} hint={field.hint}>
        {field.multiline
          ? <textarea rows={6} value={String(value || "")} onChange={(change) => updateEvent(event.event_id, { [field.key]: change.target.value })} />
          : <input value={String(value || "")} onChange={(change) => updateEvent(event.event_id, { [field.key]: change.target.value })} />}
      </Field>;
    })}
  </>;
}

function ProfessionalEventList() {
  const project = useProjectStore((state) => state.project);
  const selectedCueId = useProjectStore((state) => state.selectedCueId);
  const selectedEventId = useProjectStore((state) => state.selectedEventId);
  const selectEvent = useProjectStore((state) => state.selectEvent);
  const moveEvent = useProjectStore((state) => state.moveEvent);
  const deleteEvent = useProjectStore((state) => state.deleteEvent);
  const addEvent = useProjectStore((state) => state.addEvent);
  const cue = firstScene(project).cues.find((item) => item.cue_id === selectedCueId)!;

  return (
    <section className="event-workbench">
      <header>
        <div><Layers3 /><span><strong>{cue.title}</strong><small>{cue.events.length} 个有序事件</small></span></div>
        <details className="event-add-menu">
          <summary><Plus />添加事件</summary>
          <div className="event-add-options">
            {eventEditorDefinitions().filter((definition) => definition.timelineSupported).map((definition) => (
              <button
                type="button"
                key={definition.kind}
                onClick={(event) => {
                  addEvent(definition.kind);
                  event.currentTarget.closest("details")?.removeAttribute("open");
                }}
              >
                <EventIcon kind={definition.kind} />
                {definition.label}
              </button>
            ))}
          </div>
        </details>
      </header>
      <div className="event-list">
        {cue.events.map((event, index) => (
          <div key={event.event_id} className={event.event_id === selectedEventId ? "event-row is-active" : "event-row"}>
            <button className="event-main" type="button" onClick={() => selectEvent(event.event_id)}>
              <GripVertical />
              <span className="event-icon"><EventIcon kind={event.kind} /></span>
              <span className="event-order">{String(index + 1).padStart(2, "0")}</span>
              <span className="event-copy">
                <strong>{eventLabel(event.kind) || "扩展演出"}</strong>
                <small>{eventSummary(event)}</small>
              </span>
              {!eventLabel(event.kind) && <span className="namespace-tag">{event.kind.split(":")[0]}</span>}
            </button>
            <div className="event-actions">
              <IconButton label="上移" disabled={index === 0} onClick={() => moveEvent(event.event_id, -1)}><ArrowUp /></IconButton>
              <IconButton label="下移" disabled={index === cue.events.length - 1} onClick={() => moveEvent(event.event_id, 1)}><ArrowDown /></IconButton>
              <IconButton label="删除事件" tone="danger" onClick={() => deleteEvent(event.event_id)}><Trash2 /></IconButton>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function ProfessionalInspector() {
  const project = useProjectStore((state) => state.project);
  const selectedCueId = useProjectStore((state) => state.selectedCueId);
  const selectedEventId = useProjectStore((state) => state.selectedEventId);
  const updateEvent = useProjectStore((state) => state.updateEvent);
  const cue = firstScene(project).cues.find((item) => item.cue_id === selectedCueId)!;
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
  const evaluation = useMemo(() => evaluateScene(project, selectedCueId), [project, selectedCueId]);
  const eventIndex = cue.events.findIndex((item) => item.event_id === event.event_id);
  const eventDiagnostics = evaluation.diagnostics.filter((item) => (
    item.path.includes(`events[${eventIndex}]`) || item.severity === "error"
  ));
  const errorCount = eventDiagnostics.filter((item) => item.severity === "error").length;
  const warningCount = eventDiagnostics.filter((item) => item.severity === "warning").length;

  return (
    <aside className="inspector professional-inspector">
      <div className="inspector-heading"><span><EventIcon kind={event.kind} />事件属性</span><IconButton label="属性菜单"><MoreHorizontal /></IconButton></div>
      <div className="inspector-content">
        <Field label="事件 ID"><input className="mono" value={event.event_id} readOnly /></Field>
        <Field label="事件类型"><input className="mono" value={event.kind} readOnly /></Field>
        <ProfessionalEventFields event={event} fields={editorFields} project={project} updateEvent={updateEvent} />
        <div className="field-grid two">
          <Field label="时长"><div className="duration-input"><input type="number" min={1} value={event.duration_ms ?? resolvedDuration} onChange={(change) => updateEvent(event.event_id, { duration_ms: Number(change.target.value) })} /><span>ms</span></div></Field>
          <Field label="开始帧"><input className="mono" value="自动" readOnly /></Field>
        </div>
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

function Timeline() {
  const project = useProjectStore((state) => state.project);
  const selectedCueId = useProjectStore((state) => state.selectedCueId);
  const selectedEventId = useProjectStore((state) => state.selectedEventId);
  const selectCue = useProjectStore((state) => state.selectCue);
  const scene = firstScene(project);
  const evaluation = useMemo(
    () => evaluateScene(project, selectedCueId),
    [project, selectedCueId],
  );
  const cue = scene.cues.find((item) => item.cue_id === selectedCueId);
  const cueEventIds = new Set(cue?.events.map((event) => event.event_id));
  const eventSegments = evaluation.timeline.events.filter((event) => cueEventIds.has(event.event_id));
  return (
    <section className="timeline-panel">
      <div className="timeline-ruler"><span>00:00</span><span>00:05</span><span>00:10</span><span>00:15</span></div>
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
            <button
              type="button"
              key={event.event_id}
              className={event.event_id === selectedEventId ? "is-active" : ""}
              title={`${eventLabel(event.kind) || event.kind} · ${event.duration_ms} ms`}
              style={{ flexGrow: event.duration_frames }}
              onClick={() => useProjectStore.getState().selectEvent(event.event_id)}
            >
              <span>{eventLabel(event.kind) || "扩展演出"}</span>
              <small>{event.duration_ms} ms</small>
            </button>
          ))}
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
  return (
    <div className="workspace-grid professional-grid">
      <ProjectRail showCues />
      <main className="professional-main"><div className="professional-upper"><PreviewFrame /><ProfessionalEventList /></div><Timeline /></main>
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
    projectFileAdapter.download(
      project,
      `${(project.title || "halocue-project").replace(/[\\/:*?\"<>|]/g, "-")}.halocue-project`,
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
    const onKeyDown = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey)) return;
      if (event.key.toLowerCase() === "s") { event.preventDefault(); save(); }
      if (event.key.toLowerCase() === "z") {
        event.preventDefault();
        if (event.shiftKey) useProjectStore.getState().redo();
        else useProjectStore.getState().undo();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [project]);

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
