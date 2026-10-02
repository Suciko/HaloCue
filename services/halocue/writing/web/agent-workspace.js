/* Agent interaction polish: scoped to ideation, no writes to project state. */
(() => {
  const disclosures = new Map();
  let lastScope = '';
  function scope() { return `${new URL(location.href).searchParams.get('work_id') || ''}:${document.querySelector('[data-agent-thread]')?.dataset.agentThread || ''}`; }
  function enhance() {
    if(!['works','writing'].includes(document.querySelector('#app')?.dataset.surface))return;
    const canvas=document.querySelector('.hc-idea-canvas');
    if(!canvas)return;
    const key=scope();
    if(key!==lastScope){disclosures.clear();lastScope=key;}
    const composer=canvas.querySelector('#workConversationForm');
    const glyph=(path)=>`<svg class="composer-control-icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="${path}"></path></svg>`;
    const attach=composer?.querySelector('.attachment-menu>summary');
    if(attach&&!attach.querySelector('svg'))attach.innerHTML=glyph('M12 5v14M5 12h14');
    const permission=composer?.querySelector('.permission-menu>summary');
    if(permission&&!permission.querySelector('svg'))permission.insertAdjacentHTML('afterbegin',glyph('m12 3 8 3v5c0 5-8 10-8 10S4 16 4 11V6l8-3Zm-4 9 3 3 5-6'));
    const send=composer?.querySelector('.agent-send-icon');
    if(send&&!send.querySelector('svg'))send.innerHTML=glyph('M12 19V5m-6 6 6-6 6 6');
    const input=canvas.querySelector('#workConversationForm textarea');
    if(input&&!input.dataset.agentEnhanced){
      input.dataset.agentEnhanced='true';
      const resize=()=>{input.form.classList.toggle('has-input',Boolean(input.value.trim()));input.style.height='auto';input.style.height=`${Math.min(180,Math.max(42,input.scrollHeight))}px`;const jump=canvas.querySelector('[data-agent-jump-latest]');if(jump)jump.style.bottom=`${canvas.querySelector('.work-agent-bottom').offsetHeight+12}px`;};
      input.addEventListener('input',resize);
      requestAnimationFrame(resize);
    }
    const scroll=canvas.querySelector('[data-work-discussion-scroll]');
    const jump=canvas.querySelector('[data-agent-jump-latest]');
    if(scroll&&jump&&!scroll.dataset.agentEnhanced){
      scroll.dataset.agentEnhanced='true';
      const update=()=>{jump.style.bottom=`${canvas.querySelector('.work-agent-bottom').offsetHeight+12}px`;jump.hidden=scroll.scrollHeight-scroll.scrollTop-scroll.clientHeight<100;};
      scroll.addEventListener('scroll',update,{passive:true});
      jump.addEventListener('click',()=>{scroll.scrollTo({top:scroll.scrollHeight,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});});
      // Runs after the main renderer restores reading position.
      requestAnimationFrame(update);
    }
    canvas.querySelectorAll('details[data-agent-disclosure]').forEach(details=>{
      if(details.dataset.agentEnhanced)return;
      details.dataset.agentEnhanced='true';
      const id=details.dataset.agentDisclosure;
      if(disclosures.has(id))details.open=disclosures.get(id);
      details.addEventListener('toggle',()=>{disclosures.set(id,details.open);const label=details.querySelector('summary em');if(label)label.textContent=details.open?'收起':'展开';});
    });
  }
  const menus=()=>document.querySelectorAll('#app[data-surface="works"] :is(.attachment-menu,.permission-menu,.agent-composer-more,.thread-actions)[open]');
  document.addEventListener('click',async event=>{
    for(const menu of menus())if(!menu.contains(event.target))menu.open=false;
    const button=event.target.closest('[data-agent-copy-reply]');
    if(!button)return;
    const prose=button.closest('.message-bubble')?.querySelector('.agent-prose');
    const status=button.parentElement.querySelector('[data-agent-copy-status]');
    if(!prose||!status)return;
    try{await navigator.clipboard.writeText(prose.innerText);status.textContent='已复制';}
    catch(_){status.textContent='复制未成功，请选中文字复制';}
  });
  document.addEventListener('keydown',event=>{
    if(event.key!=='Escape')return;
    const open=[...menus()];
    if(!open.length)return;
    event.preventDefault();
    for(const menu of open)menu.open=false;
    open[open.length-1].querySelector('summary')?.focus({preventScroll:true});
  },true);
  window.HaloCueRouter?.registerRenderHook('agent-workspace',enhance);
  enhance();
})();
