(function () {
  "use strict";

  const AA = window.HaloCueAARuntime;
  const SLOT_X = AA.SLOT_LEFT_PERCENT;
  const SUPPORTED_SCHEMA = "scene-descriptor/1.0";
  const STAGE_MEDIA_KINDS = new Set(["portrait", "spine", "spine-frame"]);
  const DEFAULT_ACTOR_MEDIA_SCALE = 1.6;

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

  function clampStageOffset(value) {
    const number = Number(value);
    return Number.isFinite(number) ? Math.max(-1024, Math.min(1024, number)) : 0;
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
      scale: Math.max(0.5, Math.min(2, Number(media.scale) || DEFAULT_ACTOR_MEDIA_SCALE)),
      offset_x: clampStageOffset(media.offset_x),
      offset_y: clampStageOffset(media.offset_y),
    };
  }

  function createActor(slot) {
    const element = document.createElement("article");
    element.className = "actor-slot";
    element.dataset.slot = String(slot);
    element.style.left = `${SLOT_X[slot - 1]}%`;
    element.innerHTML = '<div class="actor-portrait" aria-hidden="true"><img class="actor-image" alt="" /></div><div class="actor-name"></div>';
    return element;
  }

  function mount(descriptor, root) {
    assertDescriptor(descriptor);
    const stage = root || document.querySelector("#preview-stage");
    if (!stage) throw new Error("Preview stage root was not found.");
    installStageScale(stage);
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
    const initialActors = Array.isArray(descriptor.initial_actors)
      ? descriptor.initial_actors
      : descriptor.actors;
    if (locationLabel) {
      locationLabel.hidden = descriptor.presentation?.location_mode === "hidden";
    }
    if (initialActors.length !== 5) {
      throw new Error("Scene descriptor initial_actors must contain exactly five actor slots.");
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
    const state = {
      eventIndex: -1,
      actors: initialActors.map((actor) => ({
        ...actor,
        presentation: AA.createCharacterState(actor.slot, actor),
      })),
      typewriter: null,
      typewriterComplete: false,
      typewriterFrame: null,
      motion: null,
      background: descriptor.initial_background || descriptor.background || null,
      backgroundPending: true,
      initialMotionPending: true,
    };

    stage.dataset.mediaReady = "loading";

    function updateMediaReadiness() {
      const pending = [...actorLayer.querySelectorAll(".actor-slot.is-visible .actor-image")]
        .filter((image) => image.src && !(image.complete && image.naturalWidth > 0));
      stage.dataset.mediaReady = pending.length || state.backgroundPending ? "loading" : "ready";
    }

    function pulseMotion(element, className) {
      if (!element) return;
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
        if (!state.typewriter) return;
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
        label.textContent = visible ? actorName(actor) : "";
        const stageMedia = visible ? stageMediaFor(actor) : null;
        const mediaUri = stageMedia?.preview_uri || "";
        image.onload = () => {
          if (image.dataset.requestUri !== mediaUri) return;
          portrait.classList.toggle("has-image", Boolean(mediaUri));
          updateMediaReadiness();
        };
        image.onerror = () => {
          if (image.dataset.requestUri !== mediaUri) return;
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
        element.dataset.stageMediaKind = actor.stage_media?.kind || "none";
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
      updateMediaReadiness();
    }

    function renderEvent(event) {
      cancelTypewriter();
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
        const eventText = event.text || (event.kind === "background" ? "" : `${event.kind}.`);
        dialogueNext.hidden = !eventText;
        dialoguePanel.classList.toggle("is-hidden", !eventText);
        copy.textContent = event.kind === "dialogue" ? "" : eventText;
        caret.hidden = event.kind !== "dialogue";
        state.typewriter = event.kind === "dialogue" ? AA.queueTypewriter(eventText) : null;
        state.typewriterComplete = event.kind !== "dialogue";
        status.textContent = event.kind === "dialogue" ? "Dialogue" : event.kind;
        renderActors(active);
        if (eventText) pulseMotion(dialoguePanel, "is-entering");
        if (eventText) pulseMotion(speakerLine, "is-revealing");
        if (state.typewriter) startTypewriter();
      }
      if (state.motion) {
        const motion = state.motion;
        state.motion = null;
        pulseMotion(actorElements.get(motion.slot), motion.kind === "exit" ? "is-exiting" : "is-entering");
      }
      progress.textContent = `${Math.max(0, state.eventIndex + 1)} / ${descriptor.events.length}`;
      advance.disabled = state.eventIndex >= descriptor.events.length - 1;
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

    function applyEvent(event) {
      if (event.kind === "enter" && event.slot) {
        const previous = state.actors[event.slot - 1];
        const catalogActor = actorCatalog.get(event.character_id) || {};
        const actorDetails = {};
        for (const key of ["display_name", "dialogue_name", "alias", "club_name", "thumbnail_uri", "thumbnail_source", "thumbnail_kind", "preview_uri", "preview_source", "preview_role", "avatar_key", "spine_key", "stage_media"]) {
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
        state.motion = { slot: event.slot, kind: "enter" };
      }
      if (event.kind === "exit" && event.slot) {
        AA.hideAnimation(state.actors[event.slot - 1].presentation);
        state.actors[event.slot - 1] = {
          ...state.actors[event.slot - 1], character_id: null, resource_id: null, state: "hidden",
        };
        state.motion = { slot: event.slot, kind: "exit" };
      }
      if (event.kind === "background") {
        const nextBackground = backgroundForEvent(event);
        if (nextBackground) {
          state.background = nextBackground;
          loadPreviewBackground(nextBackground);
        }
      }
    }

    function advanceEvent() {
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

    function loadPreviewBackground(background) {
      const previewUri = resolvePreviewUri(background && background.preview_uri);
      const focusX = clampUnit(background?.focus_x, 0.5);
      const focusY = clampUnit(background?.focus_y, 0.5);
      stageBackground.style.backgroundSize = "cover";
      stageBackground.style.backgroundPosition = `${focusX * 100}% ${focusY * 100}%`;
      if (!isSafePreviewUri(previewUri)) {
        state.backgroundPending = false;
        stageBackground.style.backgroundImage = "";
        stage.classList.remove("has-background-image");
        updateMediaReadiness();
        return;
      }
      state.backgroundPending = true;
      updateMediaReadiness();
      const image = new Image();
      image.addEventListener("load", () => {
        stageBackground.style.backgroundImage = `url("${previewUri}")`;
        stage.classList.add("has-background-image");
        stageBackground.classList.remove("is-transitioning");
        void stageBackground.offsetWidth;
        stageBackground.classList.add("is-transitioning");
        state.backgroundPending = false;
        updateMediaReadiness();
        status.textContent = "Background ready";
      });
      image.addEventListener("error", () => {
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
      autoButton.textContent = overlay.auto_label || "AUTO";
      menuButton.textContent = overlay.menu_label || "MENU";
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
      };
      menuButton.onclick = (event) => {
        event.stopPropagation();
        pulseMotion(menuButton, "is-pressing");
        menuButton.classList.toggle("is-enabled");
        menuButton.setAttribute("aria-pressed", String(menuButton.classList.contains("is-enabled")));
      };
      apply();
    }

    advance.addEventListener("click", advanceEvent);
    stage.addEventListener("click", (event) => {
      if (!event.target.closest("button, select, .runtime-controls, .stage-overlay-controls")) advanceEvent();
    });
    stage.ownerDocument.addEventListener("keydown", (event) => {
      if (event.key === " " || event.key === "ArrowRight") {
        event.preventDefault();
        advanceEvent();
      }
    });
    loadPreviewBackground(state.background);
    installOverlayControls();
    renderEvent(null);
    if (locationLabel && descriptor.presentation?.location_mode !== "persistent") {
      window.setTimeout(() => locationLabel.classList.add("is-dismissed"), 2600);
    }
    // The first visible cast enters as a restrained, staggered GalGame
    // entrance instead of appearing fully formed on the first frame.
    window.requestAnimationFrame(() => {
      if (!state.initialMotionPending) return;
      state.initialMotionPending = false;
      initialActors.filter((actor) => actor && actor.state === "visible")
        .forEach((actor, index) => {
          window.setTimeout(() => pulseMotion(actorElements.get(actor.slot), "is-entering"), index * 70);
        });
    });
    return {
      advance: advanceEvent,
      state,
    };
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
      const editorControls = new URLSearchParams(window.location.search).get("editor") === "1";
      document.querySelector(".preview-shell")?.classList.toggle("has-editor-controls", editorControls);
      const controller = mount(demoDescriptor);
      const stage = document.querySelector("#preview-stage");
      const fontSelect = document.querySelector("#font-select");
      document.querySelector("#scene-title").textContent = "预览";
      fontSelect?.addEventListener("change", () => { stage.dataset.font = fontSelect.value; });
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
