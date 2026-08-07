import json
import subprocess
from pathlib import Path


def run_node(script, *args):
    return subprocess.check_output(
        ["node", "-e", script, *map(str, args)],
        text=True,
        encoding="utf-8",
    )


def test_settings_ui_has_two_role_cards_and_help_entry():
    html = (Path(__file__).parents[1] / "ui.html").read_text(encoding="utf-8")
    layout_css = (Path(__file__).parents[1] / "css" / "layout.css").read_text(encoding="utf-8")
    settings = html.split('id="modelSettings"', 1)[1].split("</section>", 1)[0]
    assert 'class="model-role-card"' in settings
    assert "基础模型" in settings
    assert "图片识别模型" in settings
    assert 'data-action="open-model-role"' in settings
    assert 'data-action="open-help-api"' in settings
    assert 'id="helpApiModelsTemplate"' in html
    assert 'id="modelConnectionEditor" hidden' in settings
    assert 'id="modelProviderCatalog"' in settings
    assert 'data-action="use-provider-preset"' in settings
    assert 'data-action="save-profile-as-new"' in settings
    assert 'data-action="open-provider-site"' in settings
    assert 'data-action="use-base-for-vision"' in settings
    assert 'data-action="disable-vision-model"' in settings
    assert 'id="modelDiscoveryList" class="model-discovery-list wide"' in settings
    assert 'id="modelMaxTokensHint"' in settings
    assert 'id="modelReasoningMode"' in settings
    assert 'data-action="restore-model-max-tokens"' in settings
    assert ".model-grid>.field{align-content:start}" in layout_css
    app = (Path(__file__).parents[1] / "js" / "app.js").read_text(encoding="utf-8")
    assert "delete-workbench-model" in app
    assert "delete_empty_connection" in app
    assert "当前模型正在使用，请先更换" in app


def test_model_settings_helpers_filter_by_role_and_render_status():
    runtime = Path(__file__).parents[1] / "js" / "model.js"
    script = r'''
const fs=require('fs'),vm=require('vm');
const source=fs.readFileSync(process.argv[1],'utf8');
const sandbox={window:{}};vm.runInNewContext(source,sandbox);
const api=sandbox.window.ModelSettings;
const models=[
 {id:'text',model:'deepseek-chat',text_status:'passed',vision_status:'unsupported',connection_id:'conn-deepseek',connection_name:'DeepSeek'},
 {id:'vision',model:'qwen-vl-plus',text_status:'untested',vision_status:'passed',connection_id:'conn-qwen',connection_name:'Qwen'}
];
console.log(JSON.stringify({
 text:api.filterModels(models,'text','','','').map(x=>x.id),
 vision:api.filterModels(models,'vision','','','').map(x=>x.id),
 provider:api.filterModels(models,'text','','conn-qwen','').map(x=>x.id),
 label:api.statusLabel('vision','passed'),
 untested:api.statusLabel('text','untested'),
 failed:api.statusLabel('vision','failed'),
 readiness:api.modelReadinessLabel({configured:true,name:'DeepSeek 官方',model:'deepseek-v4-flash',vision_name:'Gemini 视觉',vision_model:'gemini-3.6-flash'}),
 connection:api.connectionDisplayName({name:'openai / gemini',service_preset:'deepseek'},{deepseek:{label:'DeepSeek'}}),
 savedSecrets:api.assignmentSecretStatus({
  connections:[{id:'deepseek',secret_status:'saved'},{id:'gemini',secret_status:'saved'}],
  models:[{id:'text',connection_id:'deepseek'},{id:'vision',connection_id:'gemini'}],
  assignments:{base_model_id:'text',vision_mode:'separate',vision_model_id:'vision'}
 }),
 missingSecrets:api.assignmentSecretStatus({
  connections:[{id:'deepseek',secret_status:'saved'},{id:'gemini',secret_status:'missing'}],
  models:[{id:'text',connection_id:'deepseek'},{id:'vision',connection_id:'gemini'}],
  assignments:{base_model_id:'text',vision_mode:'separate',vision_model_id:'vision'}
 }),
 assignedDelete:api.modelDeleteControl(true,false),
 legacyDelete:api.modelDeleteControl(false,true),
 unusedDelete:api.modelDeleteControl(false,false)
}));
'''
    result = json.loads(run_node(script, runtime))
    assert result == {
        "text": ["text", "vision"],
        "vision": ["vision"],
        "provider": ["vision"],
        "label": "图片已通过",
        "untested": "文字未测试",
        "failed": "图片测试失败",
        "readiness": "DeepSeek 官方 · deepseek-v4-flash；图片：Gemini 视觉 · gemini-3.6-flash",
        "connection": "DeepSeek · openai / gemini",
        "savedSecrets": "saved",
        "missingSecrets": "missing",
        "assignedDelete": {"disabled": False, "title": "当前模型正在使用，点击查看说明"},
        "legacyDelete": {"disabled": True, "title": "重新启动程序后可删除模型"},
        "unusedDelete": {"disabled": False, "title": "删除模型"},
    }


def test_model_settings_builds_legacy_workbench_fallback():
    runtime = Path(__file__).parents[1] / "js" / "model.js"
    script = r'''
const fs=require('fs'),vm=require('vm');
const source=fs.readFileSync(process.argv[1],'utf8');
const sandbox={window:{}};vm.runInNewContext(source,sandbox);
const result=sandbox.window.ModelSettings.legacyWorkbench({
 active_profile_id:'legacy-deepseek',
 profiles:[{id:'legacy-deepseek',name:'DeepSeek',provider:'openai',service_preset:'deepseek',base_url:'https://api.deepseek.com/v1',model:'deepseek-chat',max_tokens:16000,vision:false,secret_status:'saved'}],
 presets:{deepseek:{label:'DeepSeek',official_url:'https://www.deepseek.com/',api_key_url:'https://platform.deepseek.com/api_keys'}}
});
console.log(JSON.stringify(result));
'''
    result = json.loads(run_node(script, runtime))
    assert result["compatibility_mode"] == "legacy"
    assert result["models"][0]["model"] == "deepseek-chat"
    assert result["assignments"]["base_model_id"] == "legacy-model-legacy-deepseek"
    assert result["presets"]["deepseek"]["api_key_url"].endswith("/api_keys")


def test_output_limit_state_preserves_manual_values_and_restores_recommendation():
    runtime = Path(__file__).parents[1] / "js" / "model.js"
    script = r'''
const fs=require('fs'),vm=require('vm');
const sandbox={window:{}};vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),sandbox);
const api=sandbox.window.ModelSettings;
const capability={max_output_tokens:384000,source:'api',source_label:'接口返回 · 384,000'};
console.log(JSON.stringify({
 selected:api.nextOutputLimitState({value:16000,source:'legacy'},capability,{modelChanged:true}),
 refreshed:api.nextOutputLimitState({value:120000,source:'manual',recommended:384000},capability,{modelChanged:false}),
 restored:api.restoreOutputLimitState({value:120000,source:'manual',recommended:384000,recommendationSource:'api',recommendationLabel:'接口返回 · 384,000'}),
 unknown:api.nextOutputLimitState({value:16000,source:'legacy'},{max_output_tokens:null,source:'unknown',source_label:'上限未识别'},{modelChanged:true})
}));
'''
    result = json.loads(run_node(script, runtime))
    assert result["selected"]["value"] == 384000
    assert result["selected"]["source"] == "api"
    assert result["refreshed"]["value"] == 120000
    assert result["refreshed"]["source"] == "manual"
    assert result["restored"]["value"] == 384000
    assert result["restored"]["source"] == "api"
    assert result["unknown"]["value"] == 16000
    assert result["unknown"]["source"] == "unknown"
    assert result["unknown"]["recommended"] is None


def test_discovered_models_are_visible_and_can_fill_model_name():
    harness = Path(__file__).parents[1] / "tests" / "ui_runtime_harness.js"
    script = r'''
const {createHarness}=require(process.argv[1]);
const h=createHarness({request:async(path,options)=>{
  if(path==='/api/llm/models/list') return {models:[
    {model_id:'deepseek-v4-flash',max_output_tokens:384000,source:'api',source_label:'接口返回 · 384,000'},
    {model_id:'deepseek-v4-pro',max_output_tokens:null,source:'unknown',source_label:'上限未识别'}
  ]};
  return {};
}});
(async()=>{
  h.clickAction('discover-models');
  await h.drain();
  const list=h.get('#modelDiscoveryList');
  const before={hidden:list.hidden,labels:list.children.map(x=>x.textContent)};
  h.clickAction('choose-discovered-model',list.children[1]);
  console.log(JSON.stringify({before,chosen:h.get('#modelName').value,status:h.get('#modelStatus').textContent}));
})();
'''
    result = json.loads(run_node(script, harness))
    assert result == {
        "before": {
            "hidden": False,
            "labels": ["deepseek-v4-flash", "deepseek-v4-pro"],
        },
        "chosen": "deepseek-v4-pro",
        "status": "已选择 deepseek-v4-pro。",
    }


def test_discovered_limit_can_be_overridden_refreshed_and_restored():
    harness = Path(__file__).parents[1] / "tests" / "ui_runtime_harness.js"
    script = r'''
const {createHarness}=require(process.argv[1]);
const h=createHarness({request:async(path)=>{
  if(path==='/api/llm/models/list') return {models:[
    {model_id:'deepseek-v4-flash',max_output_tokens:384000,source:'api',source_label:'接口返回 · 384,000'}
  ]};
  return {};
}});
(async()=>{
  h.get('#modelProfileName').value='Token Rhythm';
  h.get('#modelProvider').value='openai';
  h.get('#modelServicePreset').value='custom';
  h.get('#modelBaseUrl').value='https://example.invalid/v1';
  h.get('#modelApiKey').value='runtime-only';
  h.clickAction('discover-models'); await h.drain();
  const option=h.get('#modelDiscoveryList').children[0];
  h.clickAction('choose-discovered-model',option); await h.drain();
  const selected={value:h.get('#modelMaxTokens').value,source:h.get('#modelMaxTokens').dataset.source,hint:h.get('#modelMaxTokensHint').textContent};
  h.get('#modelMaxTokens').value='120000';
  h.get('#modelMaxTokens').dispatch('input');
  h.clickAction('discover-models'); await h.drain();
  h.clickAction('choose-discovered-model',h.get('#modelDiscoveryList').children[0]); await h.drain();
  const refreshed={value:h.get('#modelMaxTokens').value,source:h.get('#modelMaxTokens').dataset.source};
  h.clickAction('restore-model-max-tokens'); await h.drain();
  console.log(JSON.stringify({selected,refreshed,restored:{value:h.get('#modelMaxTokens').value,source:h.get('#modelMaxTokens').dataset.source},payload:h.window.ModelSettings.profilePayload(h.document)}));
})();
'''
    result = json.loads(run_node(script, harness))
    assert result["selected"] == {
        "value": 384000, "source": "api", "hint": "接口返回 · 384,000",
    }
    assert result["refreshed"] == {"value": "120000", "source": "manual"}
    assert result["restored"] == {"value": 384000, "source": "api"}
    assert result["payload"]["max_tokens_source"] == "api"
    assert result["payload"]["recommended_max_tokens"] == 384000


def test_manual_model_name_requests_local_output_recommendation():
    harness = Path(__file__).parents[1] / "tests" / "ui_runtime_harness.js"
    script = r'''
const {createHarness}=require(process.argv[1]);
let submitted=null;
const h=createHarness({request:async(path,options)=>{
  if(path==='/api/llm/models/recommend') {
    submitted=options.payload;
    return {model_id:'gpt-4o',max_output_tokens:16384,source:'catalog',source_label:'官方目录 · 16,384'};
  }
  return {};
}});
(async()=>{
  h.get('#modelServicePreset').value='custom';
  h.get('#modelName').value='gpt-4o';
  h.get('#modelName').dispatch('change'); await h.drain();
  console.log(JSON.stringify({submitted,value:h.get('#modelMaxTokens').value,source:h.get('#modelMaxTokens').dataset.source}));
})();
'''
    result = json.loads(run_node(script, harness))
    assert result == {
        "submitted": {"model": "gpt-4o", "service_preset": "custom"},
        "value": 16384,
        "source": "catalog",
    }


def test_choosing_a_different_discovered_model_replaces_manual_limit():
    harness = Path(__file__).parents[1] / "tests" / "ui_runtime_harness.js"
    script = r'''
const {createHarness}=require(process.argv[1]);
const h=createHarness({request:async(path)=>{
  if(path==='/api/llm/models/list') return {models:[
    {model_id:'deepseek-v4-flash',max_output_tokens:384000,source:'api',source_label:'接口返回 · 384,000'},
    {model_id:'gpt-4o',max_output_tokens:16384,source:'catalog',source_label:'官方目录 · 16,384'}
  ]};
  return {};
}});
(async()=>{
  h.clickAction('discover-models'); await h.drain();
  const list=h.get('#modelDiscoveryList');
  h.clickAction('choose-discovered-model',list.children[0]);
  h.get('#modelMaxTokens').value='120000'; h.get('#modelMaxTokens').dispatch('input');
  h.clickAction('choose-discovered-model',list.children[1]);
  console.log(JSON.stringify({model:h.get('#modelName').value,value:h.get('#modelMaxTokens').value,source:h.get('#modelMaxTokens').dataset.source,hint:h.get('#modelMaxTokensHint').textContent}));
})();
'''
    result = json.loads(run_node(script, harness))
    assert result == {
        "model": "gpt-4o",
        "value": 16384,
        "source": "catalog",
        "hint": "官方目录 · 16,384",
    }


def test_provider_preset_requests_local_output_recommendation():
    harness = Path(__file__).parents[1] / "tests" / "ui_runtime_harness.js"
    script = r'''
const {createHarness}=require(process.argv[1]);
let submitted=null;
const h=createHarness({request:async(path,options)=>{
  if(path==='/api/llm/models/recommend') {
    submitted=options.payload;
    return {model_id:'gpt-4o',max_output_tokens:16384,source:'catalog',source_label:'官方目录 · 16,384'};
  }
  return {};
}});
(async()=>{
  h.clickAction('preset-openai'); await h.drain();
  console.log(JSON.stringify({submitted,model:h.get('#modelName').value,value:h.get('#modelMaxTokens').value,source:h.get('#modelMaxTokens').dataset.source}));
})();
'''
    result = json.loads(run_node(script, harness))
    assert result == {
        "submitted": {"model": "gpt-4o", "service_preset": "openai"},
        "model": "gpt-4o",
        "value": 16384,
        "source": "catalog",
    }


def test_discovery_applies_adjusted_v1_url():
    harness = Path(__file__).parents[1] / "tests" / "ui_runtime_harness.js"
    script = r'''
const {createHarness}=require(process.argv[1]);
const h=createHarness({request:async(path)=>{
  if(path==='/api/llm/models/list') return {models:['gemini-3.6-flash'],base_url:'http://example.invalid:3000/v1',base_url_adjusted:true};
  return {};
}});
(async()=>{
  h.get('#modelBaseUrl').value='http://example.invalid:3000';
  h.clickAction('discover-models');
  await h.drain();
  console.log(JSON.stringify({url:h.get('#modelBaseUrl').value,status:h.get('#modelStatus').textContent}));
})();
'''
    result = json.loads(run_node(script, harness))
    assert result == {
        "url": "http://example.invalid:3000/v1",
        "status": "已自动补全 /v1，读取 1 个模型。",
    }


def test_discovery_uses_current_form_when_editing_saved_connection():
    harness = Path(__file__).parents[1] / "tests" / "ui_runtime_harness.js"
    script = r'''
const {createHarness}=require(process.argv[1]);
let submitted=null;
const h=createHarness({request:async(path,options)=>{
  if(path==='/api/llm/models/list') {submitted=options.payload;return {models:[]};}
  return {};
}});
(async()=>{
  h.get('#modelConnectionId').value='conn-1';
  h.clickAction('discover-models');
  await h.drain();
  console.log(JSON.stringify(submitted));
})();
'''
    result = json.loads(run_node(script, harness))
    assert result["connection"]["id"] == "conn-1"
    assert "connection_id" not in result


def test_saving_workbench_model_clears_submitted_key():
    harness = Path(__file__).parents[1] / "tests" / "ui_runtime_harness.js"
    script = r'''
const {createHarness}=require(process.argv[1]);
const h=createHarness({request:async(path)=>{
  if(path==='/api/llm/connections/save') return {id:'conn-1',name:'DeepSeek',secret_status:'saved'};
  if(path==='/api/llm/models/save') return {id:'model-1',connection_id:'conn-1',model:'deepseek-v4-flash'};
  if(path==='/api/llm/workbench') throw new Error('stop after save');
  return {};
}});
(async()=>{
  h.get('#modelApiKey').value='session-secret';
  h.clickAction('save-workbench-model');
  await h.drain();
  console.log(JSON.stringify({value:h.get('#modelApiKey').value,placeholder:h.get('#modelApiKey').placeholder}));
})();
'''
    result = json.loads(run_node(script, harness))
    assert result == {
        "value": "",
        "placeholder": "已安全保存；留空则保持不变",
    }
