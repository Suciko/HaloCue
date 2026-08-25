(function () {
  "use strict";

  const AA = window.HaloCueAARuntime;
  const SLOT_X = AA.SLOT_LEFT_PERCENT;
  const SUPPORTED_SCHEMA = "scene-descriptor/1.0";

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
      && uri.startsWith("./")
      && !uri.includes("..")
      && !uri.includes("\\")
      && !/^[a-z]+:/i.test(uri);
  }

  function createActor(slot) {
    const element = document.createElement("article");
    element.className = "actor-slot";
    element.dataset.slot = String(slot);
    element.style.left = `${SLOT_X[slot - 1]}%`;
    element.innerHTML = '<div class="actor-portrait" aria-hidden="true"></div><div class="actor-name"></div>';
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
    const fontSelect = document.querySelector("#font-select");
    const fontCycleButton = stage.querySelector("#font-cycle-button");
    const fullscreenButton = stage.querySelector("#fullscreen-button");
    const closeButton = stage.querySelector("#close-button");
    const stageBackground = stage.querySelector("#stage-background");
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
        label.textContent = visible ? actorName(actor) : "";
        portrait.textContent = visible ? actorName(actor).slice(0, 1) : "";
        element.style.left = `${actor.presentation.leftPercent}%`;
        element.style.opacity = visible ? String(actor.presentation.opacity) : "0";
        element.style.zIndex = String(actor.presentation.sortingOrder);
        element.style.setProperty("--actor-luminance", String(actor.presentation.luminance));
        element.setAttribute("aria-label", visible ? `Slot ${actor.slot}: ${actorName(actor)}` : `Slot ${actor.slot}: empty`);
      });
    }

    function renderEvent(event) {
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

    function applyEvent(event) {
      if (event.kind === "enter" && event.slot) {
        state.actors[event.slot - 1] = {
          ...state.actors[event.slot - 1],
          character_id: event.character_id,
          resource_id: event.resource_id || state.actors[event.slot - 1].resource_id,
          state: "visible",
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

    function loadPreviewBackground() {
      const previewUri = descriptor.background && descriptor.background.preview_uri;
      if (!isSafePreviewUri(previewUri)) return;
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
    fontCycleButton.addEventListener("click", () => {
      const values = ["harmony", "noto", "nowar"];
      const next = values[(values.indexOf(fontSelect.value) + 1) % values.length];
      fontSelect.value = next;
      fontSelect.dispatchEvent(new Event("change", { bubbles: true }));
    });
    fullscreenButton.addEventListener("click", async () => {
      if (!document.fullscreenElement) {
        await stage.requestFullscreen?.();
      } else {
        await document.exitFullscreen?.();
      }
    });
    closeButton.addEventListener("click", () => {
      window.parent?.postMessage({ type: "halocue:close-preview" }, "*");
      status.textContent = "Preview close requested";
    });
    stage.ownerDocument.addEventListener("keydown", (event) => {
      if (event.key === " " || event.key === "ArrowRight") {
        event.preventDefault();
        advanceEvent();
      }
    });
    loadPreviewBackground();
    renderEvent(null);
    return { advance: advanceEvent, state };
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
      const select = document.querySelector("#font-select");
      const stage = document.querySelector("#preview-stage");
      document.querySelector("#scene-title").textContent = "预览";
      select.addEventListener("change", () => stage.dataset.font = select.value);
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
