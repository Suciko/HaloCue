const {test}=require('node:test');
const assert=require('node:assert/strict');
const {project,visible,preferences}=require('../web/guided-workflow.js');
const writing={workId:'work',surface:'writing',sceneId:'first',sceneTitle:'活动室',revisionId:null,canPrepare:true};
const discussion={workId:'work',surface:'works',threadId:'thread',workAction:true,nextStep:'draft',workDependency:['draft','first',null],workLabel:'进入正文写作'};

test('only an actual current Agent action yields discussion guidance',()=>{
  assert.equal(project({...discussion,nextStep:null}),null);
  assert.equal(project({...discussion,nextStep:'invented'}),null);
  assert.equal(project({...discussion,workAction:false}),null);
  assert.equal(project({...discussion,busy:true}),null);
  assert.equal(project({...writing,workId:null}),null);
});
test('entering an empty scene only prepares a request, and manual work needs no model',()=>{
  assert.equal(project(writing).action,'prepare');
  assert.match(project(writing).detail,/发送后才生成/);
  assert.equal(project({...writing,canPrepare:false}).action,'manual');
});
test('dirty prose takes precedence over a candidate and never recommends acceptance',()=>{
  const task=project({...writing,dirty:true,proposalId:'proposal',proposalBase:null});
  assert.equal(task.action,'save');
  assert.equal(project({...writing,proposalId:'proposal',proposalBase:null}).action,'review');
});
test('an old candidate is never presented as ready to adopt',()=>{
  const task=project({...writing,revisionId:'new',proposalId:'proposal',proposalBase:'old'});
  assert.equal(task.action,'manual');
  assert.match(task.detail,/旧候选不会自动采用/);
});
test('saved and adopted prose stays an editing task rather than chapter completion',()=>{
  const task=project({...writing,revisionId:'saved'});
  assert.equal(task.action,'manual');
  assert.match(task.detail,/不代表这一章已经写完/);
  assert.notEqual(task.key,project(writing).key);
});
test('scope dismissal survives unrelated versions and new replies, and expires for changed results',()=>{
  const task=project(discussion);
  const prefs={deferred:{[task.scope]:task.key}};
  assert.equal(visible(project({...discussion,version:500,messageId:'new'}),prefs),false);
  assert.equal(visible(project({...discussion,workDependency:['draft','other',null]}),prefs),true);
  assert.equal(visible(project({...writing,proposalId:'new',proposalBase:null}),prefs),true);
});
test('pause/free mode do not resume on state changes; an explicit request does not change the preference',()=>{
  const task=project(writing);
  for(const value of [{paused:true},{mode:'free'}]){
    assert.equal(visible(task,value),false);
    assert.equal(visible(task,value,true),true);
  }
  assert.equal(visible(null,{},true),false);
  assert.equal(preferences({mode:'broken',deferred:[]}).mode,'suggest');
});
test('different work and scene identities cannot share a cached task',()=>{
  assert.notEqual(project(writing).key,project({...writing,workId:'other'}).key);
  assert.notEqual(project(writing).key,project({...writing,sceneId:'other'}).key);
  assert.equal(project({...writing,surface:'production'}),null);
});
