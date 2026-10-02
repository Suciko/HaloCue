/* Read-only refresh lifecycle. No writes, model calls, or global route ownership. */
(function(root){
  'use strict';
  function create({getKey,load,apply,onError=()=>{},onStart=()=>{},onStop=()=>{},
    interval=5000,retryInterval=15000,timeout=12000,
    setTimer=setTimeout,clearTimer=clearTimeout}){
    let key=null,epoch=0,timer=null,flight=null;
    const current=(request)=>flight===request&&request.epoch===epoch&&getKey()===request.key;
    function stop(){
      epoch++;key=null;
      if(timer!==null)clearTimer(timer);timer=null;
      if(flight){clearTimer(flight.deadline);flight.controller.abort();flight=null;}
      onStop();
    }
    function schedule(delay){
      if(timer!==null)clearTimer(timer);
      timer=setTimer(()=>{timer=null;sync(true);},delay);
    }
    async function run(){
      const request={key,epoch,controller:new AbortController(),deadline:null};
      flight=request;onStart();let failed=false;
      try{
        const deadline=new Promise((_,reject)=>{
          request.deadline=setTimer(()=>{request.controller.abort();reject(new Error('refresh_timeout'));},timeout);
        });
        const result=await Promise.race([load(request.key,request.controller.signal),deadline]);
        if(!current(request))return;
        failed=apply(result)===false;
      }catch(error){
        if(!current(request))return;
        failed=true;onError(error);
      }finally{
        clearTimer(request.deadline);
        if(flight===request){
          flight=null;
          if(getKey()===key&&key!==null)schedule(failed?retryInterval:interval);
          else stop();
        }
      }
    }
    function sync(force=false){
      const next=getKey();
      if(next===null){if(key!==null||flight||timer!==null)stop();return;}
      if(next!==key){stop();key=next;void run();return;}
      if(force&&!flight){if(timer!==null)clearTimer(timer);timer=null;void run();}
    }
    return {sync,refresh:()=>sync(true),stop};
  }
  if(typeof module==='object'&&module.exports)module.exports={create};
  else root.HaloCueActivityRefresh={create};
})(typeof window==='undefined'?globalThis:window);
