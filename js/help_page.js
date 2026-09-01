(function () {
  'use strict';

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
    localStorage.setItem(pathStorageKey, JSON.stringify(progress));
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
      main.scrollTop = Math.max(0, heading.offsetTop - 18);
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
      ['open', '打开程序并检查环境', 'start'],
      ['scene', '建立作品、章节和场景', 'first-scene'],
      ['review', '生成草稿并审查 Proposal', 'ai'],
      ['release', '通过检查并生成 AA 工程', 'production']
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
      const response = await fetch('/api/diagnostics/runtime', {headers: {'Accept': 'application/json'}});
      if (!response.ok) throw new Error('diagnostics unavailable');
      const payload = await response.json();
      const text = JSON.stringify(payload, null, 2);
      let copied = false;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        try { await navigator.clipboard.writeText(text); copied = true; } catch (_) { copied = false; }
      }
      if (!copied) {
        const area = document.createElement('textarea');
        area.value = text; area.setAttribute('readonly', ''); area.style.position = 'fixed'; area.style.opacity = '0';
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

  async function loadContext() {
    const get = function (url) { return fetch(url, {headers: {'Accept': 'application/json'}}).then(function (response) { if (!response.ok) throw new Error('status'); return response.json(); }); };
    const results = await Promise.allSettled([get('/api/setup/status'), get('/api/migration/status'), get('/api/update/status')]);
    const setup = results[0].status === 'fulfilled' ? results[0].value : null;
    const migration = results[1].status === 'fulfilled' ? results[1].value : null;
    const update = results[2].status === 'fulfilled' ? results[2].value : null;
    const items = [];
    if (migration && (migration.requires_confirmation || migration.detected)) items.push({kind: 'warning', text: '发现 0.9.3 的旧数据，迁移前请先创建备份。', page: 'data', action: '查看迁移步骤'});
    if (setup && setup.aa && !setup.aa.connected) items.push({kind: 'info', text: '还没有连接 AzureArchive，普通写作可以继续，AA 制作需要先配置。', page: 'production', action: '查看连接方法'});
    if (setup && setup.model && !setup.model.configured) items.push({kind: 'info', text: '尚未配置模型；可以先用“仅转换格式”，需要 AI 时再设置。', page: 'ai', action: '查看模型设置'});
    if (update && update.status === 'available' && update.version) items.push({kind: 'success', text: '发现 HaloCue ' + update.version + '，请查看更新说明后再决定是否安装。', page: 'data', action: '查看更新说明'});
    renderContext(items);
  }

  search.addEventListener('input', function () { query = search.value.trim().toLowerCase(); renderNav(); });
  document.getElementById('themeToggle').addEventListener('click', function () { document.body.classList.toggle('dark'); localStorage.setItem('halocue-help-theme', document.body.classList.contains('dark') ? 'dark' : 'light'); });
  window.addEventListener('hashchange', function () { const page = pages.find(function (item) { return item.id === location.hash.slice(1); }); if (page) { current = page; render(); } });
  if (localStorage.getItem('halocue-help-theme') === 'dark') document.body.classList.add('dark');
  render();
  loadContext().catch(function () { /* 帮助页必须在离线状态下照常可读 */ });
})();
