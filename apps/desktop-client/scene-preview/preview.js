(function () {
  "use strict";

  const AA = window.HaloCueAARuntime;
  const SLOT_X = AA.SLOT_LEFT_PERCENT;
  const SUPPORTED_SCHEMA = "scene-descriptor/1.0";
  const AUTO_INITIAL_DELAY_MS = 700;
  const AUTO_EVENT_DELAY_MS = 900;
  const AUTO_DIALOGUE_BUFFER_MS = 650;

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
      && (uri.startsWith("./") || uri.startsWith("/api/resources/preview?"))
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
    const autoButton = stage.querySelector("#auto-button");
    const menuButton = stage.querySelector("#menu-button");
    const stageBackground = stage.querySelector("#stage-background");
    const actorCatalog = new Map(
      descriptor.actors
        .filter((actor) => actor && actor.character_id)
        .map((actor) => [actor.character_id, actor]),
    );
    actorLayer.replaceChildren(...descriptor.actors.map((actor) => createActor(actor.slot)));
    const actorElements = new Map(
      [...actorLayer.children].map((element) => [Number(element.dataset.slot), element]),
    );
    const state = {
      eventIndex: -1,
      actors: descriptor.actors.map((actor) => ({
        ...actor,
        presentation: AA.createCharacterState(actor.slot, actor),
      })),
      typewriter: null,
      typewriterComplete: false,
      background: descriptor.background || null,
      autoEnabled: false,
      autoTimer: null,
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
        const previewUri = resolvePreviewUri(actor.preview_uri);
        image.src = visible && previewUri ? previewUri : "";
        image.alt = visible ? actorName(actor) : "";
        portrait.classList.toggle("has-image", Boolean(visible && previewUri));
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
        speaker.textContent = "Scene";
        club.hidden = true;
        copy.textContent = "Press advance to begin.";
        caret.hidden = true;
        status.textContent = "Ready";
        renderActors(null);
      } else {
        const active = event.character_id || null;
        const activeActor = state.actors.find((actor) => actor.character_id === active);
        speaker.textContent = activeActor ? actorName(activeActor) : "Scene";
        club.textContent = active ? "StoryForge" : "";
        club.hidden = !active;
        const eventText = event.text || (event.kind === "background" ? "Background changed." : `${event.kind}.`);
        copy.textContent = eventText;
        caret.hidden = event.kind !== "dialogue";
        state.typewriter = event.kind === "dialogue" ? AA.queueTypewriter(eventText) : null;
        status.textContent = event.kind === "dialogue" ? "Dialogue" : event.kind;
        renderActors(active);
      }
      progress.textContent = `${Math.max(0, state.eventIndex + 1)} / ${descriptor.events.length}`;
      advance.disabled = state.eventIndex >= descriptor.events.length - 1;
    }

    function clearAutoTimer() {
      if (state.autoTimer !== null) {
        window.clearTimeout(state.autoTimer);
        state.autoTimer = null;
      }
    }

    function scheduleAutoAdvance(delayMs) {
      clearAutoTimer();
      if (!state.autoEnabled) return;
      const delay = Number.isFinite(delayMs) ? Math.max(0, delayMs) : AUTO_EVENT_DELAY_MS;
      state.autoTimer = window.setTimeout(() => {
        state.autoTimer = null;
        advanceEvent();
        if (state.autoEnabled && state.eventIndex < descriptor.events.length - 1) {
          scheduleAutoAdvance();
        } else if (state.autoEnabled) {
          state.autoEnabled = false;
          stage.classList.remove("auto-enabled");
          autoButton?.setAttribute("aria-pressed", "false");
          status.textContent = "Complete";
        }
      }, delay);
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
        for (const key of ["display_name", "preview_uri", "preview_source", "avatar_key", "spine_key"]) {
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
      if (state.autoEnabled && state.autoTimer !== null) clearAutoTimer();
      if (state.typewriter && state.eventIndex >= 0 && !state.typewriterComplete) {
        copy.textContent = state.typewriter.complete();
        state.typewriterComplete = true;
        scheduleAutoAdvance(AUTO_EVENT_DELAY_MS);
        return;
      }
      if (state.eventIndex >= descriptor.events.length - 1) return;
      state.eventIndex += 1;
      const event = descriptor.events[state.eventIndex];
      applyEvent(event);
      state.typewriterComplete = false;
      renderEvent(event);
      if (state.autoEnabled) {
        const delay = event.kind === "dialogue" && state.typewriter
          ? state.typewriter.durationMs + AUTO_DIALOGUE_BUFFER_MS
          : AUTO_EVENT_DELAY_MS;
        scheduleAutoAdvance(delay);
      }
    }

    function loadPreviewBackground(background) {
      const previewUri = resolvePreviewUri(background && background.preview_uri);
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
    autoButton?.addEventListener("click", () => {
      state.autoEnabled = !state.autoEnabled;
      stage.classList.toggle("auto-enabled", state.autoEnabled);
      autoButton.setAttribute("aria-pressed", String(state.autoEnabled));
      status.textContent = state.autoEnabled ? "Auto" : "Manual";
      if (state.autoEnabled) scheduleAutoAdvance(state.eventIndex < 0 ? AUTO_INITIAL_DELAY_MS : undefined);
      else clearAutoTimer();
    });
    menuButton?.addEventListener("click", () => {
      stage.classList.toggle("menu-open");
      status.textContent = stage.classList.contains("menu-open") ? "Menu" : "Ready";
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
      dispose() { clearAutoTimer(); },
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
    fetch("./example.scene-descriptor.json")
      .then((response) => {
        if (!response.ok) throw new Error("Could not load the synthetic scene descriptor.");
        return response.json();
      })
      .then(boot)
      .catch(showError);
  }
}());
