(function () {
  "use strict";

  const AA = window.HaloCueAARuntime;
  const SLOT_X = AA.SLOT_LEFT_PERCENT;
  const SUPPORTED_SCHEMA = "scene-descriptor/1.0";
  const STAGE_MEDIA_KINDS = new Set(["portrait", "spine", "spine-frame"]);

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
    if (actor.display_name) return actor.display_name;
    if (!actor.character_id) return "";
    const value = actor.character_id.split("/").pop() || actor.character_id;
    return value.charAt(0).toUpperCase() + value.slice(1);
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
      scale: Math.max(0.5, Math.min(1.6, Number(media.scale) || 1)),
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
    const stageBackground = stage.querySelector("#stage-background");
    const initialActors = Array.isArray(descriptor.initial_actors)
      ? descriptor.initial_actors
      : descriptor.actors;
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
      background: descriptor.initial_background || descriptor.background || null,
    };

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
        };
        image.onerror = () => {
          if (image.dataset.requestUri !== mediaUri) return;
          portrait.classList.remove("has-image");
        };
        image.dataset.requestUri = mediaUri;
        if (mediaUri) image.src = mediaUri;
        else image.removeAttribute("src");
        image.alt = mediaUri ? actorName(actor) : "";
        portrait.classList.remove("has-image");
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
        element.style.setProperty("--actor-media-scale", String(stageMedia?.scale ?? 1));
        portrait.dataset.initial = visible ? actorName(actor).slice(0, 1) : "";
        element.style.left = `${actor.presentation.leftPercent}%`;
        element.style.opacity = visible ? String(actor.presentation.opacity) : "0";
        element.style.zIndex = String(actor.presentation.sortingOrder);
        element.style.setProperty("--actor-luminance", String(actor.presentation.luminance));
        element.setAttribute("aria-label", visible ? `Slot ${actor.slot}: ${actorName(actor)}` : `Slot ${actor.slot}: empty`);
      });
    }

    function renderEvent(event) {
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
        status.textContent = "Ready";
        renderActors(null);
      } else {
        const active = event.character_id || null;
        const activeActor = state.actors.find((actor) => actor.character_id === active);
        const hasSpeaker = Boolean(activeActor && active);
        speaker.textContent = hasSpeaker ? actorName(activeActor) : "";
        club.textContent = hasSpeaker
          ? (activeActor.club_name || descriptor.club_name || "StoryForge")
          : "";
        club.hidden = !hasSpeaker;
        speakerLine.classList.toggle("is-narration", !hasSpeaker);
        const eventText = event.text || (event.kind === "background" ? "" : `${event.kind}.`);
        dialoguePanel.classList.toggle("is-hidden", !eventText);
        copy.textContent = eventText;
        caret.hidden = event.kind !== "dialogue";
        state.typewriter = event.kind === "dialogue" ? AA.queueTypewriter(eventText) : null;
        status.textContent = event.kind === "dialogue" ? "Dialogue" : event.kind;
        renderActors(active);
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
        for (const key of ["display_name", "thumbnail_uri", "thumbnail_source", "thumbnail_kind", "preview_uri", "preview_source", "preview_role", "avatar_key", "spine_key", "stage_media"]) {
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
      }
      if (event.kind === "exit" && event.slot) {
        AA.hideAnimation(state.actors[event.slot - 1].presentation);
        state.actors[event.slot - 1] = {
          ...state.actors[event.slot - 1], character_id: null, resource_id: null, state: "hidden",
        };
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
        copy.textContent = state.typewriter.complete();
        state.typewriterComplete = true;
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
        stageBackground.style.backgroundImage = "";
        stage.classList.remove("has-background-image");
        return;
      }
      const image = new Image();
      image.addEventListener("load", () => {
        stageBackground.style.backgroundImage = `url("${previewUri}")`;
        stage.classList.add("has-background-image");
        status.textContent = "Background ready";
      });
      image.addEventListener("error", () => {
        status.textContent = "Background placeholder";
      });
      image.src = previewUri;
    }

    advance.addEventListener("click", advanceEvent);
    stage.addEventListener("click", (event) => {
      if (!event.target.closest("button, select, .runtime-controls")) advanceEvent();
    });
    stage.ownerDocument.addEventListener("keydown", (event) => {
      if (event.key === " " || event.key === "ArrowRight") {
        event.preventDefault();
        advanceEvent();
      }
    });
    loadPreviewBackground(state.background);
    renderEvent(null);
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
    const descriptorName = new URLSearchParams(window.location.search).get("descriptor") === "local-aa"
      ? "./local-aa.scene-descriptor.json"
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
