(() => {
  const storageKey = 'halocue-writing.panels.v7';
  const root = document.getElementById('app');
  if (!root) return;
  const widthKey = 'halocue-writing.panel-widths.v1';
  const defaults = { works: 224, writing: 236, inspector: 340 };
  const widths = { ...defaults };
  try {
    const saved = JSON.parse(localStorage.getItem(widthKey) || '{}');
    for (const key of Object.keys(widths)) {
      if (Number.isFinite(saved[key])) widths[key] = Math.max(key === 'inspector' ? 240 : 180, Math.min(480, saved[key]));
    }
  } catch (_) { /* Invalid preferences fall back to the initial widths. */ }
  const saveWidths = () => { try { localStorage.setItem(widthKey, JSON.stringify(widths)); } catch (_) {} };
  const surface = () => root.dataset.surface === 'writing' ? 'writing' : 'works';
  const hasInspector = () => root.dataset.surface === 'writing'
    || (root.dataset.surface === 'works' && root.classList.contains('work-agent-stage'));
  const widthName = side => side === 'tree' ? surface() : 'inspector';
  let displayed = { tree: 308, inspector: 340 };

  let narrowPanel = null;
  let worksInspectorRequested = false;
  let focusRestore = null;
  function visiblePanels() {
    const effective = { ...panels };
    if (root.dataset.surface === 'works' && !worksInspectorRequested) effective.inspector = true;
    if (root.dataset.surface === 'works' && root.clientWidth < 1280 && root.clientWidth > 760) {
      // Adaptive presentation does not overwrite saved user preferences.
      if (narrowPanel === 'inspector' && !panels.inspector) effective.tree = true;
      else effective.inspector = true;
      if (root.clientWidth < 980 && narrowPanel !== 'tree') effective.tree = true;
    }
    if (root.dataset.surface === 'writing' && root.clientWidth < 1200 && root.clientWidth > 760) {
      // One supporting rail at a time keeps the manuscript readable.
      if (narrowPanel === 'inspector' && !panels.inspector) effective.tree = true;
      else effective.inspector = true;
    }
    return effective;
  }

  function applyWidths() {
    const active = ['works', 'writing'].includes(root.dataset.surface) && !root.classList.contains('production-mode');
    const visible = visiblePanels();
    const right = active && hasInspector() && !visible.inspector;
    const left = active && !visible.tree;
    const navWidth = root.querySelector('.primary-nav')?.getBoundingClientRect().width || 64;
    const centerMin = surface() === 'works' ? Math.min(560, root.clientWidth - navWidth - 24 - (right ? 240 : left ? 180 : 0)) : 240;
    const budget = Math.max(0, root.clientWidth - navWidth - 24 - centerMin);
    let leftWidth = left ? (surface() === 'works' ? Math.min(widths.works, 260) : widths.writing) : 0;
    let rightWidth = right ? (surface() === 'works' ? Math.min(widths.inspector, 300) : widths.inspector) : 0;
    if (leftWidth + rightWidth > budget) {
      const excess = leftWidth + rightWidth - budget;
      const shrinkLeft = Math.min(excess, Math.max(0, leftWidth - 180));
      leftWidth -= shrinkLeft;
      rightWidth = Math.max(0, Math.min(rightWidth, budget - leftWidth));
    }
    displayed = { tree: leftWidth, inspector: rightWidth };
    root.style.setProperty('--hc-left-width', `${leftWidth}px`);
    root.style.setProperty('--hc-right-width', `${rightWidth}px`);
    root.classList.toggle('has-panel-inspector', active && hasInspector());
    for (const handle of root.querySelectorAll('[data-panel-resize]')) {
      const side = handle.dataset.panelResize;
      const enabled = active && (side === 'tree' ? left : right);
      handle.hidden = !enabled;
      const { min, max } = limits(side);
      handle.setAttribute('aria-valuemin', String(min));
      handle.setAttribute('aria-valuemax', String(max));
      handle.setAttribute('aria-valuenow', String(Math.round(displayed[side])));
      handle.setAttribute('aria-valuetext', `${Math.round(displayed[side])} 像素`);
      if (side === 'tree') handle.setAttribute('aria-controls', surface() === 'works' ? 'worksPanel' : 'treePanel');
    }
  }

  function limits(side) {
    const min = side === 'tree' ? 180 : 240;
    const other = displayed[side === 'tree' ? 'inspector' : 'tree'];
    const navWidth = root.querySelector('.primary-nav')?.getBoundingClientRect().width || 64;
    const works = surface() === 'works';
    const designMax = works ? (side === 'tree' ? 260 : 300) : 480;
    const centerMin = works ? 560 : 240;
    return { min, max: Math.max(min, Math.min(designMax, root.clientWidth - navWidth - 24 - centerMin - other)) };
  }

  function resizePanel(side, value) {
    const { min, max } = limits(side);
    widths[widthName(side)] = Math.round(Math.max(min, Math.min(max, value)));
    applyWidths();
  }

  // Keep both writing rails available; compact desktop widths show one at a time.
  let panels = { tree: false, inspector: false };
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) || '{}');
    panels = {
      tree: Object.prototype.hasOwnProperty.call(saved, 'tree') ? Boolean(saved.tree) : panels.tree,
      inspector: Object.prototype.hasOwnProperty.call(saved, 'inspector') ? Boolean(saved.inspector) : panels.inspector,
    };
  } catch (_) {
    // Invalid display preferences must not prevent the workbench from opening.
  }

  const save = () => { try { localStorage.setItem(storageKey, JSON.stringify(panels)); } catch (_) {} };

  function setPanel(side, collapsed) {
    if (!(side in panels)) return;
    focusRestore = null;
    panels[side] = Boolean(collapsed);
    if (side === 'inspector' && root.dataset.surface === 'works') worksInspectorRequested = !collapsed;
    if (!collapsed) narrowPanel = side;
    save();
    apply();
  }

  function apply() {
    const visible = visiblePanels();
    const desktop = window.matchMedia('(min-width: 761px)').matches;
    root.classList.toggle('tree-collapsed', visible.tree);
    root.classList.toggle('inspector-collapsed', visible.inspector);
    const focusMode = visible.tree && visible.inspector;
    root.classList.toggle('focus-mode', focusMode);
    applyWidths();
    const worksPanel = root.querySelector('#worksPanel');
    if (worksPanel) worksPanel.inert = root.dataset.surface !== 'works' || (desktop && visible.tree);

    for (const [side, selector] of Object.entries({ tree: '.tree-panel', inspector: '.inspector' })) {
      const panel = root.querySelector(selector);
      if (!panel) continue;
      const inspectorSurface = hasInspector();
      const hidden = (side === 'inspector' && !inspectorSurface)
        || (side === 'tree' && root.dataset.surface !== 'writing')
        || (desktop && Boolean(visible[side]));
      panel.inert = hidden;
      if (hidden) panel.setAttribute('aria-hidden', 'true');
      else panel.removeAttribute('aria-hidden');
    }

    document.querySelectorAll('[data-panel-toggle]').forEach(button => {
      const side = button.dataset.panelToggle;
      const collapsed = Boolean(visible[side]);
      const railName = side === 'tree'
        ? (surface() === 'works' ? '对话栏' : '章节与场景栏')
        : (root.dataset.surface === 'works' ? '创作导演栏' : '场景 Agent');
      const label = `${collapsed ? '展开' : '收起'}${railName}`;
      button.setAttribute('aria-pressed', String(collapsed));
      if (button.classList.contains('panel-divider-toggle')) {
        const glyph = button.querySelector('[aria-hidden="true"]');
        if (glyph) glyph.textContent = side === 'tree'
          ? (collapsed ? '›' : '‹')
          : (collapsed ? '‹' : '›');
      } else if (!button.hasAttribute("data-panel-icon")) {
        button.textContent = label;
      }
      button.setAttribute('aria-expanded', String(!collapsed));
      button.setAttribute('aria-label', label);
      button.title = label;
    });

    const focusButton = document.querySelector('[data-focus-toggle]');
    if (focusButton) {
      focusButton.setAttribute('aria-pressed', String(focusMode));
      focusButton.textContent = focusMode ? '退出专注' : '专注';
      focusButton.title = focusMode ? '恢复专注前的侧栏布局' : '同时收起目录与 Agent，只保留正文';
    }
  }

  document.addEventListener('click', event => {
    const button = event.target.closest('button');
    if (!button) return;
    if (button.dataset.panelToggle !== undefined) {
      event.preventDefault();
      const side = button.dataset.panelToggle;
      if (!(side in panels)) return;
      setPanel(side, !visiblePanels()[side]);
      if (side === 'tree' && visiblePanels().tree && button.closest('#worksPanel')) {
        root.querySelector('.agent-sidebar-toggle')?.focus({ preventScroll: true });
      }
      return;
    }
    if (button.dataset.focusToggle !== undefined) {
      event.preventDefault();
      const visible=visiblePanels();
      if(visible.tree&&visible.inspector){
        panels=focusRestore?.panels || {tree:false,inspector:false};
        narrowPanel=focusRestore?.narrowPanel || null;
        focusRestore=null;
      }else{
        focusRestore={panels:{...panels},narrowPanel};
        panels={tree:true,inspector:true};
      }
      save();
      apply();
      return;
    }
    if (button.dataset.inspector !== undefined && window.matchMedia('(min-width: 761px)').matches) {
      setPanel('inspector', false);
    }
  }, true);

  window.addEventListener('resize', apply);

  let drag = null;
  root.addEventListener('pointerdown', event => {
    const handle = event.target.closest('[data-panel-resize]');
    if (!handle || event.button !== 0 || !window.matchMedia('(min-width: 761px)').matches) return;
    const side = handle.dataset.panelResize;
    drag = { handle, side, pointer: event.pointerId, startX: event.clientX, width: displayed[side], surface: surface() };
    handle.setPointerCapture(event.pointerId);
    root.classList.add('panel-resizing');
    event.preventDefault();
  });
  root.addEventListener('pointermove', event => {
    if (!drag || event.pointerId !== drag.pointer || drag.surface !== surface()) return;
    resizePanel(drag.side, drag.width + (event.clientX - drag.startX) * (drag.side === 'tree' ? 1 : -1));
  });
  function finishResize(event) {
    if (!drag || event.pointerId !== drag.pointer) return;
    const { handle, pointer } = drag;
    drag = null;
    root.classList.remove('panel-resizing');
    if (handle.hasPointerCapture(pointer)) handle.releasePointerCapture(pointer);
    saveWidths();
  }
  root.addEventListener('pointerup', finishResize);
  root.addEventListener('pointercancel', finishResize);
  root.addEventListener('lostpointercapture', finishResize);
  root.addEventListener('keydown', event => {
    const handle = event.target.closest('[data-panel-resize]');
    if (!handle || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const side = handle.dataset.panelResize;
    const { min, max } = limits(side);
    const delta = (event.key === 'ArrowRight' ? 20 : -20) * (side === 'tree' ? 1 : -1);
    resizePanel(side, event.key === 'Home' ? min : event.key === 'End' ? max : displayed[side] + delta);
    saveWidths();
  });
  root.addEventListener('dblclick', event => {
    const handle = event.target.closest('[data-panel-resize]');
    if (!handle) return;
    resizePanel(handle.dataset.panelResize, defaults[widthName(handle.dataset.panelResize)]);
    saveWidths();
  });

  window.HaloCuePanels = Object.freeze({
    apply,
    open: side => setPanel(side, false),
    collapse: side => setPanel(side, true),
  });

  apply();
})();
