const test = require('node:test');
const assert = require('node:assert/strict');
const graph = require('../web/knowledge-graph-ui.js');

test('local focus shows verified neighbors across node types, never unrelated nodes', () => {
  const nodes = [
    {id: 'character:a', type: 'character'},
    {id: 'character:b', type: 'character'},
    {id: 'entity:room', type: 'entity'},
    {id: 'fact:orphan', type: 'fact'},
  ];
  const edges = [
    {from: 'character:a', to: 'character:b'},
    {from: 'character:a', to: 'entity:room'},
  ];
  const focused = graph.visibleGraph(nodes, edges, 'character', 'character:a');
  assert.deepEqual(focused.nodes.map(node => node.id), [
    'character:a', 'character:b', 'entity:room',
  ]);
  assert.equal(focused.edges.length, 2);
  assert.equal(graph.visibleGraph(nodes, edges, 'character').nodes.length, 2);
});

test('graph layout is stable and keeps a focused node in the center', () => {
  const nodes = Array.from({length: 12}, (_, index) => ({id: `node-${index}`}));
  const edges = nodes.slice(1).map(node => ({from: 'node-0', to: node.id}));
  const first = graph.layout(nodes, edges, 'node-0');
  const second = graph.layout(nodes, edges, 'node-0');
  assert.deepEqual([...first], [...second]);
  assert.deepEqual(first.get('node-0'), {x: 380, y: 210});
  for (const point of first.values()) {
    assert.ok(Number.isFinite(point.x) && Number.isFinite(point.y));
    assert.ok(point.x >= 72 && point.x <= 688);
    assert.ok(point.y >= 48 && point.y <= 372);
  }
});
const many = count => Array.from({length: count}, (_, i) => ({id: `n-${String(i).padStart(3, '0')}`, type: 'character'}));

test('layout is independent of input ordering and expands for larger graphs', () => {
  const nodes = many(48), edges = nodes.slice(1).map(n => ({from: nodes[0].id, to: n.id}));
  const first = graph.layout(nodes, edges);
  const reversed = graph.layout([...nodes].reverse(), edges);
  for (const node of nodes) assert.deepEqual(first.get(node.id), reversed.get(node.id));
  const size = graph.dimensions(nodes.length);
  assert.ok(size.width > 760 && size.height > 420);
  for (const point of first.values()) {
    assert.ok(point.x >= 72 && point.x <= size.width - 72);
    assert.ok(point.y >= 48 && point.y <= size.height - 48);
  }
});

test('empty, isolated, unknown focus and dangling edges stay finite', () => {
  assert.equal(graph.layout([], []).size, 0);
  assert.deepEqual(graph.layout([{id:'solo'}], []).get('solo'), {x:380,y:210});
  const nodes = many(8), edges = [{from:'missing',to:'n-000'}];
  assert.deepEqual(graph.layout(nodes, edges, 'missing'), graph.layout(nodes, []));
  assert.equal(graph.visibleGraph(nodes, edges).edges.length, 0);
});

test('curved geometry distinguishes parallel and reverse directions and supports loops', () => {
  const positions = new Map([['a',{x:100,y:100}],['b',{x:300,y:200}]]);
  const ab = {from:'a',to:'b'}, ba = {from:'b',to:'a'};
  const normal = graph.edgeGeometry(ab,positions);
  assert.match(normal.d, / Q /);
  assert.notEqual(normal.d, graph.edgeGeometry(ab,positions,1).d);
  assert.notEqual(normal.y, graph.edgeGeometry(ba,positions).y);
  assert.match(graph.edgeGeometry({from:'a',to:'a'},positions).d, / C /);
  assert.equal(graph.edgeGeometry({from:'a',to:'missing'},positions), null);
  assert.ok(Number.isFinite(graph.edgeGeometry(ab,new Map([['a',{x:0,y:0}],['b',{x:0,y:0}]])).x));
});

test('type filters and stale focus never introduce an unverified relationship', () => {
  const nodes=[{id:'a',type:'character'},{id:'b',type:'entity'}];
  const edges=[{from:'a',to:'b',kind:'真实关联'},{from:'a',to:'missing'}];
  const result=graph.visibleGraph(nodes,edges,'character','stale');
  assert.equal(result.focus,'');
  assert.deepEqual(result.nodes,[nodes[0]]);
  assert.deepEqual(result.edges,[]);
});

test('focused graph excludes dangling targets before SVG lanes are assigned', () => {
  const nodes=[{id:'a',type:'character'},{id:'b',type:'entity'}];
  const edges=[{from:'a',to:'missing'},{from:'a',to:'b'}];
  assert.deepEqual(graph.visibleGraph(nodes,edges,'all','a').edges,[edges[1]]);
});

const colors={character:'#278579',entity:'#bd705d',rule:'#7089bd',event:'#a68043',fact:'#a68043',text:'#202b34',panel:'#fff'};
test('force adapter uses stable IDs, truthful degree, and explicit parallel links', () => {
  const nodes=[{id:'a',label:'同名',type:'character'},{id:'b',label:'同名',type:'entity'},{id:'c',label:'未连接',type:'rule'}];
  const edges=[{from:'a',to:'b',kind:'同伴'},{from:'a',to:'b',kind:'同社团'},{from:'b',to:'a',kind:'反向'},{from:'a',to:'a',kind:'自身'},{from:'a',to:'missing'}];
  const before=JSON.stringify({nodes,edges});
  const data=graph.forceData(nodes,edges,graph.layout(nodes,edges),colors);
  assert.deepEqual(data.data.map(n=>n.id),['a','b','c']);
  assert.deepEqual(data.data.map(n=>n.value),[2,1,0]);
  assert.equal(data.links.length,4);
  assert.notEqual(data.links[0].lineStyle.curveness,data.links[1].lineStyle.curveness);
  assert.equal(data.links[3].ignoreForceLayout,true);
  assert.equal(JSON.stringify({nodes,edges}),before);
});

test('force adapter treats graph names as data and never creates category hubs', () => {
  const nodes=[{id:'literal-id',type:'character',label:'<img onerror=alert(1)>'}];
  const data=graph.forceData(nodes,[],new Map(),colors,'literal-id');
  assert.equal(data.data.length,1);
  assert.equal(data.data[0].name,nodes[0].label);
  assert.deepEqual(data.links,[]);
  assert.equal(data.data[0].value,0);
  assert.ok(Number.isFinite(data.data[0].x));
  assert.equal(data.data[0].itemStyle.borderWidth,2);
  assert.ok(data.data[0].symbol.startsWith('path://'));
  assert.deepEqual(data.data[0].symbolSize.slice(1),[40]);
  assert.equal(data.data[0].itemStyle.color,colors.panel);
  assert.deepEqual(data.data[0].symbolSize.slice(1),[40]);
});
