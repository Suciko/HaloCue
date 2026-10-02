(() => {
  'use strict';
  const dialog = document.getElementById('externalAgentDialog');
  if (!dialog) return;
  const createForm = dialog.querySelector('[data-external-create]');
  const importForm = dialog.querySelector('[data-external-import]');
  const taskPanel = dialog.querySelector('[data-external-task]');
  const message = dialog.querySelector('[data-external-message]');
  let task = null, packageValue = null, scope = null, busy = false, config = null;
  const request = (path, body) => api('/external-agent/' + path, body === undefined ? {} : {method:'POST', body:JSON.stringify(body)});
  function note(text, failed = false) { message.textContent = text; message.dataset.failed = String(failed); }
  function controls() {
    dialog.querySelectorAll('button,input,textarea').forEach(el => {el.disabled = busy;});
    taskPanel.querySelectorAll('button,input,textarea').forEach(el => {el.disabled = busy || (task?.status !== 'open' && !el.matches('[data-external-refresh],[data-external-review]'));});
  }
  async function run(action) {
    if (busy) return;
    busy = true; controls();
    try { await action(); } catch (error) { note(error.message, true); }
    finally { busy = false; controls(); }
  }
  function download(value, filename) {
    const url = URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = filename;
    document.body.append(anchor); anchor.click(); anchor.remove(); setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  function showTask(value, exported = null) {
    task = value; packageValue = exported; config = null; taskPanel.hidden = false;
    dialog.querySelector('[data-external-config]').hidden = true;
    dialog.querySelector('[data-external-config-text]').textContent = '';
    const labels = {open:'等待外部 Agent 返回结果', submitted:'结果已提交，请在正文中审查候选',cancelled:'任务已撤销',expired:'任务已过期，请重新建立任务'};
    dialog.querySelector('[data-external-state]').textContent = labels[task.status] || '任务状态暂不可读';
    if (exported) dialog.querySelector('[data-external-state]').textContent += ` · 第 ${exported.source.start} 段起，共 ${exported.source.blocks.length} 段`;
    importForm.reset(); controls();
    dialog.querySelector('[data-external-review]').hidden = task.status !== 'submitted';
  }
  async function history() {
    const result = await request(`tasks?work_id=${encodeURIComponent(scope.workId)}&scene_id=${encodeURIComponent(scope.sceneId)}`);
    const holder = dialog.querySelector('[data-external-history]'); holder.replaceChildren();
    if (!result.tasks.length) return;
    const label = document.createElement('p'); label.className = 'form-note'; label.textContent = '最近的任务'; holder.append(label);
    for (const item of result.tasks.slice(0,5)) {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'quiet';
      button.textContent = `${new Date(item.created_at).toLocaleString()} · ${{open:'等待结果',submitted:'已提交',cancelled:'已撤销',expired:'已过期'}[item.status] || item.status}`;
      button.addEventListener('click', () => run(async()=> {
        const current = await request(`tasks/${item.id}/status`);
        showTask(current, current.status === 'open' ? await request(`tasks/${item.id}/package`) : null);
        note(current.status === 'submitted' ? '返回正文可审查已有候选。' : '已恢复任务；关闭窗口不会撤销它。');
      })); holder.append(button);
    }
  }
  document.addEventListener('click', event => {
    if (!event.target.closest('[data-external-agent-open]')) return;
    event.preventDefault(); event.stopPropagation();
    const scene = typeof selectedScene === 'function' ? selectedScene() : null;
    if (!scene || !state.work) { toast('请先选择场景。',true); return; }
    if (!scene.current_revision_id) { toast('请先保存本场正文。',true); return; }
    scope = {workId:state.work.id, sceneId:scene.id}; task = packageValue = config = null;
    createForm.reset(); taskPanel.hidden = true; note('');
    dialog.querySelector('[data-external-scene]').textContent = scene.title;
    dialog.showModal(); run(history);
  });
  dialog.querySelector('[data-external-close]').addEventListener('click',()=>dialog.close());
  dialog.addEventListener('cancel',event=> {if(busy)event.preventDefault();});
  dialog.querySelector('[data-external-refresh]').addEventListener('click',()=>run(async()=> {
    const current = await request(`tasks/${task.id}/status`);
    showTask(current, current.status === 'open' ? await request(`tasks/${task.id}/package`) : null);
    await history(); note(current.status === 'submitted' ? '结果已返回，点击查看候选进行审查。' : '任务状态已更新。');
  }));
  dialog.querySelector('[data-external-review]').addEventListener('click',()=>run(async()=> {
    await loadWork(scope.workId,{resume:false}); dialog.close(); toast('请在正文中审查外部候选。');
  }));
  createForm.addEventListener('submit', event => {
    event.preventDefault(); if (!createForm.reportValidity()) return;
    run(async()=> {
      const result = await request('tasks',{work_id:scope.workId, scene_id:scope.sceneId, expected_version:state.work.version,
        instruction:createForm.elements.instruction.value, start:Number(createForm.elements.start.value), limit:Number(createForm.elements.limit.value)});
      showTask(result.task,result.package); await history(); note('任务已建立。导出给外部工具，或使用 MCP 连接。');
    });
  });
  dialog.querySelector('[data-external-download]').addEventListener('click',()=>run(async()=> {
    packageValue ||= await request(`tasks/${task.id}/package`);
    download(packageValue,`HaloCue-${task.id}.json`); note('已导出任务包；它包含当前选中的正文和人物资料。');
  }));
  dialog.querySelector('[data-external-mcp]').addEventListener('click',()=>run(async()=> {
    config = await request(`tasks/${task.id}/mcp-config?endpoint=${encodeURIComponent(location.origin)}`);
    dialog.querySelector('[data-external-config-text]').textContent = JSON.stringify(config,null,2);
    const details = dialog.querySelector('[data-external-config]'); details.hidden = false; details.open = true;
    note('配置仅供本机使用。外部 Agent 的费用与额度请在该服务中确认。');
  }));
  dialog.querySelector('[data-external-config-download]').addEventListener('click',()=> {if(config)download(config,'HaloCue-MCP.json');});
  dialog.querySelector('[data-external-revoke]').addEventListener('click',()=>run(async()=> {
    showTask(await request(`tasks/${task.id}/revoke`,{})); await history(); note('任务已撤销，旧连接和结果不能再提交。');
  }));
  async function submit(value) {
    if(value?.task_id !== task.id)throw new Error('结果属于其他任务，请先恢复对应任务。');
    await request('result',value); await loadWork(scope.workId,{resume:false});
    dialog.close(); toast('外部结果已生成候选，请在正文中审查后采纳。');
  }
  importForm.addEventListener('submit',event=> {
    event.preventDefault(); if(!importForm.reportValidity())return;
    run(()=>submit(JSON.parse(importForm.elements.result.value)));
  });
  dialog.querySelector('[data-external-file]').addEventListener('change',event=>run(async()=> {
    const file=event.target.files?.[0];if(!file)return;
    if(file.size>1000000)throw new Error('结果文件不能超过 1 MB。');
    await submit(JSON.parse(await file.text()));
  }));
})();
