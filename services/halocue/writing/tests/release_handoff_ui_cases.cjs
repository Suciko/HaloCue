// Actual production renderer/controller and delegated click handler in Chromium.
// Only unrelated release-gate dependencies and HTTP IO are synthetic.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const [name, sourcePath, runtime, executablePath, screenshotDir] = process.argv.slice(2);
const {chromium} = require(runtime);
const source = fs.readFileSync(sourcePath, 'utf8');
const renderStart = source.indexOf('function renderRelease(el){');
const renderSource = source.slice(renderStart, source.indexOf('\nfunction renderInspector', renderStart));
const navigationStart = source.indexOf('const renderReleaseBeforeProductionNavigation=');
const navigationSource = source.slice(navigationStart, source.indexOf("\nregisterAppClick", navigationStart));
const controllerStart = source.indexOf('const ReleaseHandoffUI =');
const controllerSource = controllerStart < 0 ? '' : source.slice(controllerStart, source.indexOf('// In the integrated shell', controllerStart));
const integrityStart = source.indexOf('function decorateReleaseIntegrity(el){');
const integritySource = source.slice(integrityStart, source.indexOf('\nrenderRelease=function', integrityStart));
const integration = fs.readFileSync(path.resolve(path.dirname(sourcePath), '../../integrated/static/integration-shell.js'), 'utf8');
const integrationStart = integration.indexOf('    document.addEventListener("click", async event => {');
const integrationSource = integration.slice(integrationStart, integration.indexOf('    }, true);', integrationStart) + '    }, true);'.length);
const clickSource = source.split('\n').find(line => line.startsWith("registerAppClick(async event=>{const b="));
assert(renderSource && navigationSource && clickSource, 'Production release boundaries must exist');
const dispatcherStart = source.indexOf('function handleAppRouteClick(event){');
const dispatcherSource = source.slice(dispatcherStart, source.indexOf("window.addEventListener('popstate'", dispatcherStart));
const dispatcherSetup = `
let hcCommandDepth=0; const hcClickHandlers=[],hcClaimedEvents=new WeakSet();
function registerAppClick(handler,priority=20){hcClickHandlers.push({handler,priority,order:hcClickHandlers.length});}
function claimAppEvent(event){hcClaimedEvents.add(event);}
function routeUrl(){return '/fixture';} function syncAppRoute(){}
function captureClientError(error){throw error;}
function navigateRoute(target){if(target.section==='production')HaloCueProductionEmbed.open({...target,workId:state.work.id});}
window.HaloCueRouter={navigate:navigateRoute};
`;
const retry = '[data-retry-handoff]';
const proof = '[data-release-asset-status]';
const open = '[data-open-production]';
const cases = {
  async pending_retry_complete_keeps_open_task(h) {
    await h.render();
    await h.expectProof('待确认');
    assert.equal(await h.page.locator(open).getAttribute('data-open-production'), 'run-r1');
    assert.equal(await h.page.locator(open).isEnabled(), true);
    await h.page.locator(open).click();
    assert.deepEqual(await h.page.evaluate(() => io.opens.map(({runId,workId,releaseId}) => ({runId,workId,releaseId}))), [{runId:'run-r1',workId:'a',releaseId:'r1'}]);
    assert.equal(await h.count('POST'), 0, 'Rendering must never replay automatically');
    await h.page.locator(retry).click();
    await h.waitPosts(1);
    assert.equal(await h.page.locator(retry).isDisabled(), true);
    assert.equal(await h.page.locator(open).isEnabled(), true, 'Navigation stays independent');
    await h.complete();
    await h.expectProof('副本已确认');
    assert.match(await h.page.locator(proof).innerText(), /2\s*\/\s*2/);
    assert.equal(await h.page.locator(retry).count(), 0);
    assert.equal(await h.page.locator(open).getAttribute('data-release-id'), 'r1');
    assert.deepEqual(await h.page.evaluate(() => io.calls.find(c => c.method === 'POST').body), {});
    assert.equal(await h.page.evaluate(() => io.loads.length), 0);
  },
  async failed_retry_is_actionable_and_duplicate_clicks_submit_once(h) {
    await h.render(); await h.expectProof('待确认');
    await h.page.locator(retry).click();
    await h.page.locator(retry).dispatchEvent('click');
    assert.equal(await h.count('POST'), 1);
    await h.page.evaluate(() => io.pendingPost[0].reject(new Error('<img src=x onerror="window.pwned=1">离线')));
    await h.expectProof('离线');
    assert.equal(await h.page.locator(retry).isEnabled(), true);
    assert.equal(await h.page.locator(`${proof} img`).count(), 0);
    assert.equal(await h.page.evaluate(() => window.pwned), undefined);
    await h.page.locator(retry).click(); await h.waitPosts(2);
    await h.complete(1); await h.expectProof('副本已确认');
  },
  async hanging_status_is_bounded_and_independent(h) {
    await h.page.evaluate(() => {
      io.holdGet.add('r1');
      io.status.r2 = io.makeStatus('r2', 'complete');
    });
    await h.render('a', ['r1', 'r2']);
    await h.page.waitForFunction(() => document.querySelectorAll('[data-release-asset-status]')[1]?.textContent.includes('副本已确认'));
    await h.page.locator('#unrelated').click();
    assert.equal(await h.page.evaluate(() => io.unrelated), 1);
    assert.equal(await h.count('POST'), 0);
    await h.page.evaluate(() => {
      const timers = [...io.timers.values()].filter(t => t.ms <= 5000);
      if (!timers.length) throw new Error('Status read must have its own <=5s bound');
      for (const timer of timers) timer.fn();
    });
    await h.expectProof('超时', 0);
    assert.equal(await h.page.locator(retry).first().isEnabled(), true);
    assert.equal(await h.page.evaluate(() => io.pendingGet[0].signal.aborted), true);
    await h.page.evaluate(() => io.pendingGet[0].resolve(io.makeStatus('r1', 'complete')));
    await h.flush(); await h.expectProof('超时', 0);
  },
  async stale_status_after_rerender_or_work_switch_is_ignored(h) {
    await h.page.evaluate(() => io.holdGet.add('r1'));
    await h.render();
    await h.page.waitForFunction(() => io.pendingGet.length === 1);
    await h.page.evaluate(() => {io.holdGet.clear(); io.status.r1 = io.makeStatus('r1', 'complete'); renderRelease(document.querySelector('#workspace'));});
    await h.expectProof('副本已确认');
    await h.page.evaluate(() => io.pendingGet[0].resolve(io.makeStatus('r1', 'pending')));
    await h.flush(); await h.expectProof('副本已确认');
    await h.page.evaluate(() => io.holdGet.add('r1'));
    await h.render(); await h.page.waitForFunction(() => io.pendingGet.length === 2);
    await h.render('b', ['r2']); await h.expectProof('待确认');
    const before = await h.page.locator('#workspace').innerHTML();
    await h.page.evaluate(() => io.pendingGet[1].reject(new Error('旧作品读取失败')));
    await h.flush();
    assert.equal(await h.page.locator('#workspace').innerHTML(), before);
    assert.equal(await h.page.evaluate(() => io.toasts.length), 0);
  },
  async retry_completion_cannot_switch_work(h) {
    await h.render(); await h.expectProof('待确认');
    await h.page.locator(retry).click(); await h.waitPosts(1);
    await h.render('b', ['r2']); await h.expectProof('待确认');
    const before = await h.page.locator('#workspace').innerHTML();
    await h.complete(); await h.flush();
    assert.equal(await h.page.evaluate(() => state.work.id), 'b');
    assert.equal(await h.page.locator('#workspace').innerHTML(), before);
    assert.equal(await h.page.evaluate(() => io.loads.length + io.toasts.length), 0);
  },
  async rerender_during_retry_keeps_single_submission(h) {
    await h.render(); await h.expectProof('待确认');
    await h.page.locator(retry).click(); await h.waitPosts(1);
    await h.page.evaluate(() => renderRelease(document.querySelector('#workspace')));
    await h.page.locator(retry).dispatchEvent('click');
    assert.equal(await h.count('POST'), 1);
    assert.equal(await h.page.locator(retry).isDisabled(), true);
    await h.complete(); await h.expectProof('副本已确认');
    assert.equal(await h.page.locator(retry).count(), 0);
    assert.equal(await h.page.evaluate(() => io.toasts.length), 1);
  },
  async first_handoff_preserves_view_and_reports_pending_proof(h) {
    await h.page.evaluate(() => io.status.r1 = io.makeStatus('r1', 'not_handed_off', null));
    await h.render('a', ['r1'], false);
    await h.expectProof('尚未交接');
    await h.page.locator('[data-handoff]').click(); await h.waitPosts(1);
    await h.page.locator('[data-handoff]').dispatchEvent('click');
    assert.equal(await h.count('POST'), 1);
    await h.page.evaluate(() => {
      io.status.r1 = io.makeStatus('r1', 'pending');
      io.pendingPost[0].resolve({release_id:'r1', production_run_id:'run-r1', asset_handoff:{status:'pending', confirmed_count:0, expected_count:2}});
    });
    await h.expectProof('待确认');
    assert.equal(await h.page.locator(open).isEnabled(), true);
    assert.equal(await h.page.locator(retry).isEnabled(), true);
    assert.equal(await h.page.evaluate(() => state.stage), 'release');
    assert.equal(await h.page.evaluate(() => io.loads.length), 0);
    assert.match(await h.page.evaluate(() => io.toasts.at(-1).message), /待确认/);
    assert.doesNotMatch(await h.page.evaluate(() => io.toasts.at(-1).message), /交接完成|副本已确认/);
  },
  async offline_unknown_and_invalid_proof_are_not_complete(h) {
    for (const shape of ['offline', 'wrong-schema', 'wrong-release', 'wrong-run', 'wrong-count', 'unknown']) {
      await h.page.evaluate(shape => {
        const value = io.makeStatus('r1', 'pending');
        if (shape === 'offline') value.capability = {status:'offline', reason:'<svg onload=alert(1)>服务断开'};
        if (shape === 'wrong-schema') value.schema_version = 'unknown/9';
        if (shape === 'wrong-release') value.release_id = 'other';
        if (shape === 'wrong-run') value.production_run_id = 'wrong';
        if (shape === 'wrong-count') {value.status = 'complete'; value.copied_count = 1;}
        if (shape === 'unknown') value.status = 'mystery';
        io.status.r1 = value;
      }, shape);
      await h.render();
      await h.page.waitForFunction(() => !!document.querySelector('[data-retry-handoff]:not(:disabled)'));
      assert.doesNotMatch(await h.page.locator(`${proof} header`).innerText(), /副本已确认/);
      assert.equal(await h.page.locator(`${proof} svg`).count(), 0);
      assert.equal(await h.page.locator(open).isEnabled(), true);
    }
    assert.equal(await h.count('POST'), 0);
  },
  async proof_does_not_remove_frozen_integrity_details(h) {
    await h.page.evaluate(() => state.releaseDetails.r1 = {manifest:{scenes:[],dependency_refs:[],gate_snapshot_ids:[]}});
    await h.render(); await h.expectProof('待确认');
    assert.equal(await h.page.locator('.release-integrity-summary details').count(), 1, 'New proof must not suppress existing frozen manifest verification');
    assert.equal(await h.page.locator(proof).count(), 1);
  },
  async detached_status_and_retry_failures_do_not_touch_new_view(h) {
    await h.render(); await h.expectProof('待确认');
    await h.page.locator(retry).click(); await h.waitPosts(1);
    await h.page.evaluate(() => {state.stage='overview';document.querySelector('#workspace').innerHTML='<h2>作品概览</h2>';});
    await h.page.evaluate(() => io.pendingPost[0].reject(new Error('旧交接失败')));
    await h.flush();
    assert.equal(await h.page.locator('#workspace').innerText(), '作品概览');
    assert.equal(await h.page.evaluate(() => io.toasts.length), 0);
    assert.equal(await h.page.evaluate(() => state.feedbackError), undefined);
  },
  async partial_replay_remains_pending_and_recoverable(h) {
    await h.render(); await h.expectProof('待确认');
    await h.page.locator(retry).click(); await h.waitPosts(1);
    await h.page.evaluate(() => {
      io.status.r1={...io.makeStatus('r1','pending'),copied_count:1};
      io.pendingPost[0].resolve({release_id:'r1',production_run_id:'run-r1',asset_handoff:{status:'pending',confirmed_count:1,expected_count:2}});
    });
    await h.expectProof('1 / 2');
    assert.equal(await h.page.locator(retry).isEnabled(), true);
    assert.match(await h.page.evaluate(() => io.toasts.at(-1).message), /待确认/);
    assert.equal(await h.count('POST'), 1);
  },
  async http_failure_and_hanging_json_are_bounded(h) {
    await h.page.evaluate(() => io.httpError = '<img src=x>服务不可用');
    await h.render(); await h.expectProof('服务不可用');
    assert.equal(await h.page.locator(retry).isEnabled(), true);
    assert.equal(await h.page.locator(`${proof} img`).count(), 0);
    await h.page.evaluate(() => {io.httpError=null;io.holdJson=true;});
    await h.render();
    await h.page.evaluate(() => {for(const t of io.timers.values())t.fn();});
    await h.expectProof('超时');
    assert.equal(await h.page.locator(open).isEnabled(), true);
    assert.equal(await h.count('POST'), 0);
  },
  async returning_to_work_during_retry_reads_its_own_status(h) {
    await h.render(); await h.expectProof('待确认');
    await h.page.locator(retry).click(); await h.waitPosts(1);
    await h.render('b', ['r2']); await h.expectProof('待确认');
    await h.render('a', ['r1']);
    assert.equal(await h.page.locator(retry).isDisabled(), true);
    await h.complete();
    await h.expectProof('副本已确认');
    assert.equal(await h.page.evaluate(() => io.toasts.length), 0, 'The old work object must not publish a success toast into a newly selected view');
    assert.equal(await h.page.evaluate(() => io.loads.length), 0);
  },
  async late_pre_handoff_status_cannot_erase_success(h) {
    await h.page.evaluate(() => io.holdGet.add('r1'));
    await h.render('a',['r1'],false);
    await h.page.waitForFunction(() => io.pendingGet.length===1);
    await h.page.locator('[data-handoff]').click(); await h.waitPosts(1);
    await h.page.evaluate(() => io.holdGet.clear());
    await h.complete(); await h.expectProof('副本已确认');
    await h.page.evaluate(() => io.pendingGet[0].resolve(io.makeStatus('r1','not_handed_off',null)));
    await h.flush(); await h.expectProof('副本已确认');
    assert.equal(await h.page.locator(open).isEnabled(), true);
  },
  async invalid_replay_response_remains_actionable(h) {
    await h.render(); await h.expectProof('待确认');
    await h.page.locator(retry).click(); await h.waitPosts(1);
    await h.page.evaluate(() => io.pendingPost[0].resolve({release_id:'r1',production_run_id:'other-run',asset_handoff:{status:'complete',confirmed_count:2,expected_count:2}}));
    await h.expectProof('不一致');
    assert.equal(await h.page.locator(retry).isEnabled(), true);
    assert.equal(await h.page.locator(open).getAttribute('data-open-production'), 'run-r1');
    assert.equal(await h.page.evaluate(() => io.toasts.length), 0);
  },
  async paper_card_renders_at_desktop_and_mobile_widths(h) {
    for (const file of ['styles.css','tokens.css','shell.css']) {
      await h.page.addStyleTag({content:fs.readFileSync(path.join(path.dirname(sourcePath),file),'utf8')});
    }
    await h.page.evaluate(() => {
      document.querySelector('#workspace').className='workspace';
      state.releaseDetails.r1={manifest:{scenes:[],dependency_refs:[],gate_snapshot_ids:[]}};
    });
    await h.render(); await h.expectProof('待确认');
    for (const width of [1000,390]) {
      await h.page.setViewportSize({width,height:1100});
      assert.equal(await h.page.locator(open).isVisible(), true);
      assert.equal(await h.page.locator(retry).isVisible(), true);
      const layout=await h.page.locator('[data-release-card]').evaluate(card => ({
        width:card.clientWidth,scroll:card.scrollWidth,
        buttons:[...card.querySelectorAll('button')].map(node=>({x:node.getBoundingClientRect().x,right:node.getBoundingClientRect().right})),
      }));
      assert(layout.scroll <= layout.width + 1, 'Release card must not overflow horizontally');
      assert(layout.buttons.every(button=>button.x>=0 && button.right<=width), 'Both actions must remain inside the viewport');
      if (screenshotDir) {
        fs.mkdirSync(screenshotDir,{recursive:true});
        await h.page.screenshot({path:path.join(screenshotDir,`release-proof-${width}.png`),fullPage:true});
      }
    }
  },
  async not_required_and_complete_do_not_offer_replay(h) {
    for (const status of ['not_required', 'complete']) {
      await h.page.evaluate(status => io.status.r1 = io.makeStatus('r1', status), status);
      await h.render();
      await h.expectProof(status === 'complete' ? '副本已确认' : '无需');
      assert.equal(await h.page.locator(retry).count(), 0);
      assert.equal(await h.page.locator(open).isEnabled(), true);
    }
    assert.equal(await h.count('POST'), 0);
  },
};

(async () => {
  assert(cases[name], `Unknown case: ${name}`);
  const browser = await chromium.launch({headless:true, executablePath});
  try {
    const page = await browser.newPage();
    page.setDefaultTimeout(2500);
    const errors = [], external = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', route => {external.push(route.request().url()); return route.abort();});
    await page.setContent('<button id="unrelated">其他操作</button><main id="workspace"></main>');
    await page.evaluate(() => {
      window.io = {
        calls:[], toasts:[], loads:[], opens:[], pendingGet:[], pendingPost:[], holdGet:new Set(), status:{}, timers:new Map(), unrelated:0,
        makeStatus(id, status, run = `run-${id}`) {return {schema_version:'production-asset-status/1.0', release_id:id, production_run_id:run, status, expected_count:status === 'not_required' ? 0 : 2, copied_count:status === 'complete' ? 2 : 0, references:[], capability:{status:'supported'}};},
      };
      window.state = {work:null, stage:'release', surface:'works', releaseDetails:{}, releaseDetailErrors:{}};
      window.esc = value => {const node=document.createElement('span');node.textContent=String(value??'');return node.innerHTML.replaceAll('"','&quot;').replaceAll("'",'&#39;');};
      window.scenes = () => [];
      window.requestReleaseDetails = () => {};
      window.shortDigest = value => String(value || '');
      window.params = new URLSearchParams();
      window.initialProductionNavigationCancelled = false;
      window.waitFor = async getter => getter();
      window.HaloCueProductionEmbed = {open: context => io.opens.push(context)};
      window.releaseSceneRevisionRefs = () => [];
      window.releaseDependencyRefs = () => [];
      window.latestWorkGate = () => null;
      window.frame = (kicker, title, lede, body) => `<div class="workspace-inner"><p class="eyebrow">${kicker}</p><h2>${title}</h2><p class="lede">${lede}</p>${body}</div>`;
      window.toast = (message, bad) => io.toasts.push({message,bad});
      window.setBusy = () => {};
      window.loadWork = async id => {io.loads.push(id);state.work={id};state.stage='overview';};
      window.fetch = async (url, options={}) => {
        const method = options.method || 'GET';
        const id = decodeURIComponent(url.split('/releases/')[1]?.split('/')[0] || '');
        io.calls.push({url, method, body:options.body ? JSON.parse(options.body) : null});
        let data;
        if (method === 'POST' || io.holdGet.has(id)) {
          data = await new Promise((resolve,reject) => (method === 'POST' ? io.pendingPost : io.pendingGet).push({id,resolve,reject,signal:options.signal}));
        } else data = io.status[id] || io.makeStatus(id, 'pending');
        return {ok:!io.httpError, status:io.httpError?503:200, json:async () => io.holdJson ? new Promise(() => {}) : io.httpError ? {ok:false,error:{message:io.httpError}} : {ok:true,data}};
      };
      window.api = async (path, options) => (await (await fetch('/api/v1'+path, options)).json()).data;
      const nativeTimeout = window.setTimeout.bind(window), nativeClear = window.clearTimeout.bind(window);
      let nextTimer = -1;
      window.setTimeout = (fn,ms,...args) => {
        if (ms === 5000) {const id=nextTimer--;io.timers.set(id,{fn,ms});return id;}
        return nativeTimeout(fn,ms,...args);
      };
      window.clearTimeout = id => {if (id<0) io.timers.delete(id);else nativeClear(id);};
      document.querySelector('#unrelated').addEventListener('click', () => io.unrelated++);
    });
    await page.addScriptTag({content:dispatcherSetup+'\n'+dispatcherSource+'\n'+integrationSource+'\n'+renderSource+'\n'+controllerSource+'\n'+navigationSource+'\n'+integritySource+'\n'+clickSource+"\nconst renderBeforeTestIntegrity=renderRelease;renderRelease=function(el){renderBeforeTestIntegrity(el);decorateReleaseIntegrity(el)};"});
    const h = {
      page,
      async render(workId='a', ids=['r1'], linked=true) {
        await page.evaluate(({workId,ids,linked}) => {
          state.work={id:workId, releases:ids.map(id => ({id,display_version:id,production_run_id:linked?`run-${id}`:null,source_revision_ids_json:'[]'}))};
          state.stage='release';renderRelease(document.querySelector('#workspace'));
        }, {workId,ids,linked});
      },
      async expectProof(text, index=0) {await page.waitForFunction(({text,index}) => document.querySelectorAll('[data-release-asset-status]')[index]?.textContent.includes(text), {text,index});},
      async count(method) {return page.evaluate(method => io.calls.filter(c => c.method===method).length, method);},
      async waitPosts(count) {await page.waitForFunction(count => io.pendingPost.length === count, count);},
      async flush() {await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));},
      async complete(index=0) {await page.evaluate(index => {
        io.status.r1=io.makeStatus('r1','complete');
        io.pendingPost[index].resolve({release_id:'r1',production_run_id:'run-r1',asset_handoff:{status:'complete',confirmed_count:2,expected_count:2}});
      }, index);},
    };
    await cases[name](h);
    assert.deepEqual(errors, [], 'No unhandled browser errors');
    assert.deepEqual(external, [], 'All transport must stay synthetic');
    console.log(JSON.stringify({case:name,passed:true,external_requests:0,real_dom:true}));
  } finally {await browser.close();}
})().catch(error => {console.error(error.stack);process.exitCode=1;});
