/* Inline writer-model selection. Credentials stay on the local service. */
(() => {
  const escape=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
  let dialog,trigger,current=null,models=[],loadId=0,loading=false,pending=false,query='',error='',notice='';
  async function request(path,body){
    const response=await fetch('/api/v1/settings/'+path,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)})});
    const result=await response.json();
    if(!response.ok||result.ok===false)throw new Error(result.error?.message||'模型服务暂不可用');
    return result.data??result;
  }
  function position(){
    if(!dialog?.open)return;
    const rect=trigger?.isConnected?trigger.getBoundingClientRect():null;
    const width=Math.min(360,innerWidth-24),height=Math.min(490,innerHeight-32);
    dialog.style.width=width+'px';dialog.style.maxHeight=height+'px';
    dialog.style.left=Math.max(12,Math.min(innerWidth-width-12,(rect?.right||innerWidth-12)-width))+'px';
    dialog.style.top=Math.max(16,Math.min(innerHeight-dialog.offsetHeight-16,(rect?.top||innerHeight-16)-dialog.offsetHeight-10))+'px';
  }
  function syncLabels(model){
    document.querySelectorAll('[data-agent-model-picker]').forEach(button=>{
      const name=button.querySelector('.agent-model-name');if(name)name.textContent=model;
      button.setAttribute('aria-label',`选择写作模型，当前 ${model}`);
    });
  }
  function list(){
    const target=dialog.querySelector('[data-model-options]');
    const filtered=models.filter(item=>(item.model+' '+item.base_url).toLowerCase().includes(query.toLowerCase()));
    target.innerHTML=filtered.map(item=>`<button type="button" class="model-picker-option" data-select-writer="${escape(item.id)}" aria-pressed="${item.current}" ${pending||loading?'disabled':''}><span>${escape(item.model)}<small class="model-picker-endpoint">${escape(item.base_url)}</small></span><small>${item.current?'当前使用':'选择'}</small></button>`).join('')||`<p class="model-picker-empty">${loading?'正在读取已保存的模型…':query?'没有匹配的已保存模型':'还没有保存的模型，请先到设置中添加。'}</p>`;
  }
  function render(){
    const focused=dialog.contains(document.activeElement)&&document.activeElement.matches('[data-model-search]');
    const selection=focused?[document.activeElement.selectionStart,document.activeElement.selectionEnd]:null;
    const busy=loading||pending;
    dialog.innerHTML=`<header><div><h2 id="agentModelPickerTitle">选择写作模型</h2><p>${current?.model?`当前：${escape(current.model)}`:'读取当前连接'}</p></div><button type="button" class="model-picker-close" data-model-close aria-label="关闭模型选择">×</button></header><label class="model-picker-search"><span class="sr-only">搜索模型</span><input type="search" data-model-search placeholder="搜索模型名称" autocomplete="off" value="${escape(query)}" ${busy?'disabled':''}></label><p class="model-picker-status ${error?'is-error':''}" role="status">${escape(error||(pending?'正在验证并切换，成功后才会替换当前模型…':loading?'正在读取设置中保存的模型…':notice||'仅显示设置中已保存的模型。'))}</p><div class="model-picker-options" data-model-options role="group" aria-label="可用写作模型" aria-busy="${busy}"></div><footer><small>作用于所有作品后续的写作请求。选择时会发送一次连接测试。</small><div><button type="button" data-model-refresh ${busy?'disabled':''}>刷新列表</button><button type="button" data-model-settings ${pending?'disabled':''}>管理模型…</button></div></footer>`;
    list();position();
    if(dialog.open){const input=dialog.querySelector('[data-model-search]');if(!busy){input.focus({preventScroll:true});if(selection)input.setSelectionRange(...selection);}else dialog.querySelector('[data-model-close]').focus({preventScroll:true});}
  }
  async function load(){
    const id=++loadId;loading=true;error='';notice='';models=[];current=null;render();
    try{
      const result=await request('writing-model');if(id!==loadId)return;
      current=result.model;syncLabels(current?.model||'选择模型');
      models=(result.registered_models||[]).sort((a,b)=>Number(b.current)-Number(a.current));
    }catch(e){if(id===loadId){error=e.message;models=[];}}
    finally{if(id===loadId){loading=false;if(dialog.open)render();}}
  }
  async function choose(id){
    const selected=models.find(item=>item.id===id);
    if(pending||loading||!selected||selected.current)return;
    if(document.querySelector('#workConversationForm.is-running')){error='当前正在生成，请等本轮结束或先停止，再切换模型。';render();return;}
    pending=true;error='';render();
    try{
      const result=await request('writing-model:activate',{registered_model_id:id,expected_config_digest:current.config_digest});
      current=result.model;syncLabels(current.model);
      window.dispatchEvent(new CustomEvent('halocue:model-activated',{detail:result}));
      notice=`已切换为 ${current.model}`;
      if(dialog.open)dialog.close();
    }catch(e){
      try{const actual=await request('writing-model');current=actual.model;models=actual.registered_models||[];if(current?.model)syncLabels(current.model);}catch(_){}
      error=`切换未完成。${e.message}`;
    }
    finally{pending=false;if(dialog.open)render();}
  }
  function init(){
    if(dialog)return;
    dialog=document.createElement('dialog');dialog.id='agentModelPicker';dialog.className='agent-model-picker';dialog.setAttribute('aria-labelledby','agentModelPickerTitle');document.body.append(dialog);
    dialog.addEventListener('close',()=>{if(!pending){loadId++;loading=false;}trigger?.setAttribute('aria-expanded','false');if(trigger?.isConnected)trigger.focus({preventScroll:true});});
    dialog.addEventListener('click',event=>{
      const item=event.target.closest('[data-select-writer]');if(item){void choose(item.dataset.selectWriter);return;}
      if(event.target.closest('[data-model-close]'))dialog.close();
      if(event.target.closest('[data-model-refresh]'))void load();
      if(event.target.closest('[data-model-settings]')){dialog.close();document.querySelector('#openSettingsButton')?.click();}
      if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();}
    });
    dialog.addEventListener('input',event=>{if(event.target.matches('[data-model-search]')){query=event.target.value;list();}});
    window.addEventListener('resize',position);
  }
  document.addEventListener('click',event=>{
    const button=event.target.closest('[data-agent-model-picker]');if(!button)return;
    event.preventDefault();init();trigger=button;query='';trigger.setAttribute('aria-expanded','true');
    render();dialog.showModal();position();
    if(!pending)void load();
  });
})();
