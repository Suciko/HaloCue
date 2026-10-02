/* A readable, deterministic view of the verified knowledge projection. */
(function(){
  'use strict';
  const WIDTH=760,HEIGHT=420;
  const sessions=new WeakMap();
  const dimensions=count=>({width:Math.max(WIDTH,Math.ceil(Math.sqrt(count/12)*WIDTH)),height:Math.max(HEIGHT,Math.ceil(Math.sqrt(count/12)*HEIGHT))});
  const escape=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const typeName={character:'人物',entity:'世界观',rule:'规则',event:'事件',fact:'事实'};
  const clamp=(value,low,high)=>Math.max(low,Math.min(high,value));

  function visibleGraph(nodes,edges,filter='all',focusId=''){
    const known=new Set(nodes.map(node=>node.id));
    const focus=known.has(focusId)?focusId:'';
    const shown=focus
      ?new Set([focus,...edges.filter(edge=>edge.from===focus||edge.to===focus).flatMap(edge=>[edge.from,edge.to])])
      :new Set(nodes.filter(node=>filter==='all'||node.type===filter).map(node=>node.id));
    return {
      nodes:nodes.filter(node=>shown.has(node.id)),
      edges:edges.filter(edge=>known.has(edge.from)&&known.has(edge.to)&&shown.has(edge.from)&&shown.has(edge.to)),
      focus,
    };
  }

  function layout(nodes,edges,focusId=''){
    const {width,height}=dimensions(nodes.length),positions=new Map(),compact=nodes.length<=8;
    if(!nodes.length)return positions;
    const ordered=[...nodes].sort((a,b)=>a.id.localeCompare(b.id));
    const focus=ordered.some(node=>node.id===focusId)?focusId:'';
    const orbit=ordered.filter(node=>node.id!==focus);
    if(focus)positions.set(focus,{x:width/2,y:height/2});
    if(nodes.length===1){positions.set(nodes[0].id,{x:width/2,y:height/2});return positions}
    const radiusX=compact?Math.min(178,106+nodes.length*9):width/2-100;
    const radiusY=compact?Math.min(126,72+nodes.length*6):height/2-65;
    const typeOrder={character:0,entity:1,rule:2,event:3,fact:4};
    const groups=compact&&!focus?[...new Set(orbit.map(node=>node.type||'other'))].sort((a,b)=>(typeOrder[a]??9)-(typeOrder[b]??9)||a.localeCompare(b)):[];
    if(groups.length>1){
      const groupGap=Math.min(218,(width-190)/Math.max(1,groups.length-1));
      const groupByType=new Map(groups.map(type=>[type,orbit.filter(node=>(node.type||'other')===type)]));
      groups.forEach((type,groupIndex)=>{
        const group=groupByType.get(type)||[],x=width/2+(groupIndex-(groups.length-1)/2)*groupGap,rowGap=Math.min(82,Math.max(58,radiusY*.78)),start=height/2-(group.length-1)*rowGap/2;
        group.forEach((node,index)=>positions.set(node.id,{x,y:start+index*rowGap}));
      });
    }else{
      orbit.forEach((node,i)=>{
        const angle=2*Math.PI*i/orbit.length-Math.PI/2;
        positions.set(node.id,{x:width/2+radiusX*Math.cos(angle),y:height/2+radiusY*Math.sin(angle)});
      });
    }
    const linked=edges.filter(edge=>edge.from!==edge.to&&positions.has(edge.from)&&positions.has(edge.to));
    // Sparse views should read like an Obsidian-style constellation instead of
    // expanding to the edges of the canvas. Dense views still get the small
    // deterministic relaxation pass that prevents obvious collisions.
    const steps=compact?18:100,repulsionDistance=compact?152:180,springLength=compact?148:190,maxStep=compact?4:6;
    for(let step=0;step<steps;step++){
      const moves=new Map(ordered.map(node=>[node.id,{x:0,y:0}]));
      for(let i=0;i<ordered.length;i++)for(let j=i+1;j<ordered.length;j++){
        const a=positions.get(ordered[i].id),b=positions.get(ordered[j].id),dx=b.x-a.x,dy=b.y-a.y,d=Math.max(1,Math.hypot(dx,dy));
        const strength=Math.max(0,repulsionDistance-d)*(compact?.055:.09);
        moves.get(ordered[i].id).x-=dx/d*strength;moves.get(ordered[i].id).y-=dy/d*strength;
        moves.get(ordered[j].id).x+=dx/d*strength;moves.get(ordered[j].id).y+=dy/d*strength;
      }
      for(const edge of linked){
        const a=positions.get(edge.from),b=positions.get(edge.to),dx=b.x-a.x,dy=b.y-a.y,d=Math.max(1,Math.hypot(dx,dy));
        const strength=(d-springLength)*(compact?.004:.008);
        moves.get(edge.from).x+=dx/d*strength;moves.get(edge.from).y+=dy/d*strength;
        moves.get(edge.to).x-=dx/d*strength;moves.get(edge.to).y-=dy/d*strength;
      }
      for(const node of ordered){
        if(node.id===focus)continue;
        const point=positions.get(node.id),move=moves.get(node.id);
        point.x=clamp(point.x+clamp(move.x,-maxStep,maxStep),72,width-72);
        point.y=clamp(point.y+clamp(move.y,-maxStep,maxStep),48,height-48);
      }
    }
    return positions;
  }

  // One lane per explicit relation, including reciprocal links and self-relations.
  function edgeGeometry(edge,positions,lane=0){
    const a=positions.get(edge.from),b=positions.get(edge.to);
    if(!a||!b)return null;
    if(edge.from===edge.to)return {d:`M ${a.x-24} ${a.y-22} C ${a.x-90} ${a.y-105-lane*22}, ${a.x+90} ${a.y-105-lane*22}, ${a.x+24} ${a.y-22}`,x:a.x,y:a.y-82-lane*16};
    const dx=b.x-a.x,dy=b.y-a.y,d=Math.max(1,Math.hypot(dx,dy)),ux=dx/d,uy=dy/d;
    const bend=24+lane*30,cx=(a.x+b.x)/2-uy*bend,cy=(a.y+b.y)/2+ux*bend;
    const startLength=Math.max(1,Math.hypot(cx-a.x,cy-a.y)),endLength=Math.max(1,Math.hypot(b.x-cx,b.y-cy));
    const sx=a.x+(cx-a.x)/startLength*35,sy=a.y+(cy-a.y)/startLength*35;
    const ex=b.x-(b.x-cx)/endLength*40,ey=b.y-(b.y-cy)/endLength*40;
    return {d:`M ${sx} ${sy} Q ${cx} ${cy} ${ex} ${ey}`,x:(sx+2*cx+ex)/4,y:(sy+2*cy+ey)/4,candidates:[.5,.35,.65,.25,.75].map(t=>({x:(1-t)**2*sx+2*(1-t)*t*cx+t*t*ex,y:(1-t)**2*sy+2*(1-t)*t*cy+t*t*ey}))};
  }

  function upgrade(host,{nodes=[],edges=[],filter='all',focusId='',unresolved=[],ready=true,scopeKey=''}={}){
    const map=host.querySelector('.knowledge-map');
    if(!map)return;
    let previous=sessions.get(host);
    previous?.dispose();
    if(previous?.scopeKey!==scopeKey)previous=null;
    if(!ready){map.innerHTML='<div class="kg-empty">正在加载…</div>';return}
    const visible=visibleGraph(nodes,edges,filter,focusId),positions=layout(visible.nodes,visible.edges,visible.focus),density=visible.nodes.length<=8?'sparse':visible.nodes.length<=20?'compact':'dense';
    const nodeById=new Map(nodes.map(node=>[node.id,node]));
    const degree=new Map(visible.nodes.map(node=>[node.id,new Set()]));
    visible.edges.forEach(edge=>{degree.get(edge.from)?.add(edge.to);degree.get(edge.to)?.add(edge.from)});
    const focused=nodeById.get(visible.focus);
    const related=visible.focus?visible.edges.filter(edge=>edge.from===visible.focus||edge.to===visible.focus):[];
    map.innerHTML=`<div class="kg-shell">
      <div class="kg-head"><div class="kg-legend" aria-label="节点类型"><span class="kg-character">人物</span><span class="kg-entity">世界观</span><span class="kg-rule">规则</span><span class="kg-event">事件与事实</span></div><label class="kg-search"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></svg><input type="search" data-kg-search placeholder="查找图中节点…" aria-label="查找图中节点"><output data-kg-search-count aria-live="polite"></output></label></div>
      <div class="kg-canvas-wrap">
      ${visible.nodes.length?`<div class="kg-viewport kg-force-viewport kg-density-${density}" data-kg-viewport data-kg-density="${density}" tabindex="0" role="region" aria-label="关系图；拖动节点调整布局，拖动画布平移，滚轮缩放；也可展开下方节点列表"><div class="kg-force-chart" data-kg-chart></div><svg class="kg-self-links" data-kg-self-links aria-hidden="true"></svg><span class="kg-layout-status" data-kg-status role="status">布局中…</span></div>`:'<div class="kg-empty"><b>暂无节点</b><p>切换“全部”，或添加人物与世界观资料。</p></div>'}
      ${visible.nodes.length?`<div class="kg-controls" aria-label="图谱工具"><button type="button" data-kg-motion aria-pressed="false" title="固定当前布局，方便阅读">冻结布局</button><button type="button" data-kg-labels aria-pressed="true" title="显示或隐藏关系名称">显示关系名</button><span class="kg-control-divider"></span><button type="button" data-kg-zoom="out" aria-label="缩小图谱">−</button><output data-kg-scale aria-label="当前缩放比例">100%</output><button type="button" data-kg-zoom="in" aria-label="放大图谱">＋</button><button type="button" data-kg-fit title="将当前所有节点放回画布">适应画布</button></div>`:''}
      </div>
      <div class="kg-foot"><span><i class="kg-status-dot"></i><b>${visible.nodes.length}</b> 个节点 <span class="kg-foot-sep">/</span> <b>${visible.edges.length}</b> 条关系</span></div>
      ${visible.nodes.length?`<details class="kg-index" data-kg-index><summary>节点列表 <span>${visible.nodes.length} 个</span></summary><div class="kg-index-items">${visible.nodes.map(node=>`<button type="button" class="kg-index-node knowledge-node kg-${escape(typeName[node.type]?node.type:'fact')}" data-graph-node="${escape(node.id)}" aria-pressed="${node.id===visible.focus}"><span class="kg-index-dot" aria-hidden="true"></span><b>${escape(node.label)}</b><small>${escape(typeName[node.type]||'资料')} · ${degree.get(node.id).size} 个关联节点</small></button>`).join('')}</div></details>`:''}
      ${focused?`<section class="kg-detail" aria-label="节点关联"><div><small>${escape(typeName[focused.type]||'资料')}</small><h4>${escape(focused.label)}</h4><p>${related.length?`${related.length} 条关系`:'暂无关系，可打开来源补充。'}</p></div>${related.length?`<div class="kg-related">${related.map(edge=>{const other=nodeById.get(edge.from===focused.id?edge.to:edge.from);return other?`<button type="button" data-graph-node="${escape(other.id)}"><b>${escape(other.label)}</b><span>${escape(edge.kind||'关联')}</span><small>${escape(edge.summary||'当前正式修订')}</small></button>`:''}).join('')}</div>`:''}</section>`:(visible.edges.length?'':`<div class="kg-next"><p>暂无关系，可在下方添加。</p><button type="button" data-kg-add-relation>添加关系</button></div>`)}
      ${unresolved.length?`<details class="kg-unresolved"><summary>${unresolved.length} 条关系目标待核对</summary><p>请打开来源，确认关联对象。</p>${unresolved.map(item=>`<button type="button" data-graph-node="${escape(String(item.from||'').replace(/^world_entity:/,'entity:').replace(/^world_rule:/,'rule:'))}">${escape(item.target_name||item.target_world_id||'未知目标')} · ${escape(item.resolution||'未解析')}</button>`).join('')}</details>`:''}
    </div>`;
    const toolbar=host.querySelector('.graph-toolbar');
    toolbar?.classList.add('kg-toolbar');
    const form=host.querySelector('#relationForm');
    if(form){
      const from=form.elements.from_card_id,to=form.elements.to_card_id;
      if(from&&to&&from.value===to.value&&to.options.length>1)to.selectedIndex=1;
    }
    map.querySelector('[data-kg-add-relation]')?.addEventListener('click',event=>{event.stopPropagation();host.querySelector('#relationForm')?.scrollIntoView({behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'center'})});
    const session=mount(map,{nodes:visible.nodes,edges:visible.edges,positions,previous,focus:visible.focus,filter,scopeKey});
    if(session)sessions.set(host,session);
  }

  // Standard ECharts graph data, independently implemented for HaloCue. Node IDs
  // remain canonical; names need not be unique and no type hubs are invented.
  function forceData(nodes,edges,positions,colors,focus=''){
    const ids=new Set(nodes.map(n=>n.id)),neighbors=new Map(nodes.map(n=>[n.id,new Set()])),lanes=new Map();
    const valid=edges.filter(e=>ids.has(e.from)&&ids.has(e.to));
    for(const e of valid){neighbors.get(e.from).add(e.to);neighbors.get(e.to).add(e.from)}
    return {
      data:nodes.map(node=>{
        const degree=neighbors.get(node.id).size,p=positions.get(node.id)||{x:380,y:210};
        return {id:node.id,name:String(node.label||node.id),value:degree,x:p.x,y:p.y,
          category:node.type,meta:node.meta||'',symbol:'path://M8 0H112Q120 0 120 8V40Q120 48 112 48H8Q0 48 0 40V8Q0 0 8 0Z',symbolSize:[clamp(Array.from(String(node.label||node.id)).length*11+24,84,140),40],
          itemStyle:{color:colors.panel,borderWidth:node.id===focus?2:1,borderColor:colors[node.type]||colors.fact},
          label:{show:true,rich:{meta:{color:colors[node.type]||colors.fact}}},
          emphasis:{label:{show:true}},
        };
      }),
      links:valid.map((edge,index)=>{
        const key=JSON.stringify([edge.from,edge.to]),lane=lanes.get(key)||0;lanes.set(key,lane+1);
        return {id:edge.id||`relation-${index}`,source:edge.from,target:edge.to,name:String(edge.kind||'关联'),summary:edge.summary||'已保存的明确关系',
          ignoreForceLayout:edge.from===edge.to,lineStyle:{curveness:.12+lane*.16,opacity:edge.from===edge.to?0:.55},
          label:edge.from===edge.to?{show:false}:{},
        };
      }),
    };
  }

  function mount(map,{nodes,edges,positions,previous,focus,filter,scopeKey}){
    const viewport=map.querySelector('[data-kg-viewport]'),canvas=map.querySelector('[data-kg-chart]');
    if(!viewport||!canvas)return null;
    const index=map.querySelector('[data-kg-index]'),buttons=[...map.querySelectorAll('.kg-index-node')];
    if(!window.echarts){
      canvas.innerHTML='<div class="kg-empty">图形加载失败。请刷新，或使用下方节点列表。</div>';
      index.open=true;map.querySelector('.kg-controls').hidden=true;
      map.querySelector('[data-kg-status]').textContent='图形组件未载入';
      return null;
    }
    const reduce=window.matchMedia('(prefers-reduced-motion: reduce)');
    const same=previous&&previous.focus===focus&&previous.filter===filter&&previous.signature===nodes.map(n=>n.id).join('\n');
    const sparse=nodes.length<=8;
    const chart=window.echarts.init(canvas,null,{renderer:'canvas'});
    let disposed=false,timer=0,resizeFrame=0;
    let frozen=Boolean(previous?.frozen||previous?.keyboard),showLabels=Boolean(previous?.showLabels),search=same?previous.search:'',hoverId='',pointer=null,dragged=false,suppressUntil=0;
    let lastWidth=viewport.clientWidth,lastHeight=viewport.clientHeight,labelsTouched=Boolean(previous?.labelsTouched),autoFit=!same,fitTimer=0,fitting=false;
    const currentPositions=same?new Map(previous.points):new Map([...positions].map(([id,p])=>[id,previous?.points.get(id)||p]));
    const session={scopeKey,focus,filter,signature:nodes.map(n=>n.id).join('\n'),points:currentPositions,keyboard:false,frozen,showLabels,search,zoom:same?previous.zoom:.78,center:same?previous.center:null,dispose};
    index.open=Boolean(previous?.indexOpen||previous?.keyboard);
    const input=map.querySelector('[data-kg-search]');input.value=search;
    function theme(){
      const css=getComputedStyle(map),color=name=>css.getPropertyValue(name).trim();
      return {character:color('--kg-character'),entity:color('--kg-entity'),rule:color('--kg-rule'),event:color('--kg-event'),fact:color('--kg-event'),text:color('--hc-text'),muted:color('--hc-muted'),panel:color('--hc-panel'),edge:color('--kg-edge'),line:color('--hc-line'),font:css.fontFamily};
    }
    // ECharts' graph model exposes solved positions, which getOption does not.
    // Keep these pinned-version reads in one adapter; never persist them to a work.
    function snapshot(){
      if(disposed||chart.isDisposed())return;
      const data=chart.getModel().getSeriesByIndex(0)?.getData();
      if(data)for(let i=0;i<data.count();i++){
        const point=data.getItemLayout(i);
        if(point&&Number.isFinite(point[0])&&Number.isFinite(point[1]))session.points.set(data.getId(i),{x:point[0],y:point[1]});
      }
      const series=chart.getOption().series?.[0];
      if(series){session.zoom=series.zoom||1;session.center=series.center||null;const zero=chart.convertToPixel({seriesIndex:0},[0,0]),unit=chart.convertToPixel({seriesIndex:0},[1,0]);session.mapping={x:zero[0],y:zero[1],scale:unit[0]-zero[0]}}
      session.indexOpen=index.open;session.frozen=frozen;session.showLabels=showLabels;session.labelsTouched=labelsTouched;session.search=search;
    }
    function option(){
      const colors=theme(),data=forceData(nodes,edges,session.points,colors,focus),mobile=viewport.clientWidth<500;
      return {
        // Motion comes from the force solver; do not run a second transform tween
        // over its coordinates (that would desynchronize hit targets and symbols).
        animation:false,
        textStyle:{fontFamily:colors.font},
        tooltip:{confine:true,transitionDuration:0,hideDelay:0,backgroundColor:colors.panel,borderColor:colors.line,padding:[10,13],textStyle:{fontFamily:colors.font,color:colors.text,fontSize:12},
          formatter:p=>p.dataType==='edge'?`<b>${escape(p.data.name)}</b><br>${escape(p.data.summary)}`:`<b>${escape(p.data.name)}</b><br>${escape(typeName[p.data.category]||'资料')} · ${p.data.value} 个关联节点<br>${escape(p.data.meta)}`},
        series:[{
          id:'knowledge',type:'graph',preserveAspect:true,layout:frozen||reduce.matches?'none':'force',
          left:mobile?35:70,right:mobile?35:70,top:76,bottom:100,
          zoom:session.zoom,center:session.center,scaleLimit:{min:.3,max:3},
          force:{initLayout:'none',repulsion:sparse?[220,520]:[720,1500],edgeLength:sparse?[118,168]:[175,245],gravity:sparse?.16:.07,friction:.14,layoutAnimation:!reduce.matches},
          roam:true,draggable:true,nodeScaleRatio:0,autoCurveness:true,cursor:'pointer',
          data:data.data.map(node=>mobile?{...node,symbolSize:[Math.min(node.symbolSize[0],106),40]}:node),links:data.links,edgeSymbol:['none','arrow'],edgeSymbolSize:[0,6],
          lineStyle:{color:colors.edge,width:1.3,opacity:.55},
          label:{show:true,position:'inside',color:colors.text,align:'center',verticalAlign:'middle',
            formatter:p=>{const name=Array.from(p.data.name).slice(0,mobile?8:11).join('')+(Array.from(p.data.name).length>(mobile?8:11)?'…':'');return `{name|${name.replace(/[{}]/g,c=>c==='{'?'｛':'｝')}}\n{meta|${typeName[p.data.category]||'资料'}}`},
            rich:{name:{fontFamily:colors.font,fontSize:mobile?11:13,fontWeight:600,lineHeight:21,color:colors.text},meta:{fontFamily:colors.font,fontSize:10,fontWeight:400,lineHeight:15,color:colors.muted}},
          },
          edgeLabel:{show:showLabels,formatter:p=>p.data.name,color:colors.muted,fontSize:9,backgroundColor:colors.panel,borderColor:colors.line,borderWidth:1,padding:[3,6],borderRadius:6,overflow:'truncate',rotate:0},
          labelLayout:{hideOverlap:true},
          emphasis:{focus:'adjacency',scale:false,itemStyle:{borderColor:colors.text,borderWidth:2},lineStyle:{color:colors.text,width:2,opacity:1},label:{show:true},edgeLabel:{show:true,color:colors.text}},
          blur:{itemStyle:{opacity:.18},lineStyle:{opacity:.08},label:{opacity:.3},edgeLabel:{opacity:0}},
        }],
      };
    }
    function status(text){map.querySelector('[data-kg-status]').textContent=text}
    function controls(){
      const button=map.querySelector('[data-kg-motion]');button.textContent=frozen?'继续布局':'冻结布局';
      const labels=map.querySelector('[data-kg-labels]');labels.textContent=showLabels?'隐藏关系名':'显示关系名';labels.title=showLabels?'隐藏关系名称':'显示关系名称';button.setAttribute('aria-pressed',String(frozen));button.disabled=reduce.matches;
      button.title=reduce.matches?'已遵循系统“减少动态效果”设置':'固定当前布局，方便阅读';
      map.querySelector('[data-kg-labels]').setAttribute('aria-pressed',String(showLabels));
      map.querySelector('[data-kg-scale]').textContent=`${Math.round(session.zoom*100)}%`;
    }
    function render(){
      if(disposed)return;
      snapshot();const camera=session.mapping;chart.setOption(option(),{notMerge:true});restoreCamera(camera);controls();
      status(reduce.matches?'减少动态效果已开启':frozen?'布局已冻结':'布局中…');
      searchGraph();
    }
    function restoreCamera(camera){
      if(!camera||!Number.isFinite(camera.scale)||camera.scale<=0)return;
      fitting=true;
      let zero=chart.convertToPixel({seriesIndex:0},[0,0]);
      const unit=chart.convertToPixel({seriesIndex:0},[1,0]),scale=unit[0]-zero[0];
      if(scale>0)chart.dispatchAction({type:'graphRoam',seriesId:'knowledge',zoom:camera.scale/scale,originX:0,originY:0});
      zero=chart.convertToPixel({seriesIndex:0},[0,0]);
      chart.dispatchAction({type:'graphRoam',seriesId:'knowledge',dx:camera.x-zero[0],dy:camera.y-zero[1]});
      snapshot();fitting=false;
    }
    function stopStatus(){if(!disposed&&autoFit){autoFit=false;fit()}if(!disposed)status(reduce.matches?'减少动态效果已开启':frozen?'布局已冻结':'')}
    function selfLinks(){
      const svg=map.querySelector('[data-kg-self-links]'),self=edges.filter(e=>e.from===e.to);
      if(!self.length)return;
      const data=chart.getModel().getSeriesByIndex(0).getData(),colors=theme();
      const screen=new Map();for(let i=0;i<data.count();i++){const point=data.getItemLayout(i);if(point){const p=chart.convertToPixel({seriesIndex:0},point);screen.set(data.getId(i),{x:p[0],y:p[1]})}}
      svg.setAttribute('viewBox',`0 0 ${canvas.clientWidth} ${canvas.clientHeight}`);
      const lanes=new Map();
      svg.innerHTML=self.map(edge=>{const lane=lanes.get(edge.from)||0;lanes.set(edge.from,lane+1);const shape=edgeGeometry(edge,screen,lane);return shape?`<g><path d="${shape.d}" fill="none" stroke="${escape(colors.edge)}" stroke-width="1.4"/><title>${escape(edge.kind||'自身关系')}：${escape(edge.summary)}</title>${showLabels?`<text x="${shape.x}" y="${shape.y}" text-anchor="middle" fill="${escape(colors.muted)}" font-size="10">${escape(edge.kind||'自身关系')}</text>`:''}</g>`:''}).join('');
    }
    function onRendered(){
      if(disposed)return;
      clearTimeout(timer);timer=setTimeout(stopStatus,160);selfLinks();
    }
    function selectNode(id,keyboard=false){
      if(dragged||performance.now()<suppressUntil)return;
      session.keyboard=keyboard;snapshot();buttons.find(b=>b.dataset.graphNode===id)?.click();
    }
    function searchGraph(){
      const query=search.trim().toLocaleLowerCase();
      const matching=[];
      buttons.forEach((button,i)=>{const match=!query||String(nodes[i].label).toLocaleLowerCase().includes(query);button.hidden=!match;if(match)matching.push(i)});
      map.querySelector('[data-kg-search-count]').textContent=query?`${matching.length} 个匹配`:'';
      chart.dispatchAction({type:'downplay',seriesIndex:0});
      if(query&&matching.length)chart.dispatchAction({type:'highlight',seriesIndex:0,dataIndex:matching});
      else if(hoverId){const i=nodes.findIndex(n=>n.id===hoverId);if(i>=0)chart.dispatchAction({type:'highlight',seriesIndex:0,dataIndex:i})}
    }
    chart.on('rendered',onRendered);
    chart.on('click',params=>{if(params.dataType==='node')selectNode(params.data.id)});
    chart.on('mouseover',params=>{if(params.dataType==='node')hoverId=params.data.id});
    chart.on('globalout',()=>{hoverId='';if(search)searchGraph()});
    chart.on('graphRoam',()=>{if(!fitting)autoFit=false;snapshot();controls()});
    canvas.addEventListener('pointerdown',event=>{pointer={x:event.clientX,y:event.clientY,id:event.pointerId};dragged=false;autoFit=false;status(frozen?'布局已冻结':'布局中…')},true);
    canvas.addEventListener('pointermove',event=>{if(pointer&&pointer.id===event.pointerId&&Math.hypot(event.clientX-pointer.x,event.clientY-pointer.y)>4)dragged=true},true);
    const endPointer=event=>{if(!pointer||pointer.id!==event.pointerId)return;if(dragged)suppressUntil=performance.now()+220;pointer=null;dragged=false;snapshot()};
    window.addEventListener('pointerup',endPointer,true);window.addEventListener('pointercancel',endPointer,true);
    function zoom(factor){const rect=canvas.getBoundingClientRect();chart.dispatchAction({type:'graphRoam',seriesId:'knowledge',zoom:factor,originX:rect.width/2,originY:rect.height/2});snapshot();controls()}
    map.querySelectorAll('[data-kg-zoom]').forEach(button=>button.addEventListener('click',event=>{event.stopPropagation();zoom(button.dataset.kgZoom==='in'?1.2:1/1.2)}));
    function fit(){
      if(disposed||fitting)return;
      snapshot();fitting=true;
      const data=chart.getModel().getSeriesByIndex(0).getData();
      const bounds=()=>{const p=[];for(let i=0;i<data.count();i++){const item=data.getItemLayout(i);if(item)p.push(chart.convertToPixel({seriesIndex:0},item))}return {left:Math.min(...p.map(p=>p[0])),right:Math.max(...p.map(p=>p[0])),top:Math.min(...p.map(p=>p[1])),bottom:Math.max(...p.map(p=>p[1]))}};
      if(data.count()){
        let b=bounds();const width=canvas.clientWidth,height=canvas.clientHeight;
        const ratio=Math.min((width-126)/Math.max(80,b.right-b.left),(height-225)/Math.max(80,b.bottom-b.top));
        const next=clamp(session.zoom*ratio,sparse?.62:.3,sparse?1.08:1.5);
        chart.dispatchAction({type:'graphRoam',seriesId:'knowledge',zoom:next/session.zoom,originX:width/2,originY:height/2});
        b=bounds();chart.dispatchAction({type:'graphRoam',seriesId:'knowledge',dx:width/2-(b.left+b.right)/2,dy:(height-30)/2-(b.top+b.bottom)/2});
      }
      snapshot();controls();fitting=false;
    }
    map.querySelector('[data-kg-fit]').addEventListener('click',event=>{event.stopPropagation();fit()});
    map.querySelector('[data-kg-labels]').addEventListener('click',event=>{event.stopPropagation();autoFit=false;clearTimeout(fitTimer);labelsTouched=true;showLabels=!showLabels;render()});
    map.querySelector('[data-kg-motion]').addEventListener('click',event=>{event.stopPropagation();autoFit=false;clearTimeout(fitTimer);frozen=!frozen;render()});
    input.addEventListener('input',()=>{search=input.value;session.search=search;searchGraph()});
    input.addEventListener('keydown',event=>{if(event.key==='Escape'){input.value='';search='';searchGraph()}else if(event.key==='Enter'){event.preventDefault();const first=buttons.find(b=>!b.hidden);if(first)selectNode(first.dataset.graphNode,true)}});
    index.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' ')session.keyboard=true},true);
    buttons.forEach(button=>{
      button.addEventListener('focus',()=>{hoverId=button.dataset.graphNode;searchGraph()});
      button.addEventListener('blur',()=>{hoverId='';searchGraph()});
    });
    viewport.addEventListener('keydown',event=>{
      if(event.target!==viewport)return;
      if(['+','=','-','0','ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key))event.preventDefault();
      if(event.key==='+'||event.key==='=')zoom(1.2);else if(event.key==='-')zoom(1/1.2);else if(event.key==='0')fit();
      else if(event.key.startsWith('Arrow'))chart.dispatchAction({type:'graphRoam',seriesId:'knowledge',dx:event.key==='ArrowLeft'?35:event.key==='ArrowRight'?-35:0,dy:event.key==='ArrowUp'?35:event.key==='ArrowDown'?-35:0});
    });
    const resize=new ResizeObserver(()=>{
      if(!viewport.isConnected){dispose();return}
      if(lastWidth===viewport.clientWidth&&lastHeight===viewport.clientHeight)return;
      lastWidth=viewport.clientWidth;lastHeight=viewport.clientHeight;
      if(!labelsTouched)showLabels=lastWidth>=500;
      cancelAnimationFrame(resizeFrame);resizeFrame=requestAnimationFrame(()=>{if(!disposed){snapshot();chart.resize();render();fit()}});
    });
    resize.observe(viewport);
    const themeObserver=new MutationObserver(()=>{if(!disposed)render()});
    themeObserver.observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
    const motionChange=()=>render();reduce.addEventListener('change',motionChange);
    const visibilityChange=()=>{if(document.hidden&&!disposed){snapshot();chart.setOption({animation:false,series:[{id:'knowledge',layout:'none',data:option().series[0].data}]});stopStatus()}};
    document.addEventListener('visibilitychange',visibilityChange);
    function dispose(){
      if(disposed)return;
      snapshot();disposed=true;clearTimeout(timer);clearTimeout(fitTimer);cancelAnimationFrame(resizeFrame);
      resize.disconnect();themeObserver.disconnect();reduce.removeEventListener('change',motionChange);
      window.removeEventListener('pointerup',endPointer,true);window.removeEventListener('pointercancel',endPointer,true);
      document.removeEventListener('visibilitychange',visibilityChange);chart.dispose();
    }
    chart.setOption(option());if(same)restoreCamera(previous.mapping);controls();searchGraph();
    fitTimer=setTimeout(()=>{if(autoFit&&!disposed)fit()},500);
    if(previous?.keyboard&&focus){index.open=true;buttons.find(b=>b.dataset.graphNode===focus)?.focus({preventScroll:true})}
    return session;
  }
  const api={layout,visibleGraph,edgeGeometry,dimensions,forceData,upgrade};
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(typeof window!=='undefined')window.HaloCueKnowledgeGraph=api;
})();
