/* Local Spine WebGL face renderer. The matching runtime is loaded per bundle. */
(function (exports) {
  'use strict';

  var SPINE_38_RUNTIME = '/js/spine-webgl-3.8.95.js';
  var SPINE_42_RUNTIME = '/js/spine-webgl-4.2.119.min.js';

  function FaceWebGlRenderer() {
    this.canvas = document.getElementById('faceWebglCanvas');
    this.gl = this.canvas && this.canvas.getContext('webgl', {
      alpha: true, premultipliedAlpha: false, preserveDrawingBuffer: true
    });
    this.runtimeSrc = '';
  }

  FaceWebGlRenderer.prototype.available = function () {
    return Boolean(this.gl && window.spine);
  };

  FaceWebGlRenderer.prototype.ensureRuntime = function (version) {
    var majorMinor = String(version || '').startsWith('4.2') ? '4.2.119' : '3.8.95';
    var src = majorMinor === '4.2.119' ? SPINE_42_RUNTIME : SPINE_38_RUNTIME;
    if (this.runtimeSrc === src && this.available()) return Promise.resolve();
    this.runtimeSrc = src;
    return new Promise(function (resolve, reject) {
      var script = document.createElement('script');
      script.src = src;
      script.onload = resolve;
      script.onerror = function () { reject(new Error('Spine WebGL runtime unavailable: ' + src)); };
      document.head.appendChild(script);
    });
  };

  FaceWebGlRenderer.prototype.upload = async function (item, faceId, blob) {
    var query = '?aa_key=' + encodeURIComponent(item.aa_key || '')
      + '&sha256=' + encodeURIComponent(item.sha256 || '')
      + '&face_id=' + encodeURIComponent(faceId);
    var response = await fetch('/api/assets/faces/rendered' + query, {
      method: 'POST', headers: {'Content-Type': 'image/png'}, body: blob
    });
    var payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(payload.e || payload.code || 'face_upload_failed');
    return payload;
  };

  FaceWebGlRenderer.prototype.render = async function (item, report) {
    var query = '?aa_key=' + encodeURIComponent(item.aa_key) + '&sha256=' + encodeURIComponent(item.sha256 || '');
    var bundle = await exports.Api.request('/api/assets/faces/spine/bundle' + query);
    await this.ensureRuntime(bundle.spine_version);
    if (!this.available()) throw new Error('WebGL or Spine runtime unavailable');
    var gl = this.gl, canvas = this.canvas;
    var is42 = String(bundle.spine_version || '').startsWith('4.2');
    var webgl = is42 ? spine : spine.webgl;
    var Shader = is42 ? spine.Shader : spine.webgl.Shader;
    var shader = Shader.newTwoColoredTextured(gl);
    var batcher = new webgl.PolygonBatcher(gl);
    var renderer = new webgl.SkeletonRenderer(gl);
    var mvp = new webgl.Matrix4();
    var assets = new webgl.AssetManager(gl);
    assets.setRawDataURI('skeleton.skel', bundle.skel_url);
    assets.setRawDataURI('skeleton.atlas', bundle.atlas_url);
    var texturePages = bundle.texture_pages || [{name: bundle.texture_name, url: bundle.texture_url}];
    texturePages.forEach(function (page) { assets.setRawDataURI(String(page.name || ''), page.url); });
    assets.loadBinary('skeleton.skel');
    var atlasText = await (await fetch(bundle.atlas_url)).text();
    var atlasPma = /(?:^|\n)\s*pma:\s*true\s*(?:\n|$)/i.test(atlasText);
    // The shipped 3.8 AA atlases are straight-alpha files whose transparent
    // edge RGB needs upload-time premultiplication to avoid white fringes.
    // Spine 4.2 exports declare their intended PMA mode in the atlas.
    var pma = is42 ? atlasPma : true;
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, pma);
    assets.loadTextureAtlas('skeleton.atlas');
    await new Promise(function (resolve, reject) {
      var started = Date.now();
      (function waitForAssets() {
        if (assets.isLoadingComplete()) {
          var errors = assets.getErrors();
          if (errors && Object.keys(errors).length) reject(new Error(JSON.stringify(errors)));
          else resolve();
          return;
        }
        if (Date.now() - started > 30000) reject(new Error('Spine assets timed out'));
        else requestAnimationFrame(waitForAssets);
      })();
    });
    var atlas = assets.get('skeleton.atlas');
    var skeletonData = new spine.SkeletonBinary(new spine.AtlasAttachmentLoader(atlas))
      .readSkeletonData(assets.get('skeleton.skel'));
    var skeleton = new spine.Skeleton(skeletonData);
    var state = new spine.AnimationState(new spine.AnimationStateData(skeletonData));
    var offset = new spine.Vector2(), size = new spine.Vector2();
    var renderOne = function (faceId) {
      skeleton.setToSetupPose(); state.clearTracks();
      if (faceId !== '00') state.setAnimation(0, faceId, false);
      state.update(0); state.apply(skeleton);
      try { skeleton.updateWorldTransform(spine.Physics.update); }
      catch (_) { skeleton.updateWorldTransform(); }
      skeleton.getBounds(offset, size, []);
      var scale = Math.max(size.x / canvas.width, size.y / canvas.height) * 1.05 || 1;
      var width = canvas.width * scale, height = canvas.height * scale;
      mvp.ortho2d(offset.x + size.x / 2 - width / 2, offset.y + size.y / 2 - height / 2, width, height);
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
      shader.bind(); shader.setUniformi(Shader.SAMPLER, 0);
      shader.setUniform4x4f(Shader.MVP_MATRIX, mvp.values);
      batcher.begin(shader); renderer.premultipliedAlpha = pma;
      renderer.draw(batcher, skeleton); batcher.end(); shader.unbind(); gl.finish();
    };
    var finalResult = null;
    for (var index = 0; index < bundle.face_ids.length; index += 1) {
      var faceId = String(bundle.face_ids[index]);
      report(index, bundle.face_ids.length, faceId);
      renderOne(faceId);
      var blob = await new Promise(function (resolve, reject) {
        canvas.toBlob(function (value) { value ? resolve(value) : reject(new Error('Canvas PNG export failed')); }, 'image/png');
      });
      finalResult = await this.upload(item, faceId, blob);
    }
    assets.removeAll();
    report(bundle.face_ids.length, bundle.face_ids.length, 'complete');
    return finalResult;
  };

  exports.FaceWebGlRenderer = FaceWebGlRenderer;
})(window);
