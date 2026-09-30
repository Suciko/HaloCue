const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8');
function todos(decision,proposals){
 const body=source.slice(source.indexOf('function workTodoMarkup(){'),source.indexOf('\nconst renderChapterDiscussionInspector=',source.indexOf('function workTodoMarkup(){')));
 const ctx={blueprint:()=>null,activeWorkDecision:()=>decision,state:{work:{proposals}},hcArray:x=>x||[],esc:x=>String(x).replaceAll('<','&lt;')};
 vm.createContext(ctx);return vm.runInContext(body+'\nworkTodoMarkup()',ctx);
}
test('empty state only when no ideation decision or proposal exists',()=>{
 assert.match(todos(null,[]),/hc-todo-empty/);
 assert.doesNotMatch(todos({title:'选择方向',kind:'choose'},[]),/hc-todo-empty/);
});
test('primary proposal is not listed twice',()=>{
 const p={id:'p1',kind:'character_card',status:'pending'};
 const html=todos({title:'人物候选',kind:'proposal',pendingProposal:p},[p]);
 assert.match(html,/前往处理/);assert.doesNotMatch(html,/data-work-todo-proposal/);
});
test('only pending ideation proposals are shown with understandable labels',()=>{
 const html=todos(null,[{id:'s',kind:'scene_script',status:'pending'},{id:'b',kind:'brief_blueprint',status:'pending'},{id:'c',kind:'character_card',status:'accepted'}]);
 assert.match(html,/故事方向/);assert.match(html,/data-work-todo-proposal="b"/);assert.doesNotMatch(html,/data-work-todo-proposal="[sc]"/);
});
test('returning to a decision preserves unsent text and caret',()=>{
 const begin=source.indexOf('function renderWorkTodoTarget(){');
 const body=source.slice(begin,source.indexOf('\nregisterAppClick',begin));
 let current={value:'未发送草稿',selectionStart:2,selectionEnd:4};
 const ctx={hcRenderHooks:new Map(),state:{route:{}},document:{querySelector:()=>current},renderWorkspace:()=>{current={value:'',setSelectionRange(a,b){this.selectionStart=a;this.selectionEnd=b}}}};
 vm.createContext(ctx);vm.runInContext(body+'\nrenderWorkTodoTarget()',ctx);
 assert.equal(current.value,'未发送草稿');assert.equal(current.selectionStart,2);assert.equal(current.selectionEnd,4);
});

function formatQuestion(labels=['羁绊短场景','小说化阅读'],title='请选择主写作模式',kind='choose'){
 return {content:{decision_card:{kind,title,options:labels.map(label=>({label}))}}};
}
function skipsFormat(message,user='写一段温和的日常剧本'){
 const start=source.indexOf('function isDefaultScriptFormatQuestion(');
 const body=source.slice(start,source.indexOf('function activeWorkDecision(',start));
 const ctx={message,thread:{messages:[{role:'user',content:{text:user}}]},messageText:m=>m.content.text};vm.createContext(ctx);
 return vm.runInContext(body+'isDefaultScriptFormatQuestion(message,thread)',ctx);
}
test('legacy generic format gate is hidden, explicit prose and real choices remain',()=>{
 assert.equal(skipsFormat(formatQuestion()),true);
 assert.equal(skipsFormat(formatQuestion(),'我要小说化阅读'),false);
 assert.equal(skipsFormat(formatQuestion(['坦白','隐瞒'],'如何处理秘密？')),false);
 assert.equal(skipsFormat(formatQuestion(undefined,undefined,'confirm')),false);
});
