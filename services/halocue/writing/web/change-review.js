/* Author-facing review of durable proposals. Pure projection; never writes story data. */
(function (root) {
  'use strict';
  const labels = {
    brief: '创作想法', story_blueprint: '故事方向', chapter_plan: '章内细纲',
    idea: '写作想法', title: '标题', premise: '故事前提', central_conflict: '核心冲突',
    direction: '剧情走向', constraints: '创作约束', characters: '登场人物',
    character_card_ids: '关联人物卡', mode: '写作模式', story_modes: '故事模式',
    target_length: '目标篇幅', has_sensei: '老师是否登场', sensei_decision: '老师登场安排',
    chapter_goal: '本章目标', goal: '目标', summary: '摘要', beats: '情节节拍',
    scenes: '场景', ending: '结尾', ending_payoff: '结尾落点', emotional_arc: '情绪变化',
    name: '名称', text: '内容', role: '故事职责', relationships: '人物关系',
    voice_anchors: '口吻锚点', knowledge_boundary: '知情边界', ooc_constraints: '人物红线',
    known_facts: '已知事实', forbidden_reveals: '禁止提前揭示', stop_boundary: '收束边界',
    location: '地点', writing_mode: '写作模式', purpose: '目的', contract: '场景约束',
  };
  const operations = { add: ['＋', '新增'], modify: ['↔', '修改'], remove: ['−', '删除'] };
  const escape = value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;');
  const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  const empty = value => value == null || value === '' || (Array.isArray(value) && !value.length)
    || (record(value) && !Object.keys(value).length);
  const canonical = value => JSON.stringify(record(value)
    ? Object.fromEntries(Object.keys(value).sort().map(key => [key, JSON.parse(canonical(value[key]) ?? 'null')]))
    : Array.isArray(value) ? value.map(item => JSON.parse(canonical(item) ?? 'null')) : value);
  const operation = (before, after) => empty(before) ? 'add' : empty(after) ? 'remove' : 'modify';

  function readable(value) {
    if (empty(value)) return '';
    if (typeof value === 'boolean') return value ? '是' : '否';
    if (Array.isArray(value)) return value.map(item => `• ${readable(item)}`).join('\n');
    if (record(value)) return Object.entries(value).map(([key, item]) => `${labels[key] || key}：${readable(item)}`).join('\n');
    return String(value);
  }

  function compare(before, after, group, path = '') {
    const rows = [];
    const old = record(before) ? before : {}, next = record(after) ? after : {};
    for (const key of new Set([...Object.keys(old), ...Object.keys(next)])) {
      // Revision/workflow metadata is not authored content. Other fields are never omitted.
      if (['schema_version', 'status'].includes(key)) continue;
      const a = old[key], b = next[key], field = path ? `${path} / ${labels[key] || key}` : labels[key] || key;
      if (canonical(a) === canonical(b) || (empty(a) && empty(b))) continue;
      if (record(a) || record(b)) rows.push(...compare(a, b, group, field));
      else rows.push({ group, field, before: a, after: b, operation: operation(a, b) });
    }
    return rows;
  }

  function model(proposal, work = {}) {
    const result = { rows: [], warning: '', status: proposal?.status || 'pending' };
    if (!proposal) return result;
    if (proposal.candidate_integrity?.valid === false) {
      result.warning = '候选校验失败，无法展示可靠的改动。请退回后重新整理。';
      return result;
    }
    const candidate = record(proposal.candidate) ? proposal.candidate : {};
    const artifacts = Array.isArray(work.artifacts) ? work.artifacts : [];
    const compareArtifact = (kind, scopeId, baseKey, content) => {
      const current = artifacts.find(item => item.kind === kind && (!scopeId || item.scope_id === scopeId))?.current_revision;
      const base = candidate[baseKey];
      if ((current?.id || null) !== (base || null)) {
        result.warning = '正式版本已变化，无法用当前内容替代候选生成时的原文。请重新整理候选后再审查。';
        return;
      }
      result.rows.push(...compare(current?.content || {}, content || {}, labels[kind] || kind));
    };
    if (proposal.kind === 'brief_blueprint') {
      compareArtifact('brief', null, 'base_brief_revision_id', candidate.brief);
      compareArtifact('story_blueprint', null, 'base_blueprint_revision_id', candidate.story_blueprint);
    } else if (proposal.kind === 'chapter_plan') {
      compareArtifact('chapter_plan', proposal.scope_id, 'base_revision_id', candidate.chapter_plan);
    } else if (proposal.kind === 'story_structure') {
      const existing = [...(work.volumes || []), ...(work.chapters || [])];
      const visit = (item, type, parent = '') => {
        const group = parent || '作品结构', field = `${type} · ${item.title || '未命名'}`;
        const content = { title: item.title, goal: item.goal, ...(item.contract ? { contract: item.contract } : {}) };
        if (item.operation === 'reuse_placeholder') {
          const previous = existing.find(value => value.id === item.id);
          const expected = candidate.base?.entity_versions?.[item.id];
          if (!previous || (expected != null && previous.version !== expected)) {
            result.warning = '结构的原始版本无法核对，请重新整理候选后再审查。';
          } else {
            result.rows.push(...compare({ title: previous.title, goal: previous.goal }, content, `${group} / ${field}`));
          }
        } else {
          result.rows.push({ group, field, before: null, after: content, operation: 'add' });
        }
        for (const chapter of item.chapters || []) visit(chapter, '章', item.title);
        for (const scene of item.scenes || []) visit(scene, '场景', item.title);
      };
      for (const volume of candidate.plan?.volumes || []) visit(volume, '卷');
    } else {
      const fields = candidate.field_changes || proposal.diff?.changes;
      if (Array.isArray(fields)) {
        for (const field of fields) {
          if (!Object.hasOwn(field, 'before') || !Object.hasOwn(field, 'after')) {
            result.warning = '这份候选缺少完整的改前／改后记录，不能据此判断新增或删除。';
            continue;
          }
          if (canonical(field.before) === canonical(field.after) || (empty(field.before) && empty(field.after))) continue;
          result.rows.push({ group: candidate.title || '作品资料', field: field.field || field.label || labels[field.key] || field.key || '内容',
            before: field.before, after: field.after, operation: operation(field.before, field.after) });
        }
      } else result.warning = '这份候选没有可核对的逐项改动记录。';
    }
    // Partial counts could misrepresent a stale candidate as completely reviewed.
    if (result.warning) result.rows = [];
    return result;
  }

  function countsMarkup(rows) {
    const counts=Object.entries(operations).map(([key,[symbol,label]])=>({key,symbol,label,count:rows.filter(row=>row.operation===key).length})).filter(item=>item.count);
    return `<div class="change-review-counts" aria-label="改动统计">${counts.map(({key,symbol,label,count})=>`<span class="change-count is-${key}">${symbol} ${label} <b>${count}</b></span>`).join('')||'<span class="change-count">无内容改动</span>'}</div>`;
  }

  function reviewPreview(row) {
    const content=row.operation==='remove'?row.before:row.after;
    const summary=record(content)?content.contract?.goal||content.goal||content.summary||content.text||content.title||content:content;
    const value=readable(summary).replace(/\s+/g,' ').trim();
    return value.length>96?`${value.slice(0,96)}…`:value;
  }

  function pairMarkup(before, after) {
    const side = (value, which, title) => `<div class="change-review-side is-${which}"><small>${title}</small>${empty(value)
      ? '<p class="change-review-empty">（无内容）</p>'
      : `<pre>${escape(readable(value))}</pre>`}</div>`;
    return `<div class="change-review-pair">${side(before, 'before', '改前')}${side(after, 'after', '改后（候选）')}</div>`;
  }

  function markup(review, id = '') {
    const stateLabel = { pending: '待采纳 · 尚未写入', accepted: '已采纳', rejected: '已退回', superseded: '已失效' }[review.status] || '候选记录';
    return `<section class="change-review" data-change-review="${escape(id)}" aria-label="AI 改动清单"><header class="change-review-head"><div><b>AI 改动清单</b><small>${stateLabel}</small></div>${review.warning ? '' : countsMarkup(review.rows)}${!review.warning&&review.rows.length>1?'<button type="button" class="quiet review-expand-all" data-review-expand-all>展开全部</button>':''}</header>${review.warning
      ? `<p class="change-review-warning" role="status">${escape(review.warning)}</p>`
      : review.rows.length ? `<div class="change-review-list">${review.rows.map((row, index) => {
        const [symbol, label] = operations[row.operation];
        return `<details data-agent-disclosure="review:${escape(id)}:${index}" class="change-review-item is-${row.operation}"${index === 0 ? ' open' : ''}><summary><span class="change-operation">${symbol} ${label}</span><span class="change-review-name"><small>${escape(row.group)}</small><b>${escape(row.field)}</b><span class="change-review-preview">${escape(reviewPreview(row))}</span></span><span class="change-review-chevron" aria-hidden="true">⌄</span></summary>${pairMarkup(row.before, row.after)}</details>`;
      }).join('')}</div>` : '<p class="change-review-empty">与正式内容一致，没有内容增删改。</p>'}</section>`;
  }

  function blocksText(blocks) {
    return (Array.isArray(blocks) ? blocks : []).map(block => {
      const who = block.type === 'narration' ? '旁白' : block.type === 'action' ? '动作' : block.speaker || '对白';
      return `${who}：${block.text || ''}`;
    }).join('\n');
  }

  function sceneRows(changes) {
    return changes.map(change => ({ ...change, operation: change.kind === 'insert' ? 'add' : change.kind === 'delete' ? 'remove' : 'modify' }));
  }

  function sceneMarkup(changes, selected, preview, proposalId = '') {
    const rows = sceneRows(changes);
    return `<div class="scene-review-toolbar">${countsMarkup(rows)}${rows.length>1?'<button type="button" class="quiet review-expand-all" data-review-expand-all>展开全部</button>':''}</div><section class="scene-diff-choices scene-review-list" aria-label="选择要应用的修改">${rows.map((change, index) => {
      const [symbol, label] = operations[change.operation], text = preview(change);
      const start = Number(change.base_start) || 0, end = Number(change.base_end) || start;
      const location = change.kind === 'insert' ? (start ? `原文第 ${start} 段后` : '正文开头')
        : `原文第 ${start + 1}${end > start + 1 ? `–${end}` : ''} 段`;
      return `<article class="scene-review-change is-${change.operation}" data-review-change="${escape(change.id)}"><div class="scene-review-change-head"><label class="scene-diff-choice"><input type="checkbox" value="${escape(change.id)}" data-scene-change ${selected.has(change.id) ? 'checked' : ''} aria-label="采用${label} ${index + 1}：${escape(text)}"><span><b><span class="change-operation">${symbol} ${label}</span> <span class="scene-review-location">${location}</span></b><small data-scene-change-preview>${escape(text)}</small></span></label><button type="button" class="quiet" data-discuss-scene-change="${escape(change.id)}" data-review-proposal="${escape(proposalId)}" aria-label="讨论第 ${index + 1} 项改动">讨论这项</button></div><details class="scene-review-detail"${rows.length <= 3 || index === 0 ? ' open' : ''}><summary>查看改前 / 改后 <span aria-hidden="true">⌄</span></summary>${pairMarkup(blocksText(change.old_blocks), blocksText(change.new_blocks))}</details></article>`;
    }).join('')}</section>`;
  }

  if(typeof document!=='undefined') {
    const updateButton=root=>{
      const button=root?.querySelector('[data-review-expand-all]');if(!button)return;
      const items=[...root.querySelectorAll('.change-review-item,.scene-review-detail')];
      button.textContent=items.length&&items.every(item=>item.open)?'收起全部':'展开全部';
    };
    document.addEventListener('click',event=>{
      const button=event.target.closest?.('[data-review-expand-all]');if(!button)return;
      const root=button.closest('.change-review,.scene-diff-desk');if(!root)return;
      const items=[...root.querySelectorAll('.change-review-item,.scene-review-detail')];
      const open=!items.every(item=>item.open);items.forEach(item=>{item.open=open;});updateButton(root);
    });
    document.addEventListener('toggle',event=>{
      if(event.target.matches?.('.change-review-item,.scene-review-detail'))updateButton(event.target.closest('.change-review,.scene-diff-desk'));
    },true);
  }

  const api = Object.freeze({ model, markup, compare, readable, countsMarkup, pairMarkup, sceneMarkup });
  root.HaloCueChangeReview = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(globalThis);
