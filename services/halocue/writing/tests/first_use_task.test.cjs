const {test}=require('node:test');
const assert=require('node:assert/strict');
const {lesson}=require('../web/first-use-task.js');
test('teaching requires opting into the first task, never a new-work reminder',()=>{
  for(const status of ['offered','complete','dismissed','paused','legacy'])assert.equal(lesson({}, {status}),null);
  assert.equal(lesson({}, {status:'active'}).action,'create');
});
test('each step follows actual work state rather than pressing next',()=>{
  const record={status:'active',workId:'w'};
  assert.equal(lesson({workId:'w'},record).step,2);
  assert.equal(lesson({workId:'w',hasIdea:true},record).action,'structure');
  assert.equal(lesson({workId:'w',planPending:true,hasIdea:true},record).action,'plan');
  assert.equal(lesson({workId:'w',sceneId:'s'},record).action,'draft');
});
test('manual authors need no model and dirty prose teaches saving',()=>{
  const record={status:'active',workId:'w',manual:true};
  assert.equal(lesson({workId:'w'},record).step,3);
  assert.equal(lesson({workId:'w',sceneId:'s',atDraft:true},record).action,'manual');
  assert.equal(lesson({workId:'w',sceneId:'s',atDraft:true,dirty:true},record).action,'save');
  assert.equal(lesson({workId:'w',sceneId:'s',atDraft:true,dirty:true,emptyField:true},record).action,'write');
  assert.equal(lesson({workId:'w',atStructure:true},record).action,'add-scene');
  assert.match(lesson({workId:'w',compactNav:true},record).detail,/视图菜单/);
  assert.match(lesson({workId:'w',atStructure:true,addSceneVisible:false},record).detail,/展开场景栏/);
});
test('a candidate is not lesson completion; only a new saved revision completes it',()=>{
  const record={status:'active',workId:'w'};
  assert.equal(lesson({workId:'w',sceneId:'s',atDraft:true,proposalId:'p'},record).action,'review');
  assert.notEqual(lesson({workId:'w',sceneId:'s',atDraft:true,revisionId:'old'},record).step,5);
  assert.equal(lesson({workId:'w',sceneId:'s',saved:true},record).step,5);
});
test('switching works or deleting the teaching scene cannot silently complete/rebind it',()=>{
  const record={status:'active',workId:'w'};
  assert.equal(lesson({workId:'other',saved:true},record).action,'return');
  assert.equal(lesson({workId:'w',targetMissing:true},record).action,'structure');
});
