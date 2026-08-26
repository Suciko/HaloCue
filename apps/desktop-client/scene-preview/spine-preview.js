(function () {
  "use strict";

  const runtimePromises = new Map();
  const bundlePromises = new Map();
  const players = new Set();
  let animationFrame = null;
  let lastFrameTime = 0;

  function documentIsVisible() {
    return typeof document === "undefined" || document.visibilityState !== "hidden";
  }

  function hasTickingPlayers() {
    return documentIsVisible() && [...players].some((player) => !player.paused && !player.disposed);
  }

  function stopLoop() {
    if (animationFrame !== null) window.cancelAnimationFrame(animationFrame);
    animationFrame = null;
    lastFrameTime = 0;
  }

  function runtimeSource(family) {
    const configured = String(window.HALO_CUE_SPINE_RUNTIME_BASE || "/js/");
    const base = configured.endsWith("/") ? configured : `${configured}/`;
    return `${base}${family === "4.2" ? "spine-webgl-4.2.119.min.js" : "spine-webgl-3.8.95.js"}`;
  }

  function runtimeReady(family) {
    return family === "4.2"
      ? Boolean(window.spine?.Skeleton && window.spine?.webgl === undefined)
      : Boolean(window.spine?.webgl?.SkeletonRenderer || window.spine?.webgl?.AssetManager);
  }

  function ensureRuntime(family) {
    const normalized = String(family || "4.2").startsWith("3.8") ? "3.8" : "4.2";
    if (runtimeReady(normalized)) return Promise.resolve(window.spine);
    if (runtimePromises.has(normalized)) return runtimePromises.get(normalized);
    const promise = new Promise((resolve, reject) => {
      const source = runtimeSource(normalized);
      const existing = document.querySelector(`script[data-halo-cue-spine-runtime="${normalized}"]`);
      if (existing) {
        existing.addEventListener("load", () => resolve(window.spine), { once: true });
        existing.addEventListener("error", () => reject(new Error(`Spine ${normalized} runtime failed to load`)), { once: true });
        return;
      }
      const script = document.createElement("script");
      script.src = source;
      script.async = true;
      script.dataset.haloCueSpineRuntime = normalized;
      script.onload = () => runtimeReady(normalized)
        ? resolve(window.spine)
        : reject(new Error(`Spine ${normalized} runtime exposed no WebGL API`));
      script.onerror = () => reject(new Error(`Spine ${normalized} runtime failed to load`));
      document.head.append(script);
    });
    runtimePromises.set(normalized, promise);
    return promise;
  }

  function validBundlePayload(payload) {
    return payload && payload.ok !== false
      && typeof payload.spine_family === "string"
      && typeof payload.skeleton === "string"
      && typeof payload.atlas === "string"
      && Array.isArray(payload.textures)
      && payload.textures.every((page) => page && typeof page.name === "string" && typeof page.uri === "string");
  }

  function loadBundle(key) {
    const normalized = String(key || "").trim();
    if (!normalized || !/^[A-Za-z0-9_.-]+$/.test(normalized)) {
      return Promise.reject(new Error("Invalid Spine bundle key"));
    }
    if (bundlePromises.has(normalized)) return bundlePromises.get(normalized);
    const promise = fetch(`/api/resources/stage/spine/data?key=${encodeURIComponent(normalized)}`, {
      credentials: "same-origin",
      cache: "no-store",
    }).then(async (response) => {
      let payload = null;
      try { payload = await response.json(); } catch (_) {}
      if (!response.ok || !validBundlePayload(payload)) {
        throw new Error(payload?.e || "Spine bundle is unavailable");
      }
      return payload;
    });
    bundlePromises.set(normalized, promise);
    return promise;
  }

  function animationName(media, animationNames) {
    const requested = String(media?.animation || "00_default").trim() || "00_default";
    const candidates = requested === "00_default" ? ["00", "00_default"] : [requested];
    const match = candidates.find((name) => animationNames.includes(name));
    return match || animationNames[0] || null;
  }

  function setNeutralTint(skeleton) {
    if (skeleton.color?.set) skeleton.color.set(1, 1, 1, 1);
    for (const slot of skeleton.slots || []) {
      if (slot.color?.set) slot.color.set(1, 1, 1, 1);
      if (slot.darkColor?.set) slot.darkColor.set(1, 1, 1, 1);
      const attachment = slot.getAttachment?.();
      if (attachment?.color?.set) attachment.color.set(1, 1, 1, 1);
    }
  }

  class SpinePlayer {
    constructor(canvas, media, onReady, onError) {
      this.canvas = canvas;
      this.media = media;
      this.onReady = onReady;
      this.onError = onError;
      this.disposed = false;
      this.ready = false;
      this.paused = false;
      this.pendingSeekSeconds = null;
      this.lastAnimation = "";
      this.bounds = null;
      this.canvasResolution = { width: 0, height: 0 };
      this.resources = null;
      this.startedAt = 0;
      this._load();
    }

    async _load() {
      try {
        const bundle = await loadBundle(this.media.bundle_key);
        if (this.disposed) return;
        await ensureRuntime(bundle.spine_family);
        if (this.disposed) return;
        const spineApi = window.spine;
        const is42 = bundle.spine_family === "4.2";
        const webgl = is42 ? spineApi : spineApi.webgl;
        const Shader = is42 ? spineApi.Shader : spineApi.webgl.Shader;
        const gl = this.canvas.getContext("webgl", {
          alpha: true,
          premultipliedAlpha: false,
          preserveDrawingBuffer: false,
          antialias: true,
        });
        if (!gl) throw new Error("WebGL is unavailable");
        const assets = new webgl.AssetManager(gl);
        assets.setRawDataURI("skeleton.skel", bundle.skeleton);
        assets.setRawDataURI("skeleton.atlas", bundle.atlas);
        for (const page of bundle.textures) assets.setRawDataURI(page.name, page.uri);
        assets.loadBinary("skeleton.skel");
        gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, Boolean(bundle.pma));
        assets.loadTextureAtlas("skeleton.atlas");
        await new Promise((resolve, reject) => {
          const started = Date.now();
          const poll = () => {
            if (this.disposed) return reject(new Error("Spine player disposed"));
            if (assets.isLoadingComplete()) {
              const errors = assets.getErrors?.();
              if (errors && Object.keys(errors).length) reject(new Error(JSON.stringify(errors)));
              else resolve();
            } else if (Date.now() - started > 60000) reject(new Error("Spine assets timed out"));
            else window.requestAnimationFrame(poll);
          };
          poll();
        });
        const atlas = assets.get("skeleton.atlas");
        const loader = new spineApi.AtlasAttachmentLoader(atlas);
        const binary = new spineApi.SkeletonBinary(loader);
        const skeletonData = binary.readSkeletonData(assets.get("skeleton.skel"));
        const skeleton = new spineApi.Skeleton(skeletonData);
        const state = new spineApi.AnimationState(new spineApi.AnimationStateData(skeletonData));
        const shader = Shader.newTwoColoredTextured(gl);
        const batcher = new webgl.PolygonBatcher(gl);
        const renderer = new webgl.SkeletonRenderer(gl);
        const mvp = new webgl.Matrix4();
        const animationNames = skeletonData.animations.map((item) => item.name);
        this.resources = { bundle, spineApi, gl, assets, skeleton, skeletonData, state, shader, batcher, renderer, mvp, Shader, animationNames, pma: Boolean(bundle.pma) };
        this.selectAnimation();
        this.resizeAndMeasure();
        this.ready = true;
        players.add(this);
        if (this.pendingSeekSeconds !== null) this.seek(this.pendingSeekSeconds);
        else this.render();
        startLoop();
        this.onReady?.(this);
      } catch (error) {
        if (!this.disposed) this.onError?.(error);
      }
    }

    selectAnimation() {
      if (!this.resources) return;
      const name = animationName(this.media, this.resources.animationNames);
      if (!name) return;
      const { skeleton, state, spineApi } = this.resources;
      skeleton.setToSetupPose();
      state.clearTracks();
      state.setAnimation(0, name, true);
      state.update(0);
      state.apply(skeleton);
      try { skeleton.updateWorldTransform(spineApi.Physics.update); }
      catch (_) { skeleton.updateWorldTransform(); }
      this.lastAnimation = name;
    }

    resizeAndMeasure() {
      const { skeleton, spineApi } = this.resources;
      try { skeleton.updateWorldTransform(spineApi.Physics.update); }
      catch (_) { skeleton.updateWorldTransform(); }
      const offset = new spineApi.Vector2();
      const size = new spineApi.Vector2();
      skeleton.getBounds(offset, size, []);
      if (!(size.x > 0 && size.y > 0)) throw new Error("Spine skeleton has empty bounds");
      this.bounds = { x: offset.x, y: offset.y, width: size.x, height: size.y };
      this.applyCanvasResolution(size.y / size.x, 2048);
    }

    applyCanvasResolution(ratio, maxSide) {
      const safeRatio = Number.isFinite(ratio) && ratio > 0 ? ratio : 1;
      const boundedMax = Math.max(512, Math.min(2048, Math.round(maxSide)));
      let width = safeRatio >= 1 ? Math.round(boundedMax / safeRatio) : boundedMax;
      let height = safeRatio >= 1 ? boundedMax : Math.round(boundedMax * safeRatio);
      if (Math.min(width, height) < 256) {
        if (safeRatio >= 1) {
          width = 256;
          height = Math.round(width * safeRatio);
        } else {
          height = 256;
          width = Math.round(height / safeRatio);
        }
      }
      const overage = Math.max(width, height) / 2048;
      if (overage > 1) {
        width = Math.max(256, Math.round(width / overage));
        height = Math.max(256, Math.round(height / overage));
      }
      if (this.canvasResolution.width === width && this.canvasResolution.height === height) return;
      this.canvas.width = width;
      this.canvas.height = height;
      this.canvasResolution = { width, height };
    }

    syncCanvasResolution() {
      if (!this.bounds) return;
      // A 1.75x CSS-pixel sample is visually stable at the reference frame
      // while avoiding a full 2048px render for small previews. High-DPI
      // displays are capped at the same deterministic 2048px upper bound.
      const cssPixels = Math.max(this.canvas.clientWidth, this.canvas.clientHeight, 1);
      const dpr = Math.min(Number(window.devicePixelRatio) || 1, 2);
      const maxSide = Math.max(512, Math.min(2048, Math.ceil(cssPixels * dpr * 1.75)));
      this.applyCanvasResolution(this.bounds.height / this.bounds.width, maxSide);
    }

    tick(delta) {
      if (!this.ready || this.disposed || this.paused || !this.resources) return;
      this.resources.state.update(Math.min(Math.max(delta, 0), 0.064));
      this.resources.state.apply(this.resources.skeleton);
      try { this.resources.skeleton.updateWorldTransform(this.resources.spineApi.Physics.update); }
      catch (_) { this.resources.skeleton.updateWorldTransform(); }
      this.render();
    }

    setPaused(paused) {
      this.paused = Boolean(paused);
      if (!this.paused) startLoop();
    }

    seek(seconds) {
      const next = Math.max(0, Number(seconds) || 0);
      this.pendingSeekSeconds = next;
      if (!this.ready || !this.resources) return;
      this.selectAnimation();
      if (next > 0) this.resources.state.update(next);
      this.resources.state.apply(this.resources.skeleton);
      try { this.resources.skeleton.updateWorldTransform(this.resources.spineApi.Physics.update); }
      catch (_) { this.resources.skeleton.updateWorldTransform(); }
      this.render();
    }

    render() {
      if (!this.ready || !this.resources || !this.bounds) return;
      this.syncCanvasResolution();
      const { gl, skeleton, shader, batcher, renderer, mvp, Shader } = this.resources;
      const { x, y, width: boundsWidth, height: boundsHeight } = this.bounds;
      const pad = 1;
      const worldWidth = boundsWidth * pad;
      const worldHeight = boundsHeight * pad;
      mvp.ortho2d(x - (worldWidth - boundsWidth) / 2, y - (worldHeight - boundsHeight) / 2, worldWidth, worldHeight);
      gl.viewport(0, 0, this.canvas.width, this.canvas.height);
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      shader.bind();
      shader.setUniformi(Shader.SAMPLER, 0);
      shader.setUniform4x4f(Shader.MVP_MATRIX, mvp.values);
      batcher.begin(shader);
      renderer.premultipliedAlpha = this.resources.pma;
      renderer.draw(batcher, skeleton);
      batcher.end();
      shader.unbind();
    }

    dispose() {
      if (this.disposed) return;
      this.disposed = true;
      players.delete(this);
      if (!players.size) stopLoop();
      if (!this.resources) return;
      try { this.resources.assets.dispose(); } catch (_) {}
      try { this.resources.shader.dispose(); } catch (_) {}
      try { this.resources.batcher.dispose(); } catch (_) {}
      this.resources = null;
    }
  }

  function startLoop() {
    if (animationFrame !== null || !hasTickingPlayers()) return;
    const tick = (now) => {
      animationFrame = null;
      const delta = lastFrameTime ? (now - lastFrameTime) / 1000 : 0;
      lastFrameTime = now;
      for (const player of players) player.tick(delta);
      if (hasTickingPlayers()) animationFrame = window.requestAnimationFrame(tick);
      else lastFrameTime = 0;
    };
    animationFrame = window.requestAnimationFrame(tick);
  }

  function createManager() {
    const attached = new Map();
    let paused = false;
    let seekSeconds = null;
    return {
      attach(canvas, media, callbacks = {}) {
        if (!canvas || !media?.bundle_key) return null;
        const existing = attached.get(canvas);
        const identity = `${media.bundle_key}|${media.animation || "00_default"}`;
        if (existing?.identity === identity) {
          existing.player.setPaused(paused);
          return existing.player;
        }
        existing?.player.dispose();
        const entry = { identity, player: null };
        entry.player = new SpinePlayer(
          canvas,
          media,
          (player) => { if (attached.get(canvas) === entry) callbacks.ready?.(player); },
          (error) => { if (attached.get(canvas) === entry) callbacks.error?.(error); },
        );
        entry.player.setPaused(paused);
        if (seekSeconds !== null) entry.player.seek(seekSeconds);
        attached.set(canvas, entry);
        return entry.player;
      },
      pause() {
        paused = true;
        for (const entry of attached.values()) entry.player.setPaused(true);
      },
      resume() {
        paused = false;
        seekSeconds = null;
        for (const entry of attached.values()) entry.player.setPaused(false);
        startLoop();
      },
      seek(seconds) {
        seekSeconds = Math.max(0, Number(seconds) || 0);
        paused = true;
        for (const entry of attached.values()) {
          entry.player.setPaused(true);
          entry.player.seek(seekSeconds);
        }
      },
      detach(canvas) {
        const entry = attached.get(canvas);
        if (!entry) return;
        entry.player.dispose();
        attached.delete(canvas);
      },
      dispose() {
        for (const entry of attached.values()) entry.player.dispose();
        attached.clear();
      },
    };
  }

  if (typeof document !== "undefined") {
    document.addEventListener("visibilitychange", () => {
      if (documentIsVisible()) startLoop();
      else stopLoop();
    });
  }

  window.HaloCueSpineRenderer = { createManager };
}());
