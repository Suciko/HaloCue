(function () {
  'use strict';

  const embedded = window.parent !== window && new URLSearchParams(location.search).get('embed') === '1';
  if (embedded) {
    document.body.classList.add('help-embedded');
    // Embedded help is part of the current workspace, not a second theme preference.
    try {
      const parentRoot = window.parent.document.documentElement;
      const syncTheme = function () {
        const dark = parentRoot.dataset.theme === 'dark';
        document.body.classList.toggle('dark', dark);
        document.documentElement.style.colorScheme = dark ? 'dark' : 'light';
        const parentStyle = window.parent.getComputedStyle(parentRoot);
        const tokens = {'--bg':'--paper','--panel':'--surface','--text':'--ink','--muted':'--muted','--line':'--line','--accent':'--accent','--accent-soft':'--accent-soft','--shadow':'--shadow'};
        Object.entries(tokens).forEach(function ([local, source]) {
          const value = parentStyle.getPropertyValue(source).trim();
          if (value) document.body.style.setProperty(local, value);
        });
        const font = parentStyle.getPropertyValue('--font-ui').trim();
        if (font) document.body.style.fontFamily = font;
      };
      const observer = new MutationObserver(syncTheme);
      const watch = function () { observer.observe(parentRoot, {attributes:true, attributeFilter:['data-theme','data-appearance-palette','data-appearance-contrast','data-appearance-scale','style']}); syncTheme(); };
      watch();
      window.addEventListener('pagehide', function () { observer.disconnect(); });
      window.addEventListener('pageshow', watch);
    } catch (_) { /* Standalone/help fallback still remains readable. */ }
  }
  function notifyParent(type, extra) {
    if (embedded) window.parent.postMessage(Object.assign({ type: type }, extra || {}), location.origin);
  }
  const pages = window.HaloCueHelpPages || [];
  const groups = {start: '开始使用', write: '写作与 AI', produce: '制作与素材', maintain: '数据与排障'};
  const nav = document.getElementById('docsNav');
  const main = document.getElementById('docsMain');
  const toc = document.getElementById('docsToc');
  const search = document.getElementById('docsSearch');
  const context = document.getElementById('docsContext');
  const pathStorageKey = 'halocue-help-first-scene-v1';
  let current = pages.find(function (page) { return page.id === location.hash.slice(1); }) || pages[0];
  let query = '';

  function pageText(page) {
    return (page.title + page.summary + page.sections.map(function (item) { return item.join(' '); }).join(' ') + (page.steps || []).join(' ')).toLowerCase();
  }

  function navigate(pageId) {
    const page = pages.find(function (item) { return item.id === pageId; });
    if (!page) return;
    current = page;
    history.replaceState(null, '', '#' + page.id);
    render();
    main.focus();
  }

  function readProgress() {
    try {
      const value = JSON.parse(localStorage.getItem(pathStorageKey) || '{}');
      return value && typeof value === 'object' ? value : {};
    } catch (_) { return {}; }
  }

  function writeProgress(progress) {
    try { localStorage.setItem(pathStorageKey, JSON.stringify(progress)); } catch (_) { /* Reading still works with storage disabled. */ }
  }

  function renderNav() {
    nav.replaceChildren();
    const visible = pages.filter(function (page) { return !query || pageText(page).includes(query); });
    let lastGroup = '';
    visible.forEach(function (page) {
      const group = groups[page.category] || '其他';
      if (group !== lastGroup) {
        const label = document.createElement('div');
        label.className = 'docs-nav-group';
        label.textContent = group;
        nav.appendChild(label);
        lastGroup = group;
      }
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = page.title;
      button.classList.toggle('active', page.id === current.id);
      button.addEventListener('click', function () { navigate(page.id); });
      nav.appendChild(button);
    });
    if (!visible.length) {
      const empty = document.createElement('div');
      empty.className = 'empty-state';
      empty.textContent = '没有找到匹配内容。';
      nav.appendChild(empty);
    }
  }

  function addTocLink(heading, label) {
    const link = document.createElement('a');
    link.href = '#' + heading.id;
    link.textContent = label;
    link.addEventListener('click', function (event) {
      event.preventDefault();
      main.scrollTop += heading.getBoundingClientRect().top - main.getBoundingClientRect().top - 18;
    });
    toc.appendChild(link);
  }

  function updatePathCount(target, steps, progress) {
    const done = steps.filter(function (item) { return progress[item[0]] === true; }).length;
    target.textContent = done + ' / ' + steps.length + ' 已完成';
  }

  function renderQuickPath() {
    if (!['start', 'first-scene'].includes(current.id)) return;
    const card = document.createElement('section');
    card.className = 'quick-path';
    const heading = document.createElement('div');
    heading.className = 'quick-path-heading';
    heading.innerHTML = '<div><span class="eyebrow">新手路径</span><h3>照着做，完成第一场</h3></div><span class="quick-path-count"></span>';
    card.appendChild(heading);
    const steps = [
      ['open', '打开作品或新建故事', 'start'],
      ['scene', '建立作品、章节和场景', 'first-scene'],
      ['review', '手写保存或审查助手候选', 'revision'],
      ['release', '检查定稿，再按需进入制作', 'production']
    ];
    const progress = readProgress();
    const list = document.createElement('div');
    list.className = 'quick-path-list';
    steps.forEach(function (item) {
      const row = document.createElement('label');
      row.className = 'quick-path-item';
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.checked = progress[item[0]] === true;
      checkbox.addEventListener('change', function () {
        progress[item[0]] = checkbox.checked;
        writeProgress(progress);
        updatePathCount(heading.querySelector('.quick-path-count'), steps, progress);
      });
      const label = document.createElement('span');
      label.textContent = item[1];
      row.append(checkbox, label);
      row.addEventListener('dblclick', function () { navigate(item[2]); });
      list.appendChild(row);
    });
    card.appendChild(list);
    const hint = document.createElement('p');
    hint.className = 'quick-path-hint';
    hint.textContent = '勾选只保存在本机，用来记住你看到哪一步；双击某一步可直接打开对应页面。';
    card.appendChild(hint);
    updatePathCount(heading.querySelector('.quick-path-count'), steps, progress);
    main.appendChild(card);
  }

  function render() {
    if (!current) return;
    main.replaceChildren();
    if (context) main.appendChild(context);
    toc.replaceChildren();
    const kicker = document.createElement('span');
    kicker.className = 'article-kicker';
    kicker.textContent = groups[current.category] || '帮助';
    const title = document.createElement('h2');
    title.textContent = current.title;
    const lede = document.createElement('p');
    lede.className = 'article-lede';
    lede.textContent = current.summary;
    const badge = document.createElement('span');
    badge.className = 'status-badge';
    badge.textContent = current.status;
    main.append(kicker, title, lede, badge);
    renderQuickPath();
    current.sections.forEach(function (part, index) {
      const section = document.createElement('section');
      section.className = 'article-section';
      const heading = document.createElement('h3');
      heading.id = 'section-' + current.id + '-' + index;
      heading.textContent = part[0];
      const text = String(part[1]);
      if (part[0] === '操作步骤' || part[0] === '制作顺序' || part[2] === 'steps') {
        const list = document.createElement('ol');
        list.className = 'step-list';
        text.split(/[。；\n]/).map(function (item) { return item.trim(); }).filter(Boolean).forEach(function (item) {
          const li = document.createElement('li');
          li.textContent = item;
          list.appendChild(li);
        });
        section.append(heading, list);
      } else {
        const paragraph = document.createElement('p');
        paragraph.textContent = text;
        section.append(heading, paragraph);
      }
      main.appendChild(section);
      addTocLink(heading, part[0]);
    });
    if (current.note) {
      const note = document.createElement('p');
      note.className = 'article-note';
      note.textContent = current.note;
      main.appendChild(note);
    }
    const footer = document.createElement('footer');
    footer.className = 'article-footer';
    const index = pages.indexOf(current);
    const previous = pages[index - 1];
    const next = pages[index + 1];
    const back = document.createElement('button');
    back.textContent = previous ? '‹ ' + previous.title : '返回目录';
    const forward = document.createElement('button');
    forward.textContent = next ? next.title + ' ›' : '已到最后一页';
    back.disabled = !previous;
    forward.disabled = !next;
    back.onclick = function () { if (previous) navigate(previous.id); };
    forward.onclick = function () { if (next) navigate(next.id); };
    footer.append(back, forward);
    main.appendChild(footer);
    renderNav();
    main.scrollTop = 0;
    notifyParent('halocue-help-page', { page: current.id });
  }

  function renderContext(items) {
    if (!context || !items.length) {
      if (context) context.hidden = true;
      return;
    }
    context.replaceChildren();
    const title = document.createElement('strong');
    title.textContent = '根据这台电脑的状态，你可能要先处理：';
    context.appendChild(title);
    items.forEach(function (item) {
      const row = document.createElement('div');
      row.className = 'docs-context-item ' + (item.kind || 'info');
      const text = document.createElement('span');
      text.textContent = item.text;
      const link = document.createElement('a');
      link.href = '#' + item.page;
      link.textContent = item.action || '查看说明';
      link.addEventListener('click', function (event) { event.preventDefault(); navigate(item.page); });
      row.append(text, link);
      context.appendChild(row);
    });
    const diagnostics = document.createElement('button');
    diagnostics.type = 'button';
    diagnostics.className = 'docs-context-diagnostics';
    diagnostics.textContent = '复制运行环境诊断';
    diagnostics.addEventListener('click', copyDiagnostics);
    context.appendChild(diagnostics);
    context.hidden = false;
  }

  async function copyDiagnostics() {
    const buttons = context ? context.querySelectorAll('.docs-context-diagnostics') : [];
    const button = buttons && buttons[0];
    if (button) { button.disabled = true; button.textContent = '正在读取诊断…'; }
    try {
      const diag = await getLocal('/api/v1/settings/diagnostics');
      // Whitelist only coarse status fields. Never copy arbitrary raw diagnostics,
      // model credentials, local paths, conversation content or server config.
      const payload = {
        application: 'HaloCue 1.0',
        observed_at: new Date().toISOString(),
        writing_status: 'diagnostics_reachable',
        production_status: diag.production_service?.status === 'online' ? 'online' : 'unavailable',
        local_key_protection: diag.writing_service?.dpapi_available === true,
        corpus_available: diag.corpus_status?.available === true,
        corpus_count: Number(diag.corpus_status?.count) || 0,
      };
      const text = JSON.stringify(payload, null, 2);
      let copied = false;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        try { await navigator.clipboard.writeText(text); copied = true; } catch (_) { copied = false; }
      }
      if (!copied) {
        const area = document.createElement('textarea');
        area.value = text; area.setAttribute('readonly', ''); area.className = 'docs-copy-buffer';
        document.body.appendChild(area); area.select();
        try { copied = Boolean(document.execCommand && document.execCommand('copy')); } catch (_) { copied = false; }
        area.remove();
      }
      if (copied) {
        if (button) button.textContent = '已复制，可贴到反馈里';
      } else {
        const details = document.createElement('details');
        details.className = 'docs-diagnostics-details';
        const summary = document.createElement('summary');
        summary.textContent = '复制权限受限，点这里手动复制';
        const pre = document.createElement('pre');
        pre.textContent = text;
        details.append(summary, pre);
        context.appendChild(details);
        if (button) button.textContent = '已显示诊断内容';
      }
    } catch (_) {
      if (button) button.textContent = '复制失败，请回工作台操作';
    } finally {
      if (button) setTimeout(function () { button.disabled = false; button.textContent = '复制运行环境诊断'; }, 2800);
    }
  }

  async function getLocal(url) {
    const controller = new AbortController();
    const timer = setTimeout(function () { controller.abort(); }, 5000);
    try {
      const response = await fetch(url, {headers: {Accept: 'application/json'}, signal: controller.signal});
      if (!response.ok) throw new Error('service unavailable');
      const value = await response.json();
      if (value.ok === false) throw new Error('service unavailable');
      return value.data || value;
    } finally { clearTimeout(timer); }
  }

  async function loadContext() {
    const results = await Promise.allSettled([
      getLocal('/api/v1/settings/writing-model'),
      getLocal('/api/v1/settings/diagnostics')
    ]);
    const model = results[0].status === 'fulfilled' ? results[0].value.model : null;
    const diagnostics = results[1].status === 'fulfilled' ? results[1].value : null;
    const items = [];
    if (model && !model.configured) items.push({kind: 'info', text: '写作模型尚未配置；可以先手动写作，需要 AI 时再连接。', page: 'ai', action: '查看模型设置'});
    if (diagnostics && diagnostics.production_service?.status !== 'online') items.push({kind: 'warning', text: 'AA 制作服务暂不可用；阅读手册与写作不受此提示限制。', page: 'production', action: '查看制作说明'});
    renderContext(items);
  }

  search.addEventListener('input', function () { query = search.value.trim().toLowerCase(); renderNav(); });
  document.getElementById('themeToggle').addEventListener('click', function () {
    document.body.classList.toggle('dark');
    try { localStorage.setItem('halocue-help-theme', document.body.classList.contains('dark') ? 'dark' : 'light'); } catch (_) {}
  });
  document.addEventListener('keydown', function (event) {
    if (embedded && event.key === 'Escape') { event.preventDefault(); notifyParent('halocue-help-close'); }
  });
  document.querySelectorAll('.brand, .back-link').forEach(function (link) {
    link.addEventListener('click', function (event) {
      if (embedded) { event.preventDefault(); notifyParent('halocue-help-close'); }
    });
  });
  window.addEventListener('hashchange', function () { const page = pages.find(function (item) { return item.id === location.hash.slice(1); }); if (page) { current = page; render(); } });
  try { if (!embedded && localStorage.getItem('halocue-help-theme') === 'dark') document.body.classList.add('dark'); } catch (_) {}
  render();
  loadContext().catch(function () { /* 帮助页必须在离线状态下照常可读 */ });
})();
