(() => {
  'use strict';
  const panel = document.getElementById('mcpWorkspaceConnection');
  if (!panel) return;
  const form = panel.querySelector('[data-mcp-connect]');
  const message = panel.querySelector('[data-mcp-message]');
  let busy = false, config = null;
  const request = (path, body) => api('/mcp/'+path, body === undefined ? {} : {method:'POST',body:JSON.stringify(body)});
  function note(text, failed=false) {message.textContent=text;message.dataset.failed=String(failed);}
  async function run(action) {
    if(busy)return;busy=true;panel.querySelectorAll('button,input,select').forEach(el=>{el.disabled=true;});
    try {await action();}catch(error){note(error.message,true);}
    finally {busy=false;panel.querySelectorAll('button,input,select').forEach(el=>{el.disabled=false;});}
  }
  function render(value) {
    config=null;panel.querySelector('[data-mcp-config]').hidden=true;panel.querySelector('[data-mcp-config-text]').textContent='';
    panel.querySelector('[data-mcp-summary]').textContent=value.connected?`已连接 · ${value.allowed_work_ids.length} 个作品 · ${(value.allowed_run_ids||[]).length} 个 AA 任务`:'未连接';
    const holder=panel.querySelector('[data-mcp-works]');holder.replaceChildren();
    for(const work of value.works){
      const label=document.createElement('label');const checkbox=document.createElement('input');
      checkbox.type='checkbox';checkbox.name='work_ids';checkbox.value=work.id;checkbox.checked=value.allowed_work_ids.includes(work.id);
      const title=document.createElement('span');title.textContent=work.title;label.append(checkbox,title);holder.append(label);
    }
    if(!value.works.length)holder.textContent='暂无作品';
    const tasks=panel.querySelector('[data-mcp-productions]');tasks.replaceChildren();
    for(const task of value.productions||[]){
      const label=document.createElement('label'),input=document.createElement('input'),title=document.createElement('span');
      input.type='checkbox';input.name='run_ids';input.value=task.id;input.checked=(value.allowed_run_ids||[]).includes(task.id);
      title.textContent=task.title;label.append(input,title);tasks.append(label);
    }
    if(!(value.productions||[]).length)tasks.textContent='先在 AA 制作中建立任务，再刷新连接。';
    panel.querySelector('[data-mcp-action=disconnect]').hidden=!value.connected;
    if(!value.connected){config=null;panel.querySelector('[data-mcp-config]').hidden=true;panel.querySelector('[data-mcp-config-text]').textContent='';}
  }
  async function readConfig(open=false){
    config=null;
    panel.querySelector('[data-mcp-config-text]').textContent='';
    panel.querySelector('[data-mcp-instructions]').textContent='正在生成配置…';
    const profile=await request('config?endpoint='+encodeURIComponent(location.origin)+'&client='+encodeURIComponent(panel.querySelector('[data-mcp-client]').value));
    config=profile;
    panel.querySelector('[data-mcp-config-text]').textContent=profile.text;
    panel.querySelector('[data-mcp-instructions]').textContent=profile.instructions;
    const details=panel.querySelector('[data-mcp-config]');details.hidden=false;details.open=open;
    note('配置已生成；按上方说明添加后，重新打开 Agent 会话。');
  }
  panel.querySelector('[data-mcp-client]').addEventListener('change',()=>run(()=>readConfig(true)));
  async function refresh(){
    const value=await request('settings');render(value);if(value.connected)await readConfig();
    note(value.connected?'在 Agent 软件中添加配置后，直接描述要操作的作品与场景。':'选择作品或 AA 制作任务后启用，配置一次即可使用。');
  }
  form.addEventListener('submit',event=>{
    event.preventDefault();run(async()=>{
      const work_ids=[...form.querySelectorAll('input[name=work_ids]:checked')].map(el=>el.value);
      const run_ids=[...form.querySelectorAll('input[name=run_ids]:checked')].map(el=>el.value);
       if(!work_ids.length&&!run_ids.length)throw new Error('至少选择一个作品或 AA 制作任务。');
      render(await request('connect',{work_ids,run_ids}));await readConfig(true);
      note('已启用。把配置添加到外部 Agent，之后无需任务包交换；模型调用由外部软件负责。');
    });
  });
  panel.addEventListener('click',event=>{
    const action=event.target.closest('[data-mcp-action]')?.dataset.mcpAction;if(!action)return;
    run(async()=>{
      if(action==='refresh')return refresh();
      if(action==='disconnect'){render(await request('disconnect',{}));note('连接已断开，旧配置不能继续操作。');return;}
      if(!config)throw new Error('先启用连接并生成配置。');
      const text=config.text;
      if(action==='copy'){await navigator.clipboard.writeText(text);note('已复制 MCP 配置。');return;}
      const url=URL.createObjectURL(new Blob([text],{type:config.content_type}));
      const link=document.createElement('a');link.href=url;link.download=config.filename;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);note('配置已导出。');
    });
  });
  const settings=document.getElementById('settingsDialog');
  new MutationObserver(()=>{if(settings.open&&!busy)run(refresh);}).observe(settings,{attributes:true,attributeFilter:['open']});
})();
