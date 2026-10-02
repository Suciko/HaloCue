const assert=require('node:assert/strict');
const {create}=require('../web/activity-refresh.js');
const tick=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};
function setup(){
  let key='work-a:1',next=0;
  const timers=new Map(),requests=[],applied=[],errors=[];
  const controller=create({getKey:()=>key,interval:5,retryInterval:15,timeout:12,
    setTimer:(fn,delay)=>{const id=++next;timers.set(id,{fn,delay});return id;},clearTimer:id=>timers.delete(id),
    load:(scope,signal)=>new Promise((resolve,reject)=>requests.push({scope,signal,resolve,reject})),
    apply:result=>{applied.push(result);return result.healthy;},onError:error=>errors.push(error.message)});
  return {controller,requests,applied,errors,timers,setKey:value=>{key=value;},fire:delay=>{const entry=[...timers].find(([,t])=>t.delay===delay);assert.ok(entry,`No ${delay}ms timer`);timers.delete(entry[0]);entry[1].fn();}};
}
(async()=>{
  const a=setup();a.controller.sync();a.controller.refresh();assert.equal(a.requests.length,1);
  a.requests[0].resolve({healthy:true,id:'initial'});await tick();assert.equal(a.applied.length,1);
  a.fire(5);assert.equal(a.requests.length,2);a.requests[1].resolve({healthy:true});await tick();
  a.setKey(null);a.controller.sync();assert.equal(a.timers.size,0);
  a.setKey('work-a:2');a.controller.sync();const late=a.requests[2];
  a.setKey('work-b:3');a.controller.sync();assert.equal(late.signal.aborted,true);
  late.resolve({healthy:true,id:'stale'});a.requests[3].resolve({healthy:true,id:'new'});await tick();
  assert.equal(a.applied.at(-1).id,'new');assert.ok(!a.applied.some(x=>x.id==='stale'));
  a.fire(5);a.setKey(null);a.controller.sync();a.requests[4].resolve({healthy:true,id:'hidden'});await tick();assert.equal(a.applied.at(-1).id,'new');
  const b=setup();b.controller.sync();b.requests[0].reject(new Error('offline'));await tick();assert.deepEqual(b.errors,['offline']);b.fire(15);assert.equal(b.requests.length,2);
  b.fire(12);await tick();assert.equal(b.requests[1].signal.aborted,true);assert.equal(b.errors.at(-1),'refresh_timeout');b.fire(15);
  b.requests[2].resolve({healthy:false});await tick();b.fire(15);assert.equal(b.requests.length,4);
  b.controller.stop();a.controller.stop();assert.equal(b.timers.size,0);
  console.log('activity refresh: scope, deduplication, visibility, timeout, retry, stop passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
