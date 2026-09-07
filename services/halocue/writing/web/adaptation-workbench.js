/* Original source → explicit plan → durable candidates → ordinary scene revisions. */
(function () {
  "use strict";
  window.createAdaptationWorkbench = function (bridge) {
    const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
    const dialog = document.createElement("dialog");
    dialog.className = "adaptation-workbench";
    dialog.setAttribute("aria-label", "原文改编工作台");
    document.body.append(dialog);
    let epoch = 0, timer = null, busy = false, work = null, source = null, plans = [], provider = null;
    let stage = "source", error = "", upload = null, preview = null, selection = new Set(), updateSelection = new Set();
    let completion = "ongoing", mode = "append", scope = "", mapping = "", maxCalls = 5, planId = "";
    let runUpdates = new Map(), retryKeys = new Map();
    const root = () => `/works/${encodeURIComponent(work.id)}`;
    const active = token => token === epoch && dialog.open && (bridge.getWork()?.id || null) === (work?.id || null);
    const post = (path, body) => bridge.api(path, {method:"POST", body:JSON.stringify(body)});
    const currentPlan = () => plans.find(p => p.id === planId) || null;
    const chapterName = id => work?.chapters?.find(c => c.id === id)?.title || "目标章节不可用";
    const sourceName = id => source?.chapters?.find(c => c.id === id)?.title || "原文章节";
    function close() { epoch++; clearTimeout(timer); timer = null; busy = false; dialog.close(); }
    function currentRun(chapter) {
      const rows = (work?.agent_runs || []).filter(r => r.scope_id === chapter.id && r.policy?.workflow === "adaptation.chapter.generate");
      return rows.length ? (runUpdates.get(rows[0].id) || rows[0]) : null;
    }
    function schedule(token) {
      clearTimeout(timer);
      if (!active(token) || busy) return;
      const running = (currentPlan()?.chapters || []).map(currentRun).filter(r => ["queued","running"].includes(r?.status));
      if (!running.length) return;
      timer = setTimeout(async () => {
        try {
          const values = await Promise.all(running.map(r => bridge.api(`${root()}/agent-runs/${encodeURIComponent(r.id)}`)));
          if (!active(token)) return;
          values.forEach(r => runUpdates.set(r.id, r));
          if (values.some(r => !["queued","running"].includes(r.status))) await reload(token);
          if (!active(token)) return;
          render(); schedule(token);
        } catch (e) { if (active(token)) { error = e.message; render(); } }
      }, 1000);
    }
    async function reload(token) {
      if (!work) return;
      const [fresh, saved, history, caps] = await Promise.all([
        bridge.api(root()), bridge.api(`${root()}/source`), bridge.api(`${root()}/adaptations`), bridge.api("/capabilities")
      ]);
      if (!active(token)) return;
      work = fresh; source = saved; plans = history; provider = caps.providers?.[0] || null;
      if (!plans.some(p => p.id === planId)) planId = plans[0]?.id || "";
      selection = new Set([...selection].filter(id => source?.chapters?.some(ch => ch.id === id)));
      if (!selection.size) selection = new Set((source?.chapters || []).map(ch => ch.id));
    }
    async function action(fn) {
      if (busy || !dialog.open) return;
      if ((bridge.getWork()?.id || null) !== (work?.id || null)) { close(); return; }
      // Supersede reads already in flight, not only the next scheduled poll.
      const token = ++epoch;
      busy = true; error = ""; clearTimeout(timer); render();
      try { await fn(token); } catch (e) { if (active(token)) { error = e.message || "操作未完成，请重试。"; if (e.code?.includes("source_") || e.code === "provider_config_changed") preview = null; } }
      finally { if (active(token)) { busy = false; render(); schedule(token); } }
    }
    function sourceMarkup() {
      return `<div class="adaptation-fields"><label>原文文件<input type="file" accept=".txt,.docx" data-adaptation-file ${busy?"disabled":""}></label>
        <label>原作状态<select data-field="completion"><option value="ongoing" ${completion==="ongoing"?"selected":""}>连载中 · 不续写未提供内容</option><option value="complete" ${completion==="complete"?"selected":""}>已完结 · 只处理提供范围</option></select></label>
        <label>提供范围<input data-field="scope" value="${esc(scope)}" placeholder="例如：第一至第三章，不包含后续剧情"></label>
        ${source?`<label>这次导入<select data-field="mode"><option value="append" ${mode==="append"?"selected":""}>追加章节</option><option value="update" ${mode==="update"?"selected":""}>更新选定旧章节</option></select></label>`:""}</div>
        ${source && mode==="update"?`<fieldset class="adaptation-chapters"><legend>按原文顺序选择要更新的旧章节（数量需与文件一致）</legend>${source.chapters.map(ch=>`<label><input type="checkbox" data-update-chapter="${esc(ch.id)}" ${updateSelection.has(ch.id)?"checked":""}>${esc(ch.title)}</label>`).join("")}</fieldset>`:""}
        <p class="adaptation-note">${upload?esc(upload.filename):"选择文件只读取本地内容。保存原文不会调用模型，也不会建立正式场景。"}</p>
        <button type="button" class="primary" data-do="preview" ${!upload||busy?"disabled":""}>预览原文变化</button>
        ${preview?`<section class="adaptation-card"><h3>确认本次原文变化</h3><p>${preview.duplicate?"该文件已保存，本次不会重复追加。":"原文件与来源记录将保留；正式正文不变。"}</p>${(preview.changes||[]).map(c=>`<details open><summary>${esc(c.title)} · ${c.kind==="added"?"新增":"更新"}</summary><pre>${esc((c.diff||[]).join("\n"))}</pre></details>`).join("")}<button class="primary" data-do="apply" ${busy?"disabled":""}>确认保存原文</button></section>`:""}`;
    }
    function planMarkup() {
      if (!source) return `<p class="adaptation-empty">先保存原文，再选择本次改编范围。</p>`;
      const plan = currentPlan();
      if (plan?.status === "awaiting_plan") return `<section class="adaptation-card"><h3>确认本次计划</h3><p>${plan.selected_chapter_ids.map(sourceName).map(esc).join("、")}</p><ul>${(plan.plan?.rules||[]).map(t=>`<li>${esc(t)}</li>`).join("")}</ul><p>逻辑候选调用上限：${esc(plan.budget?.max_calls)}。失败尝试也可能消耗额度。</p><pre>${esc(Object.entries(plan.plan?.character_mapping||{}).map(([a,b])=>`${a} → ${b}`).join("\n") || "保留原文人物称呼")}</pre><button class="primary" data-do="approve" ${busy?"disabled":""}>确认计划</button></section>`;
      return `<fieldset class="adaptation-chapters"><legend>本次要改编的章节</legend>${source.chapters.map(ch=>`<label><input type="checkbox" data-chapter="${esc(ch.id)}" ${selection.has(ch.id)?"checked":""}>${esc(ch.title)}</label>`).join("")}</fieldset>
        <div class="adaptation-fields"><label>人物称呼映射（可不填；每行“原名 = 目标名”）<textarea data-field="mapping" placeholder="原文老师 = 老师">${esc(mapping)}</textarea></label><label>候选调用上限<input type="number" min="1" max="1000" data-field="maxCalls" value="${esc(maxCalls)}"></label></div>
        <p class="adaptation-note">这里只保存你确认的范围与称呼，不调用模型。目标场景位置会在候选审核时列明。</p><button class="primary" data-do="create-plan" ${busy||!selection.size?"disabled":""}>建立改编计划</button>`;
    }
    function chaptersMarkup() {
      const plan = currentPlan();
      if (!plan) return `<p class="adaptation-empty">先建立并确认改编计划。</p>`;
      if (plan.status === "awaiting_plan") return planMarkup();
      const outdated = plan.source_version_id !== source?.id;
      return `${outdated?'<p class="adaptation-alert">本计划的原文已更新。请基于当前原文建立新计划；旧结果不会自动覆盖。</p>':""}
      ${(plan.chapters||[]).map(ch=>{
        const run = currentRun(ch), running=["queued","running"].includes(run?.status), cand=ch.candidate||{};
        const proposal=(work.proposals||[]).find(p=>p.id===cand.proposal_id);
        const pending=ch.status==="candidate" && cand.formal===false && proposal?.status!=="superseded" && proposal?.status!=="accepted";
        const legacyPending=!cand.target;
        const target=cand.target||ch.resolved_target||{}, mapped=ch.dependency?.scene_target;
        const failed=["failed","cancelled"].includes(run?.status);
        const knownFailure=run?.failure;
        const stopped=knownFailure?.retryable===false || ["provider_config_changed","adaptation_inputs_changed","adaptation_budget_exhausted"].includes(knownFailure?.code);
        const exhausted=Number(plan.budget?.reserved_calls||0)>=Number(plan.budget?.max_calls||0);
        return `<article class="adaptation-card"><header><h3>${esc(sourceName(ch.source_chapter_id))}</h3><span class="adaptation-status" data-state="${esc(running?'running':ch.status)}">${running?"生成中 · 可停止":pending?"候选待审核":ch.status==="accepted"?"已采纳":failed?"本轮已停止":"等待生成"}</span></header>
          ${knownFailure?`<p class="adaptation-alert">${esc(knownFailure.message)}${stopped?" 请确认配置、原文及目标后重新生成，不要重复重试旧任务。":""}</p>`:""}
          ${running?`<button class="danger" data-do="cancel" data-run="${esc(run.id)}" ${busy?"disabled":""}>停止本轮</button>`:`${failed&&!stopped?`<button class="quiet" data-do="retry" data-run="${esc(run.id)}" ${busy||outdated||exhausted?"disabled":""}>重试固定输入</button>`:""}<button class="${pending?'quiet':'primary'}" data-do="generate" data-chapter-id="${esc(ch.source_chapter_id)}" ${busy||outdated||exhausted||!provider?"disabled":""}>${provider?.is_simulation?"生成模拟候选":"使用当前模型生成候选"}</button>`}
          ${exhausted?'<p class="adaptation-note">本计划调用上限已用尽；请重新评估范围后建立新计划。</p>':""}
          ${pending?`<pre>${esc(cand.text)}</pre><details><summary>原文依据与待确认内容</summary>${(cand.source_refs||[]).map(ref=>`<blockquote class="adaptation-reference">${esc(ref.quote)}</blockquote>`).join("")}<pre>${esc(JSON.stringify({偏离说明:cand.deviations||[],未决内容:cand.open_threads||[]},null,2))}</pre></details>
            <p><strong>${target.scene_id?"替换已关联场景":"新建场景"}</strong> · ${esc(chapterName(target.chapter_id))}</p><p class="adaptation-note">采纳才会写入正式场景；空行、冒号等格式按场景编辑器归一化。不会自动发布或安装。</p>
            <button class="primary" data-do="accept" data-proposal="${esc(cand.proposal_id)}" data-target-chapter="${esc(target.chapter_id)}" ${busy||outdated||!target.chapter_id||proposal?.candidate_integrity?.valid===false?"disabled":""}>${legacyPending?"确认目标并采纳旧候选":"采纳到此场景"}</button>`:""}
          ${ch.status==="accepted"&&mapped?.scene_id?`<button class="primary" data-do="scene" data-adaptation-scene="${esc(mapped.scene_id)}">查看正式场景</button>`:""}
          ${ch.status==="accepted"&&!mapped?.scene_id&&cand.revision_id?`<p>这是旧版已采纳稿，尚未进入场景。原稿将保留。</p><label>放入的章节<select data-promotion-target="${esc(ch.id)}">${work.chapters.map(c=>`<option value="${esc(c.id)}">${esc(c.title)}</option>`).join("")}</select></label><button class="primary" data-do="promote" data-chapter-id="${esc(ch.source_chapter_id)}" data-row="${esc(ch.id)}" data-revision="${esc(cand.revision_id)}" ${busy||outdated?"disabled":""}>确认把旧稿放入场景</button>`:""}</article>`;
      }).join("")}`;
    }
    function render() {
      if (!dialog.open) return;
      const plan=currentPlan();
      dialog.innerHTML=`<header class="adaptation-head"><div><p class="eyebrow">SOURCE TO SCENE</p><h2>把已有故事，写进场景</h2><p>保留原文依据，逐章审查。正式正文只在你采纳后改变。</p></div><button class="icon-button" aria-label="关闭改编工作台" data-do="close">×</button></header>
        <ol class="adaptation-steps">${[["source","原文"],["plan","计划"],["chapters","候选"]].map(([id,label])=>`<li data-current="${stage===id}"><button data-do="stage" data-adaptation-stage="${id}" ${busy?"disabled":""}>${label}</button></li>`).join("")}</ol>
        <section class="adaptation-body">${error?`<p class="adaptation-alert" role="alert">${esc(error)}</p>`:""}<div class="adaptation-layout"><aside class="adaptation-summary"><h3>${esc(work?.title||"新作品")}</h3><p>${source?esc(source.filename):"尚未保存原文"}</p><p>${source?.completion_state==="complete"?"原作已完结":"连载或片段 · 不续写未提供内容"}</p><p>${esc(source?.provided_scope||"仅处理已提供的章节")}</p><p>${provider?(provider.is_simulation?"当前是模拟模式，不调用真实模型。":`当前真实模型：${provider.model||provider.display_name||provider.kind}。生成会发送选定章节并产生用量。`):"模型状态待读取；生成暂不可用。"}</p>${plan?`<p>逻辑调用 ${esc(plan.budget?.reserved_calls||0)} / ${esc(plan.budget?.max_calls)}</p>`:""}
          ${plans.length?`<label>改编记录<select data-field="planId">${plans.map(p=>`<option value="${esc(p.id)}" ${p.id===planId?"selected":""}>${esc((p.selected_chapter_ids||[]).map(sourceName).join("、")||p.id)} · ${p.status==="awaiting_plan"?"待确认":"已确认"}</option>`).join("")}</select></label>`:""}
          <button class="quiet" data-do="refresh" ${busy?"disabled":""}>刷新状态</button><p class="adaptation-note">关闭后任务仍会继续。需要停止时，请点击本轮的停止按钮。</p></aside>
        <main class="adaptation-main"><p class="adaptation-disclosure">${provider?.is_simulation?"模拟模式 · 不调用真实模型":provider?`当前模型 ${esc(provider.model||provider.display_name||provider.kind)} · 生成将发送选定原文章节`:"当前模型状态未知，请刷新后再生成"} · 仅改编已提供内容</p>${busy?'<p role="status" class="adaptation-note">正在处理，请稍候…</p>':""}${stage==="source"?sourceMarkup():stage==="plan"?planMarkup():chaptersMarkup()}</main></div></section>
        <footer class="adaptation-actions"><button class="quiet" data-do="new-plan" ${busy||!source?"disabled":""}>新建改编计划</button><button class="quiet" data-do="prerequisites">完善写作方向与发布条件</button><button class="quiet" data-do="close">暂时关闭</button></footer>`;
      if(busy)dialog.querySelectorAll('input,select,textarea,button:not([data-do="close"])').forEach(control=>{control.disabled=true;});
    }
    async function open(filePayload = null) {
      const token=++epoch; clearTimeout(timer); busy=true; error=""; work=bridge.getWork(); source=null; plans=[]; provider=null; planId=""; runUpdates=new Map();
      upload=filePayload; preview=null; stage="source"; selection=new Set(); updateSelection=new Set(); mode="append"; mapping=""; maxCalls=5;
      if(!dialog.open)dialog.showModal(); render();
      try {
        if(work)await reload(token); else { const caps=await bridge.api("/capabilities"); if(active(token))provider=caps.providers?.[0]||null; }
        if(!active(token))return;
        completion=source?.completion_state||"ongoing"; scope=source?.provided_scope||"";
        stage=upload?"source":source?(plans.length?"chapters":"plan"):"source";
      }catch(e){if(active(token))error=e.message;}
      finally{if(active(token)){busy=false;render();schedule(token);}}
    }
    dialog.addEventListener("cancel", event=>{event.preventDefault();close();});
    dialog.addEventListener("input", event=>{
      const field=event.target.dataset.field;
      if(field==="scope")scope=event.target.value;
      if(field==="mapping")mapping=event.target.value;
      if(field==="maxCalls")maxCalls=Number(event.target.value);
      if(field==="scope")preview=null;
    });
    dialog.addEventListener("change", async event=>{
      if(busy)return;
      const el=event.target;
      if(el.matches("[data-adaptation-file]")){
        const file=el.files?.[0]; if(!file)return;
        void action(async token=>{
          if(!/\.(txt|docx)$/i.test(file.name)||file.size>16000000)throw Error("请选择不超过 16 MB 的 TXT 或 DOCX 文件。");
          const bytes=await file.arrayBuffer(); if(!active(token))return;
          upload={filename:file.name,content_base64:bridge.encode(bytes)};preview=null;
        }); return;
      }
      if(el.dataset.chapter){el.checked?selection.add(el.dataset.chapter):selection.delete(el.dataset.chapter);render();}
      if(el.dataset.updateChapter){el.checked?updateSelection.add(el.dataset.updateChapter):updateSelection.delete(el.dataset.updateChapter);preview=null;render();}
      if(el.dataset.field==="completion"){completion=el.value;preview=null;render();}
      if(el.dataset.field==="mode"){mode=el.value;preview=null;render();}
      if(el.dataset.field==="planId"){planId=el.value;stage="chapters";render();schedule(epoch);}
    });
    dialog.addEventListener("click", event=>{
      const button=event.target.closest("[data-do]"); if(!button||button.disabled)return;
      const command=button.dataset.do;
      if(command==="close"){close();return;}
      if(command==="stage"){stage=button.dataset.adaptationStage;render();schedule(epoch);return;}
      if(command==="new-plan"){planId="";stage="plan";render();return;}
      if(command==="scene"||command==="prerequisites"){
        const destination=command==="scene"?button.dataset.adaptationScene:null;
        close(); bridge.guard(()=>bridge.navigate(work?.id,destination)); return;
      }
      // Capture DOM input before action re-renders the dialog.
      const promotionChapter=command==="promote"?dialog.querySelector(`[data-promotion-target="${CSS.escape(button.dataset.row)}"]`)?.value:null;
      void action(async token=>{
        if(command==="refresh"){await reload(token);return;}
        if(command==="preview"){
          if(!upload)throw Error("请先选择原文文件。");
          if(!work){const created=await post("/works",{title:upload.filename.replace(/\.[^.]+$/,""),world_seed:"blank"});if(!active(token))return;work=created;bridge.setWork(created);}
          const saved=await bridge.api(`${root()}/source`);if(!active(token))return;source=saved;
          const body={...upload,base_version_id:source?.id||null,mode,chapter_ids:(source?.chapters||[]).filter(ch=>updateSelection.has(ch.id)).map(ch=>ch.id),completion_state:completion,provided_scope:scope};
          const result=await post(`${root()}/source:preview`,body);if(active(token))preview={...result,request:body};return;
        }
        if(command==="apply"){
          if(!preview)throw Error("原文选项已变化，请重新预览。");
          const saved=await post(`${root()}/source:update`,{...preview.request,preview_digest:preview.preview_digest});
          if(!active(token))return;source=saved.source;upload=null;preview=null;selection=new Set(source.chapters.map(ch=>ch.id));planId="";stage="plan";return;
        }
        if(command==="create-plan"){
          if(!selection.size||!Number.isInteger(maxCalls)||maxCalls<1||maxCalls>1000)throw Error("请至少选择一章，并填写 1–1000 的调用上限。");
          const names={}; for(const line of mapping.split("\n").map(l=>l.trim()).filter(Boolean)){const at=line.indexOf("=");if(at<1||!line.slice(at+1).trim())throw Error("人物映射请每行填写“原名 = 目标名”。");names[line.slice(0,at).trim()]=line.slice(at+1).trim();}
          const result=await post(`${root()}/adaptations`,{source_version_id:source.id,chapter_ids:[...selection],character_mapping:names,max_calls:maxCalls});
          if(!active(token))return;plans=[result,...plans];planId=result.id;return;
        }
        const plan=currentPlan(); if(!plan)throw Error("请先建立改编计划。");
        const path=`${root()}/adaptations/${encodeURIComponent(plan.id)}`;
        if(command==="approve"){const saved=await post(`${path}/plan:approve`,{plan_digest:plan.plan_digest});if(!active(token))return;plans=plans.map(p=>p.id===saved.id?saved:p);stage="chapters";return;}
        if(command==="generate"){await post(`${path}/chapters/${encodeURIComponent(button.dataset.chapterId)}/candidate:generate`,{expected_provider:provider});}
        if(command==="cancel"){await post(`${root()}/agent-runs/${encodeURIComponent(button.dataset.run)}:cancel`,{});}
        if(command==="retry"){const id=button.dataset.run;if(!retryKeys.has(id))retryKeys.set(id,crypto.randomUUID());await post(`${root()}/agent-runs/${encodeURIComponent(id)}:retry`,{idempotency_key:retryKeys.get(id)});}
        if(command==="accept"||command==="promote"){
          const fresh=await bridge.api(root());if(!active(token))return;
          const result=command==="accept"?await post(`${root()}/proposals/${encodeURIComponent(button.dataset.proposal)}/accept`,{expected_version:fresh.version,target_chapter_id:button.dataset.targetChapter})
            :await post(`${path}/chapters/${encodeURIComponent(button.dataset.chapterId)}/manuscript:promote`,{expected_version:fresh.version,expected_revision_id:button.dataset.revision,target_chapter_id:promotionChapter});
          if(!active(token))return;work=result.work;bridge.setWork(work);await reload(token);return;
        }
        if(active(token))await reload(token);
      });
    });
    return {open, close, isOpen:()=>dialog.open};
  };
})();
