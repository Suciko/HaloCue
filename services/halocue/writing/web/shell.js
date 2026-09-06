(() => {
  const storageKey = 'halocue-writing.panels.v4';
  const root = document.getElementById('app');
  if (!root) return;

  // The manuscript is the primary desktop surface. The Agent stays one click
  // away and opens when an Agent action is chosen.
  let panels = { tree: false, inspector: true };
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) || '{}');
    panels = {
      tree: Object.prototype.hasOwnProperty.call(saved, 'tree') ? Boolean(saved.tree) : panels.tree,
      inspector: Object.prototype.hasOwnProperty.call(saved, 'inspector') ? Boolean(saved.inspector) : panels.inspector,
    };
  } catch (_) {
    // Invalid display preferences must not prevent the workbench from opening.
  }

  const save = () => localStorage.setItem(storageKey, JSON.stringify(panels));

  function setPanel(side, collapsed) {
    if (!(side in panels)) return;
    panels[side] = Boolean(collapsed);
    save();
    apply();
  }

  function apply() {
    const desktop = window.matchMedia('(min-width: 761px)').matches;
    root.classList.toggle('tree-collapsed', panels.tree);
    root.classList.toggle('inspector-collapsed', panels.inspector);
    const focusMode = panels.tree && panels.inspector;
    root.classList.toggle('focus-mode', focusMode);

    for (const [side, selector] of Object.entries({ tree: '.tree-panel', inspector: '.inspector' })) {
      const panel = root.querySelector(selector);
      if (!panel) continue;
      const hidden = desktop && Boolean(panels[side]);
      panel.inert = hidden;
      if (hidden) panel.setAttribute('aria-hidden', 'true');
      else panel.removeAttribute('aria-hidden');
    }

    document.querySelectorAll('[data-panel-toggle]').forEach(button => {
      const side = button.dataset.panelToggle;
      const collapsed = Boolean(panels[side]);
      button.setAttribute('aria-pressed', String(collapsed));
      button.textContent = side === 'tree'
        ? (collapsed ? '显示章节' : '隐藏章节')
        : (collapsed ? '显示 Agent' : '隐藏 Agent');
      button.title = side === 'tree'
        ? (collapsed ? '展开章节与场景' : '收起章节与场景')
        : (collapsed ? '展开场景 Agent' : '收起场景 Agent');
    });

    const focusButton = document.querySelector('[data-focus-toggle]');
    if (focusButton) {
      focusButton.setAttribute('aria-pressed', String(focusMode));
      focusButton.textContent = focusMode ? '退出专注' : '专注';
      focusButton.title = focusMode ? '恢复章节栏与 Agent' : '同时收起两侧栏';
    }
  }

  document.addEventListener('click', event => {
    const button = event.target.closest('button');
    if (!button) return;
    if (button.dataset.panelToggle !== undefined) {
      event.preventDefault();
      const side = button.dataset.panelToggle;
      if (!(side in panels)) return;
      panels[side] = !panels[side];
      save();
      apply();
      return;
    }
    if (button.dataset.focusToggle !== undefined) {
      event.preventDefault();
      const next = !(panels.tree && panels.inspector);
      panels = { tree: next, inspector: next };
      save();
      apply();
      return;
    }
    if (button.dataset.inspector !== undefined && window.matchMedia('(min-width: 761px)').matches) {
      setPanel('inspector', false);
    }
  }, true);

  window.addEventListener('resize', apply);

  window.HaloCuePanels = Object.freeze({
    open: side => setPanel(side, false),
    collapse: side => setPanel(side, true),
  });

  apply();
})();
