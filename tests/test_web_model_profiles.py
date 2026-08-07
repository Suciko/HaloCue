import contextlib
import json
import subprocess
import threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import llm
import webui
from model_profiles import ModelProfileStore
from webui import H


class FakeCredentials:
    available = True

    def __init__(self):
        self.values = {}

    def read(self, target):
        return self.values.get(target)

    def write(self, target, secret):
        self.values[target] = secret

    def delete(self, target):
        self.values.pop(target, None)


@contextlib.contextmanager
def model_server(tmp_path, monkeypatch):
    credentials = FakeCredentials()
    store = ModelProfileStore(
        tmp_path / "llm_profiles.json",
        credentials=credentials,
    )
    monkeypatch.setattr(webui, "MODEL_PROFILES", store, raising=False)
    server = ThreadingHTTPServer(("127.0.0.1", 0), H)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield (
            f"http://127.0.0.1:{server.server_port}",
            store,
            credentials,
        )
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def request_json(base, path, payload=None):
    if payload is None:
        request = Request(base + path)
    else:
        request = Request(
            base + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
    try:
        with urlopen(request) as response:
            return response.status, json.loads(response.read())
    except HTTPError as response:
        return response.status, json.loads(response.read())


def test_web_model_profile_api_never_returns_or_persists_api_key(
    tmp_path, monkeypatch
):
    with model_server(tmp_path, monkeypatch) as (
        base,
        _store,
        credentials,
    ):
        status, saved = request_json(
            base,
            "/api/llm/profiles/save",
            {
                "name": "Configurable endpoint",
                "provider": "openai",
                "base_url": "https://example.invalid/v1",
                "model": "any-vision-model",
                "api_key": "web-secret-value",
                "save_key": True,
                "vision": True,
            },
        )
        get_status, state = request_json(base, "/api/llm/profiles")

    assert status == get_status == 200
    assert saved["secret_status"] == "saved"
    assert "api_key" not in saved
    assert "api_key" not in json.dumps(state)
    assert "web-secret-value" not in (
        tmp_path / "llm_profiles.json"
    ).read_text(encoding="utf-8")
    assert set(credentials.values.values()) == {"web-secret-value"}


def test_web_model_profile_can_activate_and_delete_saved_credential(
    tmp_path, monkeypatch
):
    with model_server(tmp_path, monkeypatch) as (
        base,
        _store,
        credentials,
    ):
        _, first = request_json(
            base,
            "/api/llm/profiles/save",
            {
                "name": "First",
                "provider": "openai",
                "model": "model-a",
                "api_key": "first-value",
                "save_key": True,
            },
        )
        _, second = request_json(
            base,
            "/api/llm/profiles/save",
            {
                "name": "Second",
                "provider": "anthropic",
                "model": "model-b",
                "api_key": "second-value",
                "save_key": True,
            },
        )
        status, active = request_json(
            base,
            "/api/llm/profiles/activate",
            {"id": first["id"]},
        )
        delete_status, deleted = request_json(
            base,
            "/api/llm/profiles/delete",
            {"id": first["id"], "delete_credential": True},
        )
        _, state = request_json(base, "/api/llm/profiles")

    assert status == delete_status == 200
    assert active["id"] == first["id"]
    assert deleted == {"ok": True}
    assert state["active_profile_id"] == second["id"]
    assert f"AA-AutoWriter/{first['id']}" not in credentials.values


def test_web_model_discovery_and_connection_test_use_selected_profile(
    tmp_path, monkeypatch
):
    calls = []

    class FakeProvider:
        model = "chosen-model"

        def list_models(self):
            return ["model-a", "model-b"]

        def complete_json(self, system, volatile, user, schema):
            calls.append(("text", system, user, schema))
            return {"ok": True}

        def complete_json_vision(self, system, images, user, schema):
            calls.append(("vision", len(images), user, schema))
            return {"ok": True}

    def make_provider(name, settings):
        calls.append(("provider", name, dict(settings)))
        return FakeProvider()

    monkeypatch.setattr(llm, "make_provider_from_settings", make_provider)
    with model_server(tmp_path, monkeypatch) as (base, _store, _credentials):
        _, saved = request_json(
            base,
            "/api/llm/profiles/save",
            {
                "name": "Chosen",
                "provider": "openai",
                "base_url": "https://example.invalid/v1",
                "model": "chosen-model",
                "api_key": "runtime-value",
                "save_key": False,
                "vision": True,
            },
        )
        models_status, models = request_json(
            base,
            "/api/llm/models",
            {"id": saved["id"]},
        )
        text_status, text_result = request_json(
            base,
            "/api/llm/test",
            {"id": saved["id"], "mode": "text"},
        )
        vision_status, vision_result = request_json(
            base,
            "/api/llm/test",
            {"id": saved["id"], "mode": "vision"},
        )

    assert models_status == text_status == vision_status == 200
    assert models == {"models": ["model-a", "model-b"]}
    assert text_result == {
        "ok": True,
        "mode": "text",
        "model": "chosen-model",
    }
    assert vision_result == {
        "ok": True,
        "mode": "vision",
        "model": "chosen-model",
    }
    provider_calls = [call for call in calls if call[0] == "provider"]
    assert provider_calls[0][1:] == (
        "openai",
        {
            "model": "chosen-model",
            "base_url": "https://example.invalid/v1",
            "max_tokens": 16000,
            "vision": True,
            "api_key": "runtime-value",
        },
    )
    assert {call[0] for call in calls} >= {"text", "vision"}


def test_web_model_test_accepts_unsaved_form_payload(tmp_path, monkeypatch):
    calls = []

    class FakeProvider:
        model = "deepseek-chat"

        def complete_json(self, *args):
            calls.append("text")
            return {"ok": True}

    monkeypatch.setattr(llm, "make_provider_from_settings", lambda name, settings: FakeProvider())
    with model_server(tmp_path, monkeypatch) as (base, _store, _credentials):
        status, result = request_json(base, "/api/llm/test", {
            "mode": "text",
            "profile": {
                "name": "Unsaved DeepSeek",
                "provider": "openai",
                "service_preset": "deepseek",
                "base_url": "https://api.deepseek.com/v1",
                "model": "deepseek-chat",
                "max_tokens": 16000,
                "vision": False,
                "api_key": "runtime-value",
            },
        })

    assert status == 200
    assert result["model"] == "deepseek-chat"
    assert calls == ["text"]


def test_workbench_api_saves_connection_model_and_assignment_without_secret(
    tmp_path, monkeypatch
):
    with model_server(tmp_path, monkeypatch) as (base, _store, credentials):
        status, connection = request_json(base, "/api/llm/connections/save", {
            "name": "DeepSeek 文字",
            "service_preset": "deepseek",
            "protocol": "openai",
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "workbench-secret",
        })
        model_status, model = request_json(base, "/api/llm/models/save", {
            "connection_id": connection["id"],
            "model": "deepseek-chat",
            "text_status": "passed",
            "vision_status": "unsupported",
        })
        assignment_status, assignment = request_json(base, "/api/llm/assignments/save", {
            "base_model_id": model["id"], "vision_mode": "disabled",
        })
        state_status, state = request_json(base, "/api/llm/workbench")

    serialized = json.dumps(state)
    assert status == model_status == assignment_status == state_status == 200
    assert assignment["base_model_id"] == model["id"]
    assert "workbench-secret" not in serialized
    assert "api_key" not in json.dumps(connection)
    assert credentials.values


def test_model_list_retries_root_openai_url_with_v1(tmp_path, monkeypatch):
    attempted_urls = []

    class FakeProvider:
        def __init__(self, settings):
            self.base_url = settings["base_url"]

        def list_models(self):
            attempted_urls.append(self.base_url)
            if not self.base_url.endswith("/v1"):
                raise llm.LLMError("接口没有返回合法 JSON")
            return ["gemini-3.6-flash"]

    monkeypatch.setattr(
        llm,
        "make_provider_from_settings",
        lambda _name, settings: FakeProvider(settings),
    )
    with model_server(tmp_path, monkeypatch) as (base, _store, _credentials):
        status, result = request_json(base, "/api/llm/models/list", {
            "connection": {
                "name": "Gemini 视觉",
                "service_preset": "custom",
                "protocol": "openai",
                "base_url": "http://example.invalid:3000",
                "api_key": "runtime-secret",
            },
            "model": {"model": "gemini-3.6-flash"},
        })

    assert status == 200
    assert attempted_urls == [
        "http://example.invalid:3000",
        "http://example.invalid:3000/v1",
    ]
    assert result == {
        "models": ["gemini-3.6-flash"],
        "base_url": "http://example.invalid:3000/v1",
        "base_url_adjusted": True,
    }


def test_workbench_model_list_returns_resolved_capability_objects(tmp_path, monkeypatch):
    class FakeProvider:
        def list_model_records(self):
            return [{
                "id": "deepseek-v4-flash", "context_length": 1_000_000,
                "max_output_tokens": 384_000,
                "max_output_field": "max_completion_tokens",
            }]

    monkeypatch.setattr(llm, "make_provider_from_settings", lambda _name, _settings: FakeProvider())
    with model_server(tmp_path, monkeypatch) as (base, _store, _credentials):
        status, result = request_json(base, "/api/llm/models/list", {
            "connection": {
                "name": "DeepSeek", "service_preset": "deepseek", "protocol": "openai",
                "base_url": "https://api.deepseek.com/v1", "api_key": "runtime-secret",
            },
            "model": {"model": "deepseek-v4-flash"},
        })

    assert status == 200
    assert result["models"] == [{
        "model_id": "deepseek-v4-flash", "context_length": 1_000_000,
        "max_output_tokens": 384_000, "source": "api",
        "source_label": "接口返回 · 384,000", "source_url": "", "verified_at": "",
    }]


def test_local_model_recommendation_is_offline_and_does_not_require_secret(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "make_provider_from_settings", lambda *_args: (_ for _ in ()).throw(AssertionError("network")))
    with model_server(tmp_path, monkeypatch) as (base, _store, _credentials):
        status, result = request_json(base, "/api/llm/models/recommend", {
            "model": "gpt-4o-2024-11-20", "service_preset": "custom",
        })

    assert status == 200
    assert result["max_output_tokens"] == 16384
    assert result["source"] == "catalog"


def test_local_model_recommendation_never_uses_context_length(tmp_path, monkeypatch):
    with model_server(tmp_path, monkeypatch) as (base, _store, _credentials):
        status, result = request_json(base, "/api/llm/models/recommend", {
            "model": "unlisted-model", "service_preset": "custom",
        })

    assert status == 200
    assert result["max_output_tokens"] is None
    assert result["source"] == "unknown"


def test_current_model_status_uses_v2_base_and_vision_assignments(
    tmp_path, monkeypatch
):
    store = ModelProfileStore(
        tmp_path / "profiles.json",
        credentials=FakeCredentials(),
    )
    base_connection = store.save_connection({
        "name": "DeepSeek 官方", "service_preset": "deepseek",
        "protocol": "openai", "base_url": "https://api.deepseek.com/v1",
        "api_key": "base-secret",
    })
    base_model = store.save_model({
        "connection_id": base_connection["id"], "model": "deepseek-v4-flash",
        "text_status": "passed", "vision_status": "unsupported",
    })
    vision_connection = store.save_connection({
        "name": "Gemini 视觉", "service_preset": "custom",
        "protocol": "openai", "base_url": "https://example.invalid/v1",
        "api_key": "vision-secret",
    })
    vision_model = store.save_model({
        "connection_id": vision_connection["id"], "model": "gemini-3.6-flash",
        "text_status": "untested", "vision_status": "passed",
    })
    store.set_assignments({
        "base_model_id": base_model["id"],
        "vision_mode": "separate",
        "vision_model_id": vision_model["id"],
    })
    monkeypatch.setattr(webui, "MODEL_PROFILES", store)

    assert webui.current_model_status() == {
        "configured": True,
        "name": "DeepSeek 官方",
        "model": "deepseek-v4-flash",
        "vision_name": "Gemini 视觉",
        "vision_model": "gemini-3.6-flash",
    }


def test_legacy_profile_save_is_visible_in_v2_workbench(tmp_path, monkeypatch):
    with model_server(tmp_path, monkeypatch) as (base, _store, credentials):
        status, profile = request_json(base, "/api/llm/profiles/save", {
            "name": "DeepSeek 文字",
            "service_preset": "deepseek",
            "provider": "openai",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "api_key": "profile-secret",
            "vision": False,
        })
        workbench_status, state = request_json(base, "/api/llm/workbench")

    assert status == workbench_status == 200
    assert any(row["model"] == "deepseek-chat" for row in state["models"])
    assert "profile-secret" not in json.dumps(state)
    assert credentials.values


def test_profile_saved_after_v2_migration_is_visible_in_workbench(tmp_path, monkeypatch):
    with model_server(tmp_path, monkeypatch) as (base, _store, _credentials):
        _, first = request_json(base, "/api/llm/profiles/save", {
            "name": "First", "provider": "openai", "service_preset": "deepseek",
            "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat",
            "api_key": "first-secret", "vision": False,
        })
        request_json(base, "/api/llm/workbench")
        _, second = request_json(base, "/api/llm/profiles/save", {
            "name": "Second", "provider": "openai", "service_preset": "qwen",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model": "qwen-vl-max", "api_key": "second-secret", "vision": True,
        })
        _, state = request_json(base, "/api/llm/workbench")

    names = {row["model"] for row in state["models"]}
    assert first["model"] in names
    assert second["model"] in names


def test_workbench_assignment_rejects_untested_base_vision_model(tmp_path, monkeypatch):
    with model_server(tmp_path, monkeypatch) as (base, _store, _credentials):
        _, connection = request_json(base, "/api/llm/connections/save", {
            "name": "Text", "service_preset": "custom", "protocol": "openai",
            "base_url": "https://example.invalid/v1", "api_key": "secret",
        })
        _, model = request_json(base, "/api/llm/models/save", {
            "connection_id": connection["id"], "model": "text-only",
            "text_status": "passed", "vision_status": "untested",
        })
        status, result = request_json(base, "/api/llm/assignments/save", {
            "base_model_id": model["id"], "vision_mode": "base",
        })

    assert status == 400
    assert "图片测试" in result["e"]


def test_workbench_delete_model_endpoint_cleans_empty_connection(tmp_path, monkeypatch):
    with model_server(tmp_path, monkeypatch) as (base, _store, _credentials):
        _, base_connection = request_json(base, "/api/llm/connections/save", {
            "name": "Base", "service_preset": "deepseek", "protocol": "openai",
            "base_url": "https://api.deepseek.com/v1", "api_key": "base-secret",
        })
        _, base_model = request_json(base, "/api/llm/models/save", {
            "connection_id": base_connection["id"], "model": "deepseek-v4-flash",
            "text_status": "passed", "vision_status": "unsupported",
        })
        request_json(base, "/api/llm/assignments/save", {
            "base_model_id": base_model["id"], "vision_mode": "disabled",
        })
        _, spare_connection = request_json(base, "/api/llm/connections/save", {
            "name": "Spare", "service_preset": "qwen", "protocol": "openai",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_key": "spare-secret",
        })
        _, spare_model = request_json(base, "/api/llm/models/save", {
            "connection_id": spare_connection["id"], "model": "qwen-vl-max",
        })

        status, result = request_json(base, "/api/llm/models/delete", {
            "id": spare_model["id"], "delete_empty_connection": True,
        })
        _, state = request_json(base, "/api/llm/workbench")

    assert status == 200
    assert result["deleted_connection"] is True
    assert spare_model["id"] not in {row["id"] for row in state["models"]}
    assert spare_connection["id"] not in {row["id"] for row in state["connections"]}


def test_workbench_test_updates_model_capability_status(tmp_path, monkeypatch):
    class FakeProvider:
        model = "qwen-vl-plus"

        def complete_json_vision(self, *args):
            return {"ok": True}

        def complete_json(self, *args):
            return {"ok": True}

    monkeypatch.setattr(llm, "make_provider_from_settings", lambda name, settings: FakeProvider())
    with model_server(tmp_path, monkeypatch) as (base, _store, _credentials):
        _, connection = request_json(base, "/api/llm/connections/save", {
            "name": "Qwen", "service_preset": "qwen", "protocol": "openai",
            "base_url": "https://example.invalid/v1", "api_key": "secret",
        })
        _, model = request_json(base, "/api/llm/models/save", {
            "connection_id": connection["id"], "model": "qwen-vl-plus",
        })
        status, result = request_json(base, "/api/llm/models/test", {
            "id": model["id"], "mode": "vision",
        })
        _, state = request_json(base, "/api/llm/workbench")

    saved = next(row for row in state["models"] if row["id"] == model["id"])
    assert status == 200
    assert result["mode"] == "vision"
    assert saved["vision_status"] == "passed"


def test_workbench_errors_redact_credentials_and_absolute_paths(tmp_path, monkeypatch):
    class FailingProvider:
        model = "broken-model"

        def complete_json(self, *args):
            raise llm.LLMError(
                "Authorization: Bearer top-secret; cannot read C:\\private\\model.json"
            )

    monkeypatch.setattr(llm, "make_provider_from_settings", lambda name, settings: FailingProvider())
    with model_server(tmp_path, monkeypatch) as (base, _store, _credentials):
        _, connection = request_json(base, "/api/llm/connections/save", {
            "name": "Broken", "service_preset": "custom", "protocol": "openai",
            "base_url": "https://example.invalid/v1", "api_key": "secret",
        })
        _, model = request_json(base, "/api/llm/models/save", {
            "connection_id": connection["id"], "model": "broken-model",
        })
        status, result = request_json(base, "/api/llm/models/test", {
            "id": model["id"], "mode": "text",
        })

    assert status == 400
    assert "top-secret" not in json.dumps(result)
    assert "C:\\private" not in json.dumps(result)
    assert "模型连接测试失败" in result["e"]


def test_web_model_settings_form_builds_complete_redacted_profile_payload():
    ui = Path(__file__).parents[1] / "ui.html"
    runtime = Path(__file__).parents[1] / "js" / "model.js"
    script = r'''
const fs=require('fs'),vm=require('vm');
const html=fs.readFileSync(process.argv[1],'utf8');
const runtime=fs.readFileSync(process.argv[2],'utf8');
const nodes={
  '#modelProfileId':{value:'profile-7',style:{}},
  '#modelProfileName':{value:'My endpoint',style:{}},
  '#modelProvider':{value:'openai',style:{}},
  '#modelServicePreset':{value:'deepseek',style:{}},
  '#modelBaseUrl':{value:'https://example.invalid/v1',style:{}},
  '#modelName':{value:'vision-model',style:{}},
  '#modelMaxTokens':{value:'24000',dataset:{source:'manual',recommended:'384000',recommendationSource:'api',recommendationLabel:'接口返回 · 384,000'},style:{}},
  '#modelVision':{checked:true,style:{}},
  '#modelApiKey':{value:'session-value',style:{}},
};
const document={
  querySelector:s=>nodes[s]||(nodes[s]={value:'',checked:false,style:{},textContent:'',innerHTML:'',classList:{add(){},remove(){}},addEventListener(){}}),
  querySelectorAll:()=>[]
};
const sandbox={document,console,window:{}};
vm.runInNewContext(runtime,sandbox);
console.log(JSON.stringify({
  payload:sandbox.window.ModelSettings.profilePayload(document),
  passwordField:/<input[^>]+id="modelApiKey"[^>]+type="password"/i.test(html),
  credentialChoice:html.includes('id="modelSaveKey"')
}));
'''
    output = subprocess.check_output(
        ["node", "-e", script, str(ui), str(runtime)],
        text=True,
        encoding="utf-8",
    )
    result = json.loads(output)

    assert result["passwordField"] is True
    assert result["credentialChoice"] is False
    assert result["payload"] == {
        "id": "profile-7",
        "name": "My endpoint",
        "provider": "openai",
        "service_preset": "deepseek",
        "base_url": "https://example.invalid/v1",
        "model": "vision-model",
        "max_tokens": 24000,
        "max_tokens_source": "manual",
        "recommended_max_tokens": 384000,
        "recommended_source": "api",
        "recommended_label": "接口返回 · 384,000",
        "vision": True,
        "api_key": "session-value",
    }


def test_model_profile_helpers_create_a_named_draft_and_detect_unsaved_changes():
    runtime = Path(__file__).parents[1] / "js" / "model.js"
    script = r'''
const fs=require('fs'),vm=require('vm');
const runtime=fs.readFileSync(process.argv[1],'utf8');
const sandbox={window:{}};vm.runInNewContext(runtime,sandbox);
const api=sandbox.window.ModelSettings;
const draft=api.newProfileDraft();
console.log(JSON.stringify({draft,clean:api.profileChanged(draft,draft),dirty:api.profileChanged(draft,Object.assign({},draft,{model:'deepseek-reasoner'})),keyDirty:api.profileChanged(draft,Object.assign({},draft,{api_key:'new-secret'}))}));
'''
    output = subprocess.check_output(["node", "-e", script, str(runtime)], text=True, encoding="utf-8")
    result = json.loads(output)

    assert result["draft"]["id"] == ""
    assert result["draft"]["name"] == "新模型配置"
    assert result["draft"]["service_preset"] == "custom"
    assert result["clean"] is False
    assert result["dirty"] is True
    assert result["keyDirty"] is True


def test_annotation_provider_uses_selected_web_profile(tmp_path, monkeypatch):
    credentials = FakeCredentials()
    store = ModelProfileStore(
        tmp_path / "profiles.json",
        credentials=credentials,
    )
    profile = store.save_profile(
        {
            "name": "Selected",
            "provider": "openai",
            "model": "selected-model",
            "api_key": "runtime-value",
            "save_key": False,
        }
    )
    sentinel = object()
    captured = {}

    def make_provider(name, settings):
        captured.update(name=name, settings=settings)
        return sentinel

    monkeypatch.setattr(webui, "MODEL_PROFILES", store)
    monkeypatch.setattr(llm, "make_provider_from_settings", make_provider)

    assert webui.annotation_provider(profile["id"]) is sentinel
    assert captured["name"] == "openai"
    assert captured["settings"]["model"] == "selected-model"
    assert captured["settings"]["api_key"] == "runtime-value"


def test_annotation_provider_without_explicit_profile_uses_base_assignment(tmp_path, monkeypatch):
    credentials = FakeCredentials()
    store = ModelProfileStore(tmp_path / "profiles.json", credentials=credentials)
    connection = store.save_connection({
        "name": "Roles", "service_preset": "custom", "protocol": "openai",
        "base_url": "https://example.invalid/v1", "api_key": "runtime-value",
    })
    base = store.save_model({
        "connection_id": connection["id"], "model": "base-model",
        "text_status": "passed", "vision_status": "unsupported",
    })
    vision = store.save_model({
        "connection_id": connection["id"], "model": "vision-model",
        "text_status": "passed", "vision_status": "passed",
    })
    store.set_assignments({
        "base_model_id": base["id"], "vision_mode": "separate", "vision_model_id": vision["id"],
    })
    captured = {}

    def make_provider(name, settings):
        captured.update(name=name, settings=settings)
        return object()

    monkeypatch.setattr(webui, "MODEL_PROFILES", store)
    monkeypatch.setattr(llm, "make_provider_from_settings", make_provider)

    webui.annotation_provider()

    assert captured["settings"]["model"] == "base-model"


def test_annotation_provider_ignores_stale_legacy_profile_for_v2_assignments(
    tmp_path, monkeypatch
):
    credentials = FakeCredentials()
    store = ModelProfileStore(tmp_path / "profiles.json", credentials=credentials)
    connection = store.save_connection({
        "name": "Current", "service_preset": "custom", "protocol": "openai",
        "base_url": "https://example.invalid/v1", "api_key": "runtime-value",
    })
    base = store.save_model({
        "connection_id": connection["id"], "model": "current-base-model",
        "text_status": "passed", "vision_status": "unsupported",
    })
    store.set_assignments({
        "base_model_id": base["id"], "vision_mode": "disabled",
    })
    captured = {}

    def make_provider(name, settings):
        captured.update(name=name, settings=settings)
        return object()

    monkeypatch.setattr(webui, "MODEL_PROFILES", store)
    monkeypatch.setattr(llm, "make_provider_from_settings", make_provider)

    webui.annotation_provider("deleted-legacy-profile")

    assert captured["settings"]["model"] == "current-base-model"
