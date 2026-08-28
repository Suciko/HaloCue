(function () {
  "use strict";

  const AA = window.HaloCueAARuntime;
  const SLOT_X = AA.SLOT_LEFT_PERCENT;
  const SUPPORTED_SCHEMA = "scene-descriptor/1.0";
  const STAGE_MEDIA_KINDS = new Set(["portrait", "spine", "spine-frame"]);
  const DEFAULT_ACTOR_MEDIA_SCALE = 1.6;
  const SPINE_RENDERER = window.HaloCueSpineRenderer;
  const PERFORMANCE_RUNTIME = window.HaloCueScenePerformanceRuntime;
  const PREVIEW_INTENT_SCHEMAS = new Set(["preview-intent/1.0", "preview-intent/1.1"]);
  const PREVIEW_INTENT_RESOLUTIONS = new Set([
    "selected-event", "cue-terminal", "prior-renderable", "scene-start", "explicit-frame",
  ]);
  const EVENT_REGISTRY = window.HaloCueSceneEventRegistry || {
    isVisualOnly: () => false,
  };
  const CAPABILITY_RUNTIME = window.HaloCueCapabilityRuntime || {
    motionClass: () => "",
    emoticon: () => null,
    stateId: (value) => typeof value === "string" ? value.trim() : "",
  };

  function assertDescriptor(descriptor) {
    if (!descriptor || descriptor.schema_version !== SUPPORTED_SCHEMA) {
      throw new Error(`Unsupported scene descriptor; expected ${SUPPORTED_SCHEMA}.`);
    }
    if (!Array.isArray(descriptor.actors) || descriptor.actors.length !== 5) {
      throw new Error("Scene descriptor must contain exactly five actor slots.");
    }
    if (!Array.isArray(descriptor.events)) {
      throw new Error("Scene descriptor events must be an array.");
    }
  }

  function actorName(actor) {
    if (actor.dialogue_name) return actor.dialogue_name;
    if (actor.display_name) return actor.display_name;
    if (!actor.character_id) return "";
    const value = actor.character_id.split("/").pop() || actor.character_id;
    return value.charAt(0).toUpperCase() + value.slice(1);
  }

  function actorSecondaryIdentity(actor, descriptor) {
    const primary = actorName(actor);
    const candidates = [
      [actor?.alias, "alias"],
      [actor?.club_name || descriptor?.club_name, "club"],
      [actor?.display_name, "full-name"],
    ];
    const match = candidates.find(([value]) => (
      typeof value === "string" && value.trim() && value.trim() !== primary
    ));
    return match ? { label: match[0].trim(), kind: match[1] } : { label: "", kind: "none" };
  }

  function isSafePreviewUri(uri) {
    return typeof uri === "string"
      && (uri.startsWith("./") || uri.startsWith("/api/resources/preview?")
        || uri.startsWith("/api/resources/stage/"))
      && !uri.includes("..")
      && !uri.includes("\\")
      && !/^[a-z]+:/i.test(uri);
  }

  function resolvePreviewUri(value) {
    if (isSafePreviewUri(value)) return value;
    const resolver = window.HALO_CUE_ASSET_RESOLVER;
    if (typeof resolver !== "function") return "";
    const resolved = resolver(value);
    return isSafePreviewUri(resolved) ? resolved : "";
  }

  function clampUnit(value, fallback) {
    const number = Number(value);
    return Number.isFinite(number) ? Math.max(0, Math.min(1, number)) : fallback;
  }

  function clampBackgroundZoom(value) {
    const number = Number(value);
    return Number.isFinite(number) ? Math.max(0.75, Math.min(1.5, number)) : 1;
  }

  function clampStageOffset(value) {
    const number = Number(value);
    return Number.isFinite(number) ? Math.max(-2048, Math.min(2048, number)) : 0;
  }

  function installStageScale(stage) {
    const update = () => {
      const width = stage.getBoundingClientRect().width;
      const designWidth = Number(AA.DESIGN_WIDTH) || 2560;
      const scale = width > 0 ? width / designWidth : 1;
      stage.style.setProperty("--stage-scale", String(scale));
    };
    const previousObserver = stage.__haloCueStageScaleObserver;
    if (previousObserver && typeof previousObserver.disconnect === "function") {
      previousObserver.disconnect();
    }
    const previousHandler = stage.__haloCueStageScaleHandler;
    if (previousHandler) {
      window.removeEventListener("resize", previousHandler);
      stage.__haloCueStageScaleHandler = null;
    }
    if (typeof ResizeObserver === "function") {
      const observer = new ResizeObserver(update);
      observer.observe(stage);
      stage.__haloCueStageScaleObserver = observer;
    } else {
      stage.__haloCueStageScaleHandler = update;
      window.addEventListener("resize", update, { passive: true });
    }
    update();
  }

  function stageMediaFor(actor) {
    const media = actor && actor.stage_media;
    if (!media || typeof media !== "object" || !STAGE_MEDIA_KINDS.has(media.kind)) {
      return null;
    }
    let previewValue = media.preview_uri;
    if (media.kind === "spine" && typeof media.bundle_key === "string") {
      const key = media.bundle_key.trim();
      const animation = typeof media.animation === "string" && media.animation.trim()
        ? media.animation.trim() : "00_default";
      if (/^[A-Za-z0-9_.-]+$/.test(key) && /^[A-Za-z0-9_.-]+$/.test(animation)) {
        previewValue = `/api/resources/stage/spine/frame?key=${encodeURIComponent(key)}&animation=${encodeURIComponent(animation)}`;
      }
    }
    const previewUri = resolvePreviewUri(previewValue);
    if (!previewUri && media.kind !== "spine") return null;
    return {
      ...media,
      preview_uri: previewUri,
      anchor_x: clampUnit(media.anchor_x, 0.5),
      anchor_y: clampUnit(media.anchor_y, 1),
      scale: Math.max(0.5, Math.min(4, Number(media.scale) || DEFAULT_ACTOR_MEDIA_SCALE)),
      offset_x: clampStageOffset(media.offset_x),
      offset_y: clampStageOffset(media.offset_y),
    };
  }

  function createActor(slot) {
    const element = document.createElement("article");
    element.className = "actor-slot";
    element.dataset.slot = String(slot);
    element.style.left = `${SLOT_X[slot - 1]}%`;
    element.innerHTML = '<div class="actor-portrait" aria-hidden="true"><img class="actor-image" alt="" /><canvas class="actor-canvas" aria-hidden="true"></canvas></div><div class="actor-emoticon" aria-hidden="true" hidden><span class="actor-emoticon-symbol"></span></div><div class="actor-name"></div>';
    return element;
  }

  function canonicalJson(value) {
    if (Array.isArray(value)) return value.map(canonicalJson);
    if (value && typeof value === "object") {
      return Object.fromEntries(
        Object.keys(value).sort().map((key) => [key, canonicalJson(value[key])]),
      );
    }
    return value;
  }

  function resolveRenderTimeline(descriptor, suppliedTimeline) {
    const expected = AA.buildRenderTimeline(descriptor, {
      frameRate: descriptor.presentation?.frame_rate ?? AA.DEFAULT_FRAME_RATE,
    });
    if (suppliedTimeline === undefined) {
      return { timeline: expected, source: "derived" };
    }
    if (!suppliedTimeline || suppliedTimeline.schema_version !== "render-timeline/1.2") {
      throw new Error("unsupported supplied render timeline schema");
    }
    if (JSON.stringify(canonicalJson(suppliedTimeline)) !== JSON.stringify(canonicalJson(expected))) {
      throw new Error("supplied render timeline does not match the scene descriptor");
    }
    return {
      timeline: JSON.parse(JSON.stringify(suppliedTimeline)),
      source: "supplied",
    };
  }

  function resolveScenePerformance(descriptor, timeline, suppliedPerformance) {
    if (!PERFORMANCE_RUNTIME?.buildScenePerformance) {
      throw new Error("scene performance runtime is not loaded");
    }
    const expected = PERFORMANCE_RUNTIME.buildScenePerformance(descriptor, timeline);
    if (suppliedPerformance === undefined) {
      return { performance: expected, source: "derived" };
    }
    if (!suppliedPerformance || suppliedPerformance.schema_version !== "scene-performance/1.4") {
      throw new Error("unsupported supplied scene performance schema");
    }
    if (JSON.stringify(canonicalJson(suppliedPerformance)) !== JSON.stringify(canonicalJson(expected))) {
      throw new Error("supplied scene performance does not match the descriptor and timeline");
    }
    return {
      performance: JSON.parse(JSON.stringify(suppliedPerformance)),
      source: "supplied",
    };
  }

  function validatePreviewIntent(intent, descriptor, timeline) {
    if (intent === undefined) return null;
    if (!intent || !PREVIEW_INTENT_SCHEMAS.has(intent.schema_version)) {
      throw new Error("unsupported preview intent schema");
    }
    if (intent.scene_id !== descriptor.scene_id) {
      throw new Error("preview intent scene_id does not match the descriptor");
    }
    if (typeof intent.cue_id !== "string" || !intent.cue_id.trim()) {
      throw new Error("preview intent cue_id is invalid");
    }
    if (!new Set(["cue", "event", "playhead"]).has(intent.selection_kind)) {
      throw new Error("preview intent selection kind is invalid");
    }
    if (intent.selection_kind === "playhead" && intent.schema_version !== "preview-intent/1.1") {
      throw new Error("preview playhead requires preview-intent/1.1");
    }
    if (
      (new Set(["cue", "playhead"]).has(intent.selection_kind)
        && intent.selected_event_id !== null)
      || (intent.selection_kind === "event"
        && (typeof intent.selected_event_id !== "string" || !intent.selected_event_id))
    ) {
      throw new Error("preview intent selected event is invalid");
    }
    const target = intent.target;
    if (
      !target
      || typeof target.event_id !== "string"
      || !target.event_id
      || !Number.isInteger(target.frame)
      || !new Set(["start", "end", "exact"]).has(target.alignment)
      || !PREVIEW_INTENT_RESOLUTIONS.has(target.resolution)
    ) {
      throw new Error("preview intent target is invalid");
    }
    const item = timeline.events.find((event) => event.event_id === target.event_id);
    if (!item || target.frame < item.start_frame || target.frame >= item.end_frame) {
      throw new Error("preview intent target is outside its timeline event");
    }
    if (
      (target.alignment === "start" && target.frame !== item.start_frame)
      || (target.alignment === "end" && target.frame !== item.end_frame - 1)
    ) {
      throw new Error("preview intent alignment does not match its target frame");
    }
    if (
      (target.resolution === "selected-event"
        && (intent.selection_kind !== "event" || target.event_id !== intent.selected_event_id))
      || (target.resolution === "cue-terminal" && intent.selection_kind !== "cue")
      || (new Set(["selected-event", "scene-start"]).has(target.resolution)
        && target.alignment !== "start")
      || (new Set(["cue-terminal", "prior-renderable"]).has(target.resolution)
        && target.alignment !== "end")
      || (target.resolution === "explicit-frame"
        && (intent.selection_kind !== "playhead" || target.alignment !== "exact"))
      || (intent.selection_kind === "playhead" && target.resolution !== "explicit-frame")
    ) {
      throw new Error("preview intent resolution does not match its selection");
    }
    return JSON.parse(JSON.stringify(intent));
  }

  function mount(descriptor, root, options = {}) {
    assertDescriptor(descriptor);
    const stage = root || document.querySelector("#preview-stage");
    if (!stage) throw new Error("Preview stage root was not found.");
    const rendererMode = new URLSearchParams(window.location.search).get("renderer") === "static"
      ? "static" : "realtime";
    const initialActors = Array.isArray(descriptor.initial_actors)
      ? descriptor.initial_actors
      : descriptor.actors;
    const resolvedTimeline = resolveRenderTimeline(descriptor, options.timeline);
    const timeline = resolvedTimeline.timeline;
    const resolvedPerformance = resolveScenePerformance(descriptor, timeline, options.performance);
    const performance = resolvedPerformance.performance;
    const initialIntent = validatePreviewIntent(options.intent, descriptor, timeline);
    const captureMode = options.capture === true;
    if (initialActors.length !== 5) {
      throw new Error("Scene descriptor initial_actors must contain exactly five actor slots.");
    }

    // Compile and validate the candidate before replacing the live session.
    // Once committed, a monotonically increasing generation makes every old
    // controller and delayed callback observably stale.
    stage.__haloCueController?.dispose?.();
    const generation = (Number(stage.__haloCuePreviewGeneration) || 0) + 1;
    stage.__haloCuePreviewGeneration = generation;
    stage.dataset.previewGeneration = String(generation);
    for (const key of [
      "previewCueId",
      "previewSelectionKind",
      "previewSelectedEventId",
      "previewTargetEventId",
      "previewIntentResolution",
    ]) delete stage.dataset[key];
    let disposed = false;
    const isCurrentSession = () => (
      !disposed && stage.__haloCuePreviewGeneration === generation
    );

    installStageScale(stage);
    stage.dataset.renderer = rendererMode;
    const actorLayer = stage.querySelector("#actor-layer");
    const speaker = stage.querySelector("#speaker-name");
    const club = stage.querySelector("#club-name");
    const text = stage.querySelector("#dialogue-text");
    const copy = stage.querySelector("#dialogue-copy");
    const caret = stage.querySelector("#dialogue-caret");
    const progress = stage.querySelector("#event-progress");
    const status = stage.querySelector("#preview-status");
    const advance = stage.querySelector("#advance-button");
    const locationLabel = stage.querySelector("#location-label");
    const speakerLine = stage.querySelector(".speaker-line");
    const dialoguePanel = stage.querySelector(".dialogue-panel");
    const dialogueNext = stage.querySelector("#dialogue-next");
    const stageBackground = stage.querySelector("#stage-background");
    const screenTextLayer = stage.querySelector("#screen-text-layer");
    const screenText = stage.querySelector("#screen-text");
    stage.__haloCueSpineManager?.dispose?.();
    const spineManager = rendererMode === "realtime"
      ? SPINE_RENDERER?.createManager?.() || null
      : null;
    stage.__haloCueSpineManager = spineManager;
    stage.dataset.timelineSource = resolvedTimeline.source;
    stage.dataset.performanceSource = resolvedPerformance.source;
    stage.dataset.capture = captureMode ? "deterministic" : "preview";
    if (locationLabel) {
      locationLabel.hidden = descriptor.presentation?.location_mode === "hidden";
    }
    const actorCatalog = new Map(
      [...descriptor.actors, ...initialActors]
        .filter((actor) => actor && actor.character_id)
        .map((actor) => [actor.character_id, actor]),
    );
    actorLayer.replaceChildren(...descriptor.actors.map((actor) => createActor(actor.slot)));
    const actorElements = new Map(
      [...actorLayer.children].map((element) => [Number(element.dataset.slot), element]),
    );
    const createInitialActorState = (actor) => ({
      ...actor,
      stage_media: actor?.stage_media ? { ...actor.stage_media } : actor?.stage_media,
      presentation: AA.createCharacterState(actor.slot, actor),
    });
    const initialBackground = descriptor.initial_background || descriptor.background || null;
    const state = {
      eventIndex: -1,
      actors: initialActors.map(createInitialActorState),
      typewriter: null,
      typewriterComplete: false,
      typewriterFrame: null,
      motion: null,
      effect: null,
      background: initialBackground ? { ...initialBackground } : null,
      backgroundPending: true,
      backgroundRequestUri: "",
      screenText: "",
      initialMotionPending: true,
      frame: -1,
      intent: null,
      playing: false,
      playbackFrame: null,
    };
    function cloneRuntimeActor(actor) {
      return {
        ...actor,
        stage_media: actor?.stage_media ? { ...actor.stage_media } : actor?.stage_media,
        presentation: {
          ...actor.presentation,
          position: { ...actor.presentation.position },
        },
      };
    }
    function captureSceneSnapshot() {
      return {
        actors: state.actors.map(cloneRuntimeActor),
        background: state.background ? { ...state.background } : null,
        screenText: state.screenText,
      };
    }
    function restoreSceneSnapshot(snapshot) {
      state.actors = snapshot.actors.map(cloneRuntimeActor);
      state.background = snapshot.background ? { ...snapshot.background } : null;
      state.screenText = snapshot.screenText || "";
      state.eventIndex = -1;
      state.typewriter = null;
      state.typewriterComplete = false;
      state.motion = null;
      state.effect = null;
    }
    const seekStateCache = new Map([[0, captureSceneSnapshot()]]);
    stage.dataset.playback = "live";
    stage.dataset.currentFrame = "";
    stage.dataset.currentEvent = "";
    const previewShell = stage.closest(".preview-shell");
    const editorMode = Boolean(previewShell?.classList.contains("has-editor-controls"));
    const assetInspector = document.querySelector("#asset-inspector");
    const inspectorSummary = document.querySelector("#inspector-summary");
    const inspectorList = document.querySelector("#inspector-list");
    const inspectorSelection = document.querySelector("#inspector-selection");
    const inspectorCopyStatus = document.querySelector("#inspector-copy-status");
    const guides = stage.querySelector("#calibration-guides");
    const timelineTransport = document.querySelector("#timeline-transport");
    const timelinePlay = document.querySelector("#timeline-play");
    const timelineScrubber = document.querySelector("#timeline-scrubber");
    const timelinePosition = document.querySelector("#timeline-position");
    const timelineReference = document.querySelector("#timeline-reference");
    let inspectedSlot = null;
    let inspectorRenderSignature = "";

    stage.dataset.mediaReady = "loading";

    function updateMediaReadiness() {
      const pending = [...actorLayer.querySelectorAll(".actor-slot.is-visible .actor-image")]
        .filter((image) => image.src && !(image.complete && image.naturalWidth > 0));
      stage.dataset.mediaReady = pending.length || state.backgroundPending ? "loading" : "ready";
    }

    function inspectorValue(value) {
      if (value === undefined || value === null || value === "") return "-";
      return String(value);
    }

    function appendInspectorField(list, label, value) {
      const row = document.createElement("div");
      const key = document.createElement("dt");
      const valueNode = document.createElement("dd");
      key.textContent = label;
      valueNode.textContent = inspectorValue(value);
      row.append(key, valueNode);
      list.append(row);
    }

    function inspectorActors() {
      return [...new Map(
        [...state.actors, ...actorCatalog.values()]
          .filter((actor) => actor && actor.character_id)
          .map((actor) => [actor.character_id, actor]),
      ).values()].sort((left, right) => Number(left.slot) - Number(right.slot));
    }

    function setInspectedSlot(slot) {
      inspectedSlot = Number.isInteger(slot) ? slot : null;
      actorElements.forEach((element, actorSlot) => {
        element.classList.toggle("is-inspected", actorSlot === inspectedSlot);
      });
      inspectorList?.querySelectorAll("[data-resource-slot]").forEach((row) => {
        row.classList.toggle("is-selected", Number(row.dataset.resourceSlot) === inspectedSlot);
      });
      const selected = inspectorActors().find((actor) => Number(actor.slot) === inspectedSlot);
      if (inspectorSelection) {
        inspectorSelection.textContent = selected
          ? `已选 SLOT ${selected.slot} · ${actorName(selected)}`
          : "未选择槽位";
      }
    }

    function renderResourceInspector() {
      if (!inspectorList) return;
      const actors = inspectorActors();
      const background = state.background || descriptor.background || {};
      const event = state.eventIndex >= 0 ? descriptor.events[state.eventIndex] : null;
      const signature = JSON.stringify({
        eventIndex: state.eventIndex,
        background: background.preview_uri || background.logical_key || background.aa_key || null,
        actors: actors.map((actor) => [
          actor.slot,
          actor.character_id,
          actor.stage_media?.kind,
          actor.stage_media?.bundle_key,
          actor.stage_media?.animation,
          actor.motion_id,
          actor.emoticon_id,
        ]),
      });
      if (signature === inspectorRenderSignature) return;
      inspectorRenderSignature = signature;
      if (inspectorSummary) {
        const eventLabel = event ? `${state.eventIndex + 1}/${descriptor.events.length} · ${event.kind}` : "未开始";
        const backgroundLabel = background.logical_key || background.aa_key || "未解析";
        inspectorSummary.textContent = `事件 ${eventLabel} · 背景 ${backgroundLabel}`;
      }
      inspectorList.replaceChildren();
      actors.forEach((actor) => {
        const row = document.createElement("button");
        const title = document.createElement("strong");
        const kind = document.createElement("span");
        const details = document.createElement("dl");
        const media = actor.stage_media && typeof actor.stage_media === "object"
          ? actor.stage_media : null;
        const resolved = media ? stageMediaFor(actor) : null;
        const transform = media
          ? `scale ${inspectorValue(media.scale)} · x ${inspectorValue(media.offset_x)} · y ${inspectorValue(media.offset_y)}`
          : "-";
        row.type = "button";
        row.className = "asset-resource-row";
        row.dataset.resourceSlot = String(actor.slot);
        title.className = "asset-resource-title";
        title.textContent = `SLOT ${actor.slot} · ${actorName(actor) || "未命名角色"}`;
        kind.className = "asset-resource-kind";
        kind.textContent = media?.kind ? `STAGE ${String(media.kind).toUpperCase()}` : "无正式舞台资源";
        appendInspectorField(details, "character_id", actor.character_id);
        appendInspectorField(details, "resource_id", actor.resource_id);
        appendInspectorField(details, "bundle_key", media?.bundle_key);
        appendInspectorField(details, "animation", media?.animation);
        appendInspectorField(details, "预览路由", resolved?.preview_uri);
        appendInspectorField(details, "变换", transform);
        row.append(title, kind, details);
        row.addEventListener("click", () => setInspectedSlot(Number(actor.slot)));
        inspectorList.append(row);
      });
      if (!actors.length) {
        const empty = document.createElement("p");
        empty.className = "asset-inspector-summary";
        empty.textContent = "当前场景没有已定位的角色资源。";
        inspectorList.append(empty);
      }
      setInspectedSlot(inspectedSlot);
    }

    function resourceMapPayload() {
      const background = state.background || descriptor.background || null;
      return {
        schema_version: descriptor.schema_version,
        scene_id: descriptor.scene_id,
        background: background ? {
          resource_id: background.resource_id,
          logical_key: background.logical_key,
          aa_key: background.aa_key,
          preview_uri: isSafePreviewUri(background.preview_uri) ? background.preview_uri : undefined,
          focus_x: background.focus_x,
          focus_y: background.focus_y,
          zoom: background.zoom,
        } : null,
        actors: inspectorActors().map((actor) => {
          const media = actor.stage_media && typeof actor.stage_media === "object"
            ? actor.stage_media : null;
          const resolved = media ? stageMediaFor(actor) : null;
          return {
            slot: actor.slot,
            character_id: actor.character_id,
            resource_id: actor.resource_id,
            display_name: actor.display_name,
            expression_id: actor.expression_id,
            motion_id: actor.motion_id,
            emoticon_id: actor.emoticon_id,
            stage_media: media ? {
              kind: media.kind,
              bundle_key: media.bundle_key,
              animation: media.animation,
              anchor_x: media.anchor_x,
              anchor_y: media.anchor_y,
              scale: media.scale,
              offset_x: media.offset_x,
              offset_y: media.offset_y,
              preview_uri: resolved?.preview_uri,
            } : null,
          };
        }),
      };
    }

    function installCalibrationGuides() {
      if (!guides) return;
      guides.replaceChildren(...SLOT_X.map((left, index) => {
        const line = document.createElement("span");
        line.className = "calibration-slot-guide";
        line.dataset.slot = `SLOT ${index + 1}`;
        line.style.setProperty("--guide-x", `${left}%`);
        return line;
      }));
      const toggle = document.querySelector("#guides-toggle");
      if (toggle) toggle.onchange = () => {
        if (!isCurrentSession()) return;
        guides.classList.toggle("is-visible", toggle.checked);
        guides.setAttribute("aria-hidden", String(!toggle.checked));
      };
    }

    function installResourceInspector() {
      if (!assetInspector || !editorMode) return;
      const copy = document.querySelector("#copy-resource-map");
      if (copy) copy.onclick = async () => {
        if (!isCurrentSession()) return;
        const payload = JSON.stringify(resourceMapPayload(), null, 2);
        try {
          if (!navigator.clipboard?.writeText) throw new Error("clipboard unavailable");
          await navigator.clipboard.writeText(payload);
          if (!isCurrentSession()) return;
          if (inspectorCopyStatus) inspectorCopyStatus.textContent = "资源定位 JSON 已复制";
        } catch (_error) {
          if (!isCurrentSession()) return;
          if (inspectorCopyStatus) inspectorCopyStatus.textContent = "当前浏览器不允许直接复制";
        }
      };
      renderResourceInspector();
    }

    function updateTimelineTransport() {
      if (!timelineTransport) return;
      const lastFrame = Math.max(0, timeline.total_frames - 1);
      const currentFrame = state.frame >= 0 ? Math.min(lastFrame, state.frame) : 0;
      if (timelineScrubber) {
        timelineScrubber.max = String(lastFrame);
        timelineScrubber.value = String(currentFrame);
      }
      if (timelinePosition) timelinePosition.value = `${currentFrame} / ${lastFrame}`;
      if (timelinePlay) {
        timelinePlay.textContent = state.playing ? "Ⅱ" : "▶";
        timelinePlay.title = state.playing ? "暂停" : "播放";
        timelinePlay.setAttribute("aria-label", timelinePlay.title);
      }
      if (timelineReference) timelineReference.disabled = !descriptor.presentation?.reference_frame;
    }

    function applyPerformanceFrame(frame, mode = "sample") {
      const sample = PERFORMANCE_RUNTIME.sampleScenePerformance(performance, frame, mode);
      stage.style.setProperty("--performance-offset-x", `${sample.stage.offset_x_px}px`);
      stage.style.setProperty("--performance-offset-y", `${sample.stage.offset_y_px}px`);
      stage.dataset.performanceOffsetX = String(sample.stage.offset_x_px);
      stage.dataset.performanceOffsetY = String(sample.stage.offset_y_px);
      stage.dataset.performanceOperations = sample.active_operation_ids.join(" ");
      stage.dataset.performanceMode = sample.mode;
      actorElements.forEach((element) => {
        element.style.opacity = "";
        element.style.setProperty("--performance-character-offset-y", "0px");
        element.style.setProperty("--performance-character-rotation", "0deg");
        element.style.setProperty("--performance-character-scale", "1");
        element.dataset.performanceOpacity = "";
        element.dataset.performanceOffsetY = "0";
        element.dataset.performanceRotation = "0";
        element.dataset.performanceScale = "1";
      });
      for (const character of sample.characters) {
        const actor = state.actors[character.slot - 1];
        const element = actorElements.get(character.slot);
        if (!element || actor?.character_id !== character.character_id) continue;
        if (character.opacity !== null) {
          element.style.opacity = String(character.opacity);
          element.dataset.performanceOpacity = String(character.opacity);
        }
        element.style.setProperty("--performance-character-offset-y", `${character.offset_y_px}px`);
        element.style.setProperty("--performance-character-rotation", `${character.rotation_deg}deg`);
        element.style.setProperty("--performance-character-scale", String(character.scale));
        element.dataset.performanceOffsetY = String(character.offset_y_px);
        element.dataset.performanceRotation = String(character.rotation_deg);
        element.dataset.performanceScale = String(character.scale);
      }
      return sample;
    }

    function installTimelineTransport() {
      if (!editorMode || !timelineTransport) return;
      timelinePlay.onclick = () => { if (state.playing) pause(); else play(); };
      timelineScrubber.oninput = () => seekFrame(Number(timelineScrubber.value));
      timelineReference.onclick = () => seekReference();
      updateTimelineTransport();
    }

    function pulseMotion(element, className) {
      if (!isCurrentSession() || !element) return;
      element.classList.remove(className);
      // Force a new animation cycle when two adjacent events use the same
      // slot.  This is layout-only and does not change the 16:9 stage math.
      void element.offsetWidth;
      element.classList.add(className);
      element.addEventListener("animationend", () => element.classList.remove(className), { once: true });
    }

    function cancelTypewriter() {
      if (state.typewriterFrame !== null) {
        window.cancelAnimationFrame(state.typewriterFrame);
        state.typewriterFrame = null;
      }
    }

    function cancelPlayback() {
      if (state.playbackFrame !== null) {
        window.cancelAnimationFrame(state.playbackFrame);
        state.playbackFrame = null;
      }
      state.playing = false;
      stage.dataset.playback = "paused";
      updateTimelineTransport();
    }

    function startTypewriter() {
      cancelTypewriter();
      if (!state.typewriter) return;
      if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
        copy.textContent = state.typewriter.complete();
        state.typewriterComplete = true;
        caret.hidden = true;
        return;
      }
      const startedAt = window.performance.now();
      const tick = (now) => {
        if (!isCurrentSession() || !state.typewriter) return;
        const frame = state.typewriter.frame(now - startedAt);
        copy.textContent = frame.visibleText;
        if (frame.complete) {
          state.typewriterComplete = true;
          state.typewriterFrame = null;
          caret.hidden = true;
          return;
        }
        state.typewriterFrame = window.requestAnimationFrame(tick);
      };
      state.typewriterFrame = window.requestAnimationFrame(tick);
    }

    function renderActors(activeCharacterId) {
      state.actors.forEach((actor) => {
        const element = actorElements.get(actor.slot);
        const visible = actor.state === "visible" && actor.character_id;
        element.classList.toggle("is-visible", Boolean(visible));
        element.classList.toggle(
          "is-active",
          Boolean(visible && actor.character_id === activeCharacterId),
        );
        element.classList.toggle(
          "is-dimmed",
          Boolean(visible && activeCharacterId && actor.character_id !== activeCharacterId),
        );
        const label = element.querySelector(".actor-name");
        const portrait = element.querySelector(".actor-portrait");
        const image = element.querySelector(".actor-image");
        const canvas = element.querySelector(".actor-canvas");
        const emoticonElement = element.querySelector(".actor-emoticon");
        const emoticonSymbol = element.querySelector(".actor-emoticon-symbol");
        label.textContent = visible ? actorName(actor) : "";
        const motionId = CAPABILITY_RUNTIME.stateId(actor.motion_id);
        const emoticonState = CAPABILITY_RUNTIME.emoticon(actor.emoticon_id);
        element.dataset.motion = visible ? motionId : "";
        element.dataset.emoticon = visible ? (emoticonState?.id || CAPABILITY_RUNTIME.stateId(actor.emoticon_id)) : "";
        element.classList.remove("is-motion-nod", "is-motion-appear");
        if (emoticonElement && emoticonSymbol) {
          emoticonElement.hidden = !visible || !emoticonState;
          emoticonElement.dataset.state = visible ? (emoticonState?.id || "") : "";
          emoticonElement.setAttribute("aria-label", emoticonState?.label || "");
          emoticonSymbol.textContent = emoticonState?.symbol || "";
        }
        const stageMedia = visible ? stageMediaFor(actor) : null;
        const mediaUri = stageMedia?.preview_uri || "";
        const isRealtimeSpine = Boolean(visible && stageMedia?.kind === "spine" && stageMedia?.bundle_key && spineManager);
        image.onload = () => {
          if (!isCurrentSession() || image.dataset.requestUri !== mediaUri) return;
          portrait.classList.toggle("has-image", Boolean(mediaUri));
          updateMediaReadiness();
        };
        image.onerror = () => {
          if (!isCurrentSession() || image.dataset.requestUri !== mediaUri) return;
          portrait.classList.remove("has-image");
          updateMediaReadiness();
        };
        image.dataset.requestUri = mediaUri;
        if (mediaUri) {
          if (image.getAttribute("src") !== mediaUri) image.src = mediaUri;
          if (image.complete && image.naturalWidth > 0) portrait.classList.add("has-image");
        }
        else image.removeAttribute("src");
        image.alt = mediaUri ? actorName(actor) : "";
        if (!mediaUri) portrait.classList.remove("has-image");
        portrait.dataset.mediaKind = stageMedia?.kind || "none";
        portrait.classList.toggle("has-realtime-media", isRealtimeSpine);
        if (isRealtimeSpine) {
          spineManager.attach(canvas, stageMedia, {
            ready: () => {
              if (isCurrentSession() && canvas.closest(".actor-slot") === element) {
                portrait.classList.add("realtime-ready");
                updateMediaReadiness();
              }
            },
            error: () => {
              if (!isCurrentSession()) return;
              portrait.classList.remove("has-realtime-media", "realtime-ready");
              updateMediaReadiness();
            },
          });
        } else {
          spineManager?.detach(canvas);
          portrait.classList.remove("realtime-ready", "has-realtime-media");
        }
        element.dataset.stageMediaKind = actor.stage_media?.kind || "none";
        element.dataset.stageAnimation = stageMedia?.animation || "";
        element.classList.toggle(
          "has-stage-media",
          Boolean(visible && stageMedia),
        );
        element.classList.toggle(
          "stage-media-unavailable",
          Boolean(visible && actor.stage_media && !stageMedia),
        );
        element.style.setProperty("--actor-anchor-x", String(stageMedia?.anchor_x ?? 0.5));
        element.style.setProperty("--actor-anchor-y", String(stageMedia?.anchor_y ?? 1));
        element.style.setProperty("--actor-media-scale", String(stageMedia?.scale ?? DEFAULT_ACTOR_MEDIA_SCALE));
        element.style.setProperty("--actor-offset-x", `${stageMedia?.offset_x ?? 0}px`);
        element.style.setProperty("--actor-offset-y", `${stageMedia?.offset_y ?? 0}px`);
        portrait.dataset.initial = visible ? actorName(actor).slice(0, 1) : "";
        element.style.left = `${actor.presentation.leftPercent}%`;
        element.style.opacity = visible ? String(actor.presentation.opacity) : "0";
        element.style.zIndex = String(actor.presentation.sortingOrder);
        element.style.setProperty("--actor-luminance", String(actor.presentation.luminance));
        element.setAttribute("aria-label", visible ? `Slot ${actor.slot}: ${actorName(actor)}` : `Slot ${actor.slot}: empty`);
      });
      if (editorMode) renderResourceInspector();
      updateMediaReadiness();
    }

    function renderEvent(event, options = {}) {
      cancelTypewriter();
      if (screenTextLayer && screenText) {
        screenText.textContent = state.screenText;
        screenTextLayer.hidden = !state.screenText;
      }
      if (locationLabel && descriptor.location_label) {
        locationLabel.textContent = descriptor.location_label;
      }
      if (!event) {
        speaker.textContent = "";
        club.hidden = true;
        copy.textContent = "Press advance to begin.";
        caret.hidden = true;
        speakerLine.classList.add("is-narration");
        dialoguePanel.classList.add("is-hidden");
        dialogueNext.hidden = true;
        status.textContent = "Ready";
        renderActors(null);
      } else {
        const active = event.character_id || null;
        const activeActor = state.actors.find((actor) => actor.character_id === active);
        const hasSpeaker = Boolean(activeActor && active);
        speaker.textContent = hasSpeaker ? actorName(activeActor) : "";
        const secondaryIdentity = hasSpeaker
          ? actorSecondaryIdentity(activeActor, descriptor)
          : { label: "", kind: "none" };
        club.textContent = secondaryIdentity.label;
        club.dataset.kind = secondaryIdentity.kind;
        club.hidden = !secondaryIdentity.label;
        speakerLine.classList.toggle("is-narration", !hasSpeaker);
        const eventText = EVENT_REGISTRY.isVisualOnly(event.kind)
          ? ""
          : event.text || `${event.kind}.`;
        dialogueNext.hidden = !eventText;
        dialoguePanel.classList.toggle("is-hidden", !eventText);
        state.typewriter = event.kind === "dialogue" ? AA.queueTypewriter(eventText) : null;
        if (state.typewriter && options.sample) {
          const typewriterFrame = state.typewriter.frame(options.sample.localMs);
          copy.textContent = typewriterFrame.visibleText;
          state.typewriterComplete = typewriterFrame.complete;
          caret.hidden = typewriterFrame.complete;
        } else {
          copy.textContent = event.kind === "dialogue" ? "" : eventText;
          caret.hidden = event.kind !== "dialogue";
          state.typewriterComplete = event.kind !== "dialogue";
        }
        status.textContent = event.kind === "dialogue" ? "Dialogue" : event.kind;
        renderActors(active);
        if (!options.suppressMotion && eventText) pulseMotion(dialoguePanel, "is-entering");
        if (!options.suppressMotion && eventText) pulseMotion(speakerLine, "is-revealing");
        if (state.typewriter && !options.sample) startTypewriter();
      }
      if (state.motion && !options.suppressMotion) {
        const motion = state.motion;
        state.motion = null;
        const element = actorElements.get(motion.slot);
        pulseMotion(element, motion.kind === "exit" ? "is-exiting" : "is-entering");
        const capabilityClass = CAPABILITY_RUNTIME.motionClass(motion.capability);
        if (capabilityClass) pulseMotion(element, capabilityClass);
      }
      if (state.effect && !options.suppressMotion) {
        const effect = state.effect;
        state.effect = null;
        if (effect.kind === "halocue.ba:screen-shake") pulseMotion(stage, "is-screen-shaking");
        if (effect.kind === "halocue.ba:hit-effect") pulseMotion(actorElements.get(effect.slot), "is-hit-effect");
        if (effect.kind === "halocue.ba:background-pan") pulseMotion(stageBackground, "is-panning");
      }
      progress.textContent = `${Math.max(0, state.eventIndex + 1)} / ${descriptor.events.length}`;
      advance.disabled = state.eventIndex >= descriptor.events.length - 1;
      updateTimelineTransport();
    }

    function backgroundForEvent(event) {
      if (event && typeof event.background === "object" && event.background !== null) {
        return event.background;
      }
      if (event && event.preview_uri) {
        return { ...(state.background || {}), preview_uri: event.preview_uri };
      }
      return state.background;
    }

    function applyEvent(event, options = {}) {
      if (event.kind === "halocue.ba:screen-text") {
        state.screenText = typeof event.text === "string" ? event.text : "";
      } else {
        state.screenText = "";
      }
      if (event.kind === "enter" && event.slot) {
        const previous = state.actors[event.slot - 1];
        const catalogActor = actorCatalog.get(event.character_id) || {};
        const actorDetails = {};
        for (const key of ["display_name", "dialogue_name", "alias", "club_name", "thumbnail_uri", "thumbnail_source", "thumbnail_kind", "preview_uri", "preview_source", "preview_role", "avatar_key", "spine_key", "stage_media", "expression_id", "motion_id", "emoticon_id", "focus"]) {
          if (event[key] !== undefined) actorDetails[key] = event[key];
          else if (catalogActor[key] !== undefined) actorDetails[key] = catalogActor[key];
        }
        state.actors[event.slot - 1] = {
          ...previous,
          ...actorDetails,
          character_id: event.character_id,
          resource_id: event.resource_id || catalogActor.resource_id || previous.resource_id,
          state: "visible",
          presentation: previous.presentation,
        };
        const character = state.actors[event.slot - 1].presentation;
        AA.setPos(character, AA.slotWorldPosition(event.slot));
        AA.fadeAnimation(character, true).complete();
        AA.setOnTop(character);
        if (options.motion !== false) {
          state.motion = {
            slot: event.slot,
            kind: "enter",
            capability: event.motion_id || state.actors[event.slot - 1].motion_id || "",
          };
        }
      }
      if (event.kind === "dialogue" && event.character_id) {
        const actor = state.actors.find((item) => item.character_id === event.character_id);
        if (actor) {
          for (const key of ["expression_id", "motion_id", "emoticon_id", "focus"]) {
            if (event[key] !== undefined) actor[key] = event[key];
          }
          if (options.motion !== false && event.motion_id) {
            state.motion = { slot: actor.slot, kind: "capability", capability: event.motion_id };
          }
        }
      }
      if (event.kind === "character-motion" && event.slot) {
        const actor = state.actors[event.slot - 1];
        const matchesCharacter = !event.character_id || actor?.character_id === event.character_id;
        if (options.motion !== false && matchesCharacter && event.motion_id) {
          state.motion = { slot: event.slot, kind: "capability", capability: event.motion_id };
        }
      }
      if (event.kind === "exit" && event.slot) {
        AA.hideAnimation(state.actors[event.slot - 1].presentation);
        state.actors[event.slot - 1] = {
          ...state.actors[event.slot - 1], character_id: null, resource_id: null, state: "hidden",
        };
        if (options.motion !== false) state.motion = { slot: event.slot, kind: "exit" };
      }
      if (event.kind === "background") {
        const nextBackground = backgroundForEvent(event);
        if (nextBackground) {
          state.background = nextBackground;
          if (options.loadBackground !== false) loadPreviewBackground(nextBackground);
        }
      }
      if (event.kind === "halocue.ba:background-pan") {
        state.background = {
          ...(state.background || {}),
          pan_x: Number(event.pan_x) || 0,
          pan_y: Number(event.pan_y) || 0,
        };
        if (options.loadBackground !== false) loadPreviewBackground(state.background);
        if (options.motion !== false) state.effect = { kind: "background-pan" };
      }
      if (event.kind === "halocue.ba:screen-shake" && options.motion !== false) {
        state.effect = { kind: "screen-shake" };
      }
      if (event.kind === "halocue.ba:hit-effect" && options.motion !== false && event.slot) {
        state.effect = { kind: "hit-effect", slot: event.slot };
      }
    }

    function applySampledEvent(sample) {
      const event = sample.item?.event;
      if (!event) return;
      if (event.kind === "exit" && event.slot) {
        return;
      }
      applyEvent(event, { motion: false, loadBackground: false });
    }

    function applyActiveOverlays(sample) {
      const screenTextItem = sample.activeItems
        .filter((item) => item.kind === "halocue.ba:screen-text")
        .at(-1);
      state.screenText = typeof screenTextItem?.event?.text === "string"
        ? screenTextItem.event.text
        : "";
    }

    function seekFrame(frame, options = {}) {
      if (!isCurrentSession()) return null;
      if (!options.fromPlayback) cancelPlayback();
      const sample = AA.sampleRenderTimeline(timeline, frame);
      cancelTypewriter();
      const checkpoint = sample.eventIndex < 0
        ? 0
        : Math.max(...[...seekStateCache.keys()].filter((index) => index <= sample.eventIndex));
      restoreSceneSnapshot(seekStateCache.get(checkpoint));
      for (let index = checkpoint; index < sample.eventIndex; index += 1) {
        applyEvent(timeline.events[index].event, { motion: false, loadBackground: false });
        if (!seekStateCache.has(index + 1)) {
          seekStateCache.set(index + 1, captureSceneSnapshot());
        }
      }
      applySampledEvent(sample);
      applyActiveOverlays(sample);
      state.eventIndex = sample.eventIndex;
      state.frame = sample.frame;
      state.motion = null;
      state.effect = null;
      loadPreviewBackground(state.background, { animate: false });
      renderEvent(sample.item?.event || null, { sample, suppressMotion: true });
      applyPerformanceFrame(sample.frame, options.mode || (options.fromPlayback ? "play" : "sample"));
      const spineTimeMs = Number.isFinite(options.spineTimeMs)
        ? Math.max(0, options.spineTimeMs)
        : sample.frame * 1000 / timeline.frame_rate;
      spineManager?.seek(spineTimeMs / 1000);
      stage.dataset.currentFrame = String(sample.frame);
      stage.dataset.currentEvent = sample.item?.event_id || "";
      updateTimelineTransport();
      return sample;
    }

    function seekEvent(eventIndex, options = {}) {
      if (!isCurrentSession()) return null;
      const frame = AA.timelineFrameForEvent(timeline, eventIndex, options.complete !== false);
      return seekFrame(frame, options);
    }

    function seekReference() {
      if (!isCurrentSession()) return null;
      const reference = descriptor.presentation?.reference_frame;
      if (!reference) return null;
      const spineTimeMs = Number(reference.spine_time_ms);
      return seekEvent(reference.target_event_index, {
        complete: reference.dialogue_complete !== false,
        spineTimeMs: Number.isFinite(spineTimeMs) ? spineTimeMs : undefined,
      });
    }

    function applyIntent(intent) {
      if (!isCurrentSession()) return null;
      const resolved = validatePreviewIntent(intent, descriptor, timeline);
      const sample = seekFrame(resolved.target.frame, { mode: "sample" });
      if (!sample) return null;
      state.intent = resolved;
      stage.dataset.previewCueId = resolved.cue_id;
      stage.dataset.previewSelectionKind = resolved.selection_kind;
      stage.dataset.previewSelectedEventId = resolved.selected_event_id || "";
      stage.dataset.previewTargetEventId = resolved.target.event_id;
      stage.dataset.previewIntentResolution = resolved.target.resolution;
      return sample;
    }

    function pause() {
      if (!isCurrentSession()) return;
      cancelPlayback();
      spineManager?.pause();
    }

    function play(options = {}) {
      if (!isCurrentSession() || !timeline.total_frames) return;
      cancelPlayback();
      cancelTypewriter();
      const requested = Number(options.fromFrame);
      const startFrame = Number.isFinite(requested)
        ? Math.max(0, Math.min(timeline.total_frames - 1, Math.floor(requested)))
        : state.frame >= 0 && state.frame < timeline.total_frames - 1 ? state.frame : 0;
      const requestedStop = Number(options.toFrame);
      const stopFrame = Number.isFinite(requestedStop)
        ? Math.max(startFrame, Math.min(timeline.total_frames - 1, Math.floor(requestedStop)))
        : timeline.total_frames - 1;
      const playbackMode = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
        ? "reduced-motion"
        : "play";
      const startedAt = window.performance.now() - startFrame * 1000 / timeline.frame_rate;
      state.playing = true;
      stage.dataset.playback = "playing";
      updateTimelineTransport();
      spineManager?.pause();
      let lastRenderedFrame = -1;
      const tick = (now) => {
        if (!isCurrentSession() || !state.playing) return;
        const nextFrame = Math.floor((now - startedAt) * timeline.frame_rate / 1000);
        if (nextFrame >= stopFrame) {
          seekFrame(stopFrame, { fromPlayback: true, mode: playbackMode });
          cancelPlayback();
          return;
        }
        if (nextFrame !== lastRenderedFrame) {
          seekFrame(nextFrame, { fromPlayback: true, mode: playbackMode });
          lastRenderedFrame = nextFrame;
        }
        state.playbackFrame = window.requestAnimationFrame(tick);
      };
      state.playbackFrame = window.requestAnimationFrame(tick);
    }

    function advanceEvent() {
      if (!isCurrentSession()) return;
      cancelPlayback();
      spineManager?.resume();
      stage.dataset.playback = "live";
      state.frame = -1;
      stage.dataset.currentFrame = "";
      stage.dataset.currentEvent = "";
      updateTimelineTransport();
      if (state.typewriter && state.eventIndex >= 0 && !state.typewriterComplete) {
        cancelTypewriter();
        copy.textContent = state.typewriter.complete();
        state.typewriterComplete = true;
        caret.hidden = true;
        return;
      }
      if (state.eventIndex >= descriptor.events.length - 1) return;
      state.eventIndex += 1;
      const event = descriptor.events[state.eventIndex];
      applyEvent(event);
      state.typewriterComplete = false;
      renderEvent(event);
    }

    function loadPreviewBackground(background, options = {}) {
      if (!isCurrentSession()) return;
      const previewUri = resolvePreviewUri(background && background.preview_uri);
      const focusX = clampUnit(background?.focus_x, 0.5);
      const focusY = clampUnit(background?.focus_y, 0.5);
      stageBackground.style.setProperty(
        "--background-zoom",
        String(clampBackgroundZoom(background?.zoom)),
      );
      stageBackground.style.setProperty(
        "--background-pan-x",
        String(Math.max(-0.2, Math.min(0.2, Number(background?.pan_x) || 0))),
      );
      stageBackground.style.setProperty(
        "--background-pan-y",
        String(Math.max(-0.2, Math.min(0.2, Number(background?.pan_y) || 0))),
      );
      stageBackground.style.backgroundSize = "cover";
      stageBackground.style.backgroundPosition = `${focusX * 100}% ${focusY * 100}%`;
      if (!isSafePreviewUri(previewUri)) {
        state.backgroundRequestUri = "";
        state.backgroundPending = false;
        stageBackground.style.backgroundImage = "";
        delete stageBackground.dataset.previewUri;
        stage.classList.remove("has-background-image");
        updateMediaReadiness();
        return;
      }
      if (stageBackground.dataset.previewUri === previewUri) {
        state.backgroundRequestUri = previewUri;
        state.backgroundPending = false;
        updateMediaReadiness();
        return;
      }
      state.backgroundRequestUri = previewUri;
      state.backgroundPending = true;
      updateMediaReadiness();
      const image = new Image();
      image.addEventListener("load", () => {
        if (!isCurrentSession() || state.backgroundRequestUri !== previewUri) return;
        stageBackground.style.backgroundImage = `url("${previewUri}")`;
        stageBackground.dataset.previewUri = previewUri;
        stage.classList.add("has-background-image");
        stageBackground.classList.remove("is-transitioning");
        if (options.animate !== false) {
          void stageBackground.offsetWidth;
          stageBackground.classList.add("is-transitioning");
        }
        state.backgroundPending = false;
        updateMediaReadiness();
        status.textContent = "Background ready";
      });
      image.addEventListener("error", () => {
        if (!isCurrentSession() || state.backgroundRequestUri !== previewUri) return;
        state.backgroundPending = false;
        updateMediaReadiness();
        status.textContent = "Background placeholder";
      });
      image.src = previewUri;
    }

    function installOverlayControls() {
      const autoToggle = document.querySelector("#auto-toggle");
      const menuToggle = document.querySelector("#menu-toggle");
      const autoButton = stage.querySelector("#auto-button");
      const menuButton = stage.querySelector("#menu-button");
      if (!autoToggle || !menuToggle || !autoButton || !menuButton) return;
      const overlay = descriptor.presentation?.overlay_controls || descriptor.overlay_controls || {};
      autoToggle.checked = Boolean(overlay.auto);
      menuToggle.checked = Boolean(overlay.menu);
      autoButton.classList.toggle("is-enabled", Boolean(overlay.auto_enabled));
      menuButton.classList.toggle("is-enabled", Boolean(overlay.menu_enabled));
      const setLabel = (button, value, fallback) => {
        const label = document.createElement("span");
        label.className = "stage-overlay-label";
        label.textContent = value || fallback;
        button.replaceChildren(label);
      };
      setLabel(autoButton, overlay.auto_label, "AUTO");
      setLabel(menuButton, overlay.menu_label, "MENU");
      autoButton.setAttribute("aria-pressed", String(autoButton.classList.contains("is-enabled")));
      menuButton.setAttribute("aria-pressed", String(menuButton.classList.contains("is-enabled")));
      const apply = () => {
        autoButton.hidden = !autoToggle.checked;
        menuButton.hidden = !menuToggle.checked;
        stage.dataset.overlayAuto = autoToggle.checked ? "on" : "off";
        stage.dataset.overlayMenu = menuToggle.checked ? "on" : "off";
      };
      autoToggle.onchange = apply;
      menuToggle.onchange = apply;
      autoButton.onclick = (event) => {
        event.stopPropagation();
        pulseMotion(autoButton, "is-pressing");
        autoButton.classList.toggle("is-enabled");
        autoButton.setAttribute("aria-pressed", String(autoButton.classList.contains("is-enabled")));
        if (autoButton.classList.contains("is-enabled")) play();
        else pause();
      };
      menuButton.onclick = (event) => {
        event.stopPropagation();
        pulseMotion(menuButton, "is-pressing");
        menuButton.classList.toggle("is-enabled");
        menuButton.setAttribute("aria-pressed", String(menuButton.classList.contains("is-enabled")));
      };
      apply();
    }

    const onStageClick = (event) => {
      const actorTarget = event.target.closest(".actor-slot");
      if (editorMode && actorTarget) {
        event.stopPropagation();
        setInspectedSlot(Number(actorTarget.dataset.slot));
        return;
      }
      if (!event.target.closest("button, select, .runtime-controls, .stage-overlay-controls")) advanceEvent();
    };
    const onKeyDown = (event) => {
      if (event.key === " " || event.key === "ArrowRight") {
        event.preventDefault();
        advanceEvent();
      }
    };
    const onVisibilityChange = () => {
      if (stage.ownerDocument.visibilityState === "hidden" && state.playing) pause();
    };
    advance.addEventListener("click", advanceEvent);
    stage.addEventListener("click", onStageClick);
    stage.ownerDocument.addEventListener("keydown", onKeyDown);
    stage.ownerDocument.addEventListener("visibilitychange", onVisibilityChange);
    loadPreviewBackground(state.background);
    installCalibrationGuides();
    installResourceInspector();
    installOverlayControls();
    installTimelineTransport();
    renderEvent(null);
    stage.style.setProperty("--performance-offset-x", "0px");
    stage.style.setProperty("--performance-offset-y", "0px");
    stage.dataset.performanceOffsetX = "0";
    stage.dataset.performanceOffsetY = "0";
    stage.dataset.performanceOperations = "";
    stage.dataset.performanceMode = "sample";
    const locationTimer = !captureMode
      && locationLabel
      && descriptor.presentation?.location_mode !== "persistent"
      ? window.setTimeout(() => {
        if (isCurrentSession()) locationLabel.classList.add("is-dismissed");
      }, 2600)
      : null;
    // The first visible cast enters as a restrained, staggered GalGame
    // entrance instead of appearing fully formed on the first frame.
    const initialMotionTimers = [];
    const initialMotionFrame = captureMode ? null : window.requestAnimationFrame(() => {
      if (!isCurrentSession() || !state.initialMotionPending) return;
      state.initialMotionPending = false;
      initialActors.filter((actor) => actor && actor.state === "visible")
        .forEach((actor, index) => {
          initialMotionTimers.push(window.setTimeout(
            () => {
              if (isCurrentSession()) pulseMotion(actorElements.get(actor.slot), "is-entering");
            },
            index * 70,
          ));
        });
    });
    if (captureMode) state.initialMotionPending = false;
    const controller = {
      advance: advanceEvent,
      applyIntent,
      generation,
      isCurrent: isCurrentSession,
      pause,
      play,
      seekEvent,
      seekFrame,
      seekReference,
      scene_id: descriptor.scene_id,
      state,
      timeline,
      performance,
      dispose() {
        if (disposed) return;
        const ownsStage = stage.__haloCuePreviewGeneration === generation;
        disposed = true;
        if (ownsStage) {
          stage.__haloCuePreviewGeneration = generation + 1;
          stage.dataset.previewGeneration = String(generation + 1);
        }
        cancelPlayback();
        cancelTypewriter();
        state.initialMotionPending = false;
        if (initialMotionFrame !== null) window.cancelAnimationFrame(initialMotionFrame);
        initialMotionTimers.forEach((timer) => window.clearTimeout(timer));
        if (locationTimer !== null) window.clearTimeout(locationTimer);
        advance.removeEventListener("click", advanceEvent);
        stage.removeEventListener("click", onStageClick);
        stage.ownerDocument.removeEventListener("keydown", onKeyDown);
        stage.ownerDocument.removeEventListener("visibilitychange", onVisibilityChange);
        if (timelinePlay) timelinePlay.onclick = null;
        if (timelineScrubber) timelineScrubber.oninput = null;
        if (timelineReference) timelineReference.onclick = null;
        const guidesToggle = document.querySelector("#guides-toggle");
        const copyResourceMap = document.querySelector("#copy-resource-map");
        if (guidesToggle) guidesToggle.onchange = null;
        if (copyResourceMap) copyResourceMap.onclick = null;
        stage.__haloCueStageScaleObserver?.disconnect?.();
        if (stage.__haloCueStageScaleHandler) {
          window.removeEventListener("resize", stage.__haloCueStageScaleHandler);
          stage.__haloCueStageScaleHandler = null;
        }
        spineManager?.dispose();
        if (stage.__haloCueSpineManager === spineManager) stage.__haloCueSpineManager = null;
        if (stage.__haloCueController === controller) stage.__haloCueController = null;
      },
    };
    stage.__haloCueController = controller;
    if (initialIntent) applyIntent(initialIntent);
    return controller;
  }

  window.HaloCueScenePreview = { mount, SUPPORTED_SCHEMA };

  function showError(exception) {
    const error = document.querySelector("#preview-error");
    if (!error) return;
    error.hidden = false;
    error.textContent = exception.message;
  }

  function boot(demoDescriptor) {
    try {
      const params = new URLSearchParams(window.location.search);
      const editorControls = params.get("editor") === "1";
      const embedded = params.get("embedded") === "1";
      const captureMode = params.get("capture") === "1";
      const previewShell = document.querySelector(".preview-shell");
      previewShell?.classList.toggle("has-editor-controls", editorControls);
      previewShell?.classList.toggle("is-embedded", embedded);
      previewShell?.classList.toggle("is-capture", captureMode);
      const controller = mount(demoDescriptor, null, {
        capture: captureMode,
        timeline: window.HALO_CUE_RENDER_TIMELINE,
        performance: window.HALO_CUE_SCENE_PERFORMANCE,
      });
      const stage = document.querySelector("#preview-stage");
      const fontSelect = document.querySelector("#font-select");
      document.querySelector("#scene-title").textContent = "预览";
      fontSelect?.addEventListener("change", () => { stage.dataset.font = fontSelect.value; });
      if (params.get("reference") === "1") controller.seekReference();
      else if (/^\d+$/.test(params.get("frame") || "")) controller.seekFrame(Number(params.get("frame")));
      if (params.get("play") === "1") controller.play({ fromFrame: Math.max(0, controller.state.frame) });
      window.HaloCueScenePreview.controller = controller;
    } catch (exception) {
      showError(exception);
    }
  }

  const demoDescriptor = window.HALO_CUE_SCENE_DESCRIPTOR;
  if (demoDescriptor) {
    boot(demoDescriptor);
  } else if (window.location.protocol !== "file:") {
    const requestedDescriptor = new URLSearchParams(window.location.search).get("descriptor") || "example";
    const descriptorName = /^[a-z0-9-]+$/i.test(requestedDescriptor)
      ? `./${requestedDescriptor}.scene-descriptor.json`
      : "./example.scene-descriptor.json";
    fetch(descriptorName)
      .then((response) => {
        if (!response.ok) throw new Error("Could not load the synthetic scene descriptor.");
        return response.json();
      })
      .then(boot)
      .catch(showError);
  }
}());
