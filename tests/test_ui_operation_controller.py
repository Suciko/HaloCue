import json
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]


def test_api_poll_retries_network_errors_and_stops_when_scope_is_stale():
    script = r'''
const fs=require('fs'),vm=require('vm'),src=fs.readFileSync(process.argv[1],'utf8');let calls=0,current=true;const timers=[];const values=[new Error('first'),{state:'running'},new Error('middle'),{state:'succeeded'}];const window={};vm.runInNewContext(src,{window,fetch:async()=>{calls++;const v=values.shift();if(v instanceof Error)throw v;return {ok:true,headers:{get:()=> 'application/json'},json:async()=>v}},setTimeout:f=>timers.push(f),Promise,Error});(async()=>{let retries=0;const p=window.Api.poll('/job',x=>x.state==='succeeded',{interval:1,isCurrent:()=>current,onRetry:()=>retries++});while(timers.length||values.length){if(timers.length)await timers.shift()();else await Promise.resolve()}const value=await p;const before=calls;current=false;const stale=await window.Api.poll('/job',()=>false,{isCurrent:()=>current});console.log(JSON.stringify({value:value.state,retries,calls,before,stale}));})();
'''
    result = json.loads(subprocess.check_output(["node", "-e", script, str(HERE / "js" / "api.js")], text=True, encoding="utf-8"))
    assert result == {"value": "succeeded", "retries": 2, "calls": 4, "before": 4, "stale": None}


def test_api_poll_treats_missing_or_expired_jobs_as_terminal_without_retry():
    script = r'''
const fs=require('fs'),vm=require('vm'),src=fs.readFileSync(process.argv[1],'utf8');let calls=0,timers=0;const window={};vm.runInNewContext(src,{window,fetch:async()=>{calls++;return {ok:false,status:410,headers:{get:()=> 'application/json'},json:async()=>({code:'job_missing',e:'gone'})}},setTimeout:()=>timers++,Promise,Error});(async()=>{try{await window.Api.poll('/job',()=>false,{interval:1})}catch(error){console.log(JSON.stringify({calls,timers,status:error.status,code:error.code}))}})();
'''
    result = json.loads(subprocess.check_output(["node", "-e", script, str(HERE / "js" / "api.js")], text=True, encoding="utf-8"))
    assert result == {"calls": 1, "timers": 0, "status": 410, "code": "job_missing"}
