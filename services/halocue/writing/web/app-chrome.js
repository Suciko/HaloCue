/* Shared application chrome. No project mutation or workspace-specific state. */
(() => {
  function enhanceNavigation(){
    // One consistent outline icon set; visible labels and accessible names stay intact.
    const icons={projects:'M3 5h7l2 2h9v13H3V5Zm4 6h10M7 15h6',works:'M4 5h16v11H9l-5 4V5Z',writing:'m4 17 1 3 3-1L20 7l-4-4L4 15v2Zm9-11 4 4',production:'M4 5h16v14H4V5Zm0 4h16M8 5v4m8-4v4m-6 3 5 3-5 2v-5Z',assets:'M4 4h16v16H4V4Zm0 12 5-5 4 4 3-3 4 4M15 8h1',references:'M4 5h6l2 2h8v13H4V5Z',tasks:'M8 5h12M8 12h12M8 19h12M3 5h1m-1 7h1m-1 7h1',feedback:'M4 4h16v13H9l-5 3V4Zm8 4v4m0 2v1',help:'M9 8a3 3 0 0 1 6 0c0 2-3 2-3 5m0 3v1M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Z',settings:'M4 6h16M4 12h16M4 18h16M8 3v6m8 0v6m-6 0v6', 'open-creation':'M4 5h16v11H9l-5 4V5Z'};
    document.querySelectorAll('.primary-nav .nav-item').forEach(button=>{
      const key=button.dataset.section||button.dataset.action;
      if(!button.title)button.title=button.textContent.trim();
      if(!icons[key]||button.querySelector('.agent-nav-icon'))return;
      button.insertAdjacentHTML('afterbegin',`<svg class="agent-nav-icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="${icons[key]}"></path></svg>`);
    });

  }
  window.HaloCueRouter?.registerRenderHook('app-chrome',enhanceNavigation);
  enhanceNavigation();
})();
