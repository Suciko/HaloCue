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
    assert list(credentials.values.values()) == ["web-secret-value"]


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
  '#modelBaseUrl':{value:'https://example.invalid/v1',style:{}},
  '#modelName':{value:'vision-model',style:{}},
  '#modelMaxTokens':{value:'24000',style:{}},
  '#modelVision':{checked:true,style:{}},
  '#modelApiKey':{value:'session-value',style:{}},
  '#modelSaveKey':{checked:true,style:{}},
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
    assert result["credentialChoice"] is True
    assert result["payload"] == {
        "id": "profile-7",
        "name": "My endpoint",
        "provider": "openai",
        "base_url": "https://example.invalid/v1",
        "model": "vision-model",
        "max_tokens": 24000,
        "vision": True,
        "api_key": "session-value",
        "save_key": True,
    }


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
