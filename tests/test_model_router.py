import pytest

import model_profiles
import model_router


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


def make_router(tmp_path, monkeypatch):
    credentials = FakeCredentials()
    store = model_profiles.ModelProfileStore(tmp_path / "profiles.json", credentials=credentials)
    connection = store.save_connection({
        "name": "Models", "service_preset": "custom", "protocol": "openai",
        "base_url": "https://example.invalid/v1", "api_key": "runtime-secret",
    })
    text = store.save_model({
        "connection_id": connection["id"], "model": "text-model",
        "text_status": "passed", "vision_status": "unsupported",
    })
    vision = store.save_model({
        "connection_id": connection["id"], "model": "vision-model",
        "text_status": "passed", "vision_status": "passed",
    })
    store.set_assignments({
        "base_model_id": text["id"], "vision_mode": "separate", "vision_model_id": vision["id"],
    })

    class FakeProvider:
        def __init__(self, name, settings):
            self.name = name
            self.model = settings["model"]
            self.settings = settings

    monkeypatch.setattr(model_router.llm, "make_provider_from_settings", FakeProvider)
    return model_router.ModelRouter(store), store, text, vision


def test_text_always_uses_base_model(tmp_path, monkeypatch):
    router, store, text, vision = make_router(tmp_path, monkeypatch)
    store.set_assignments({
        "base_model_id": text["id"], "vision_mode": "separate", "vision_model_id": vision["id"],
    })

    assert router.text_provider().model == "text-model"


def test_separate_vision_uses_vision_model(tmp_path, monkeypatch):
    router, _, _, _ = make_router(tmp_path, monkeypatch)

    assert router.vision_provider().model == "vision-model"


def test_disabled_vision_returns_none(tmp_path, monkeypatch):
    router, store, text, _ = make_router(tmp_path, monkeypatch)
    store.set_assignments({"base_model_id": text["id"], "vision_mode": "disabled"})

    assert router.vision_provider() is None


def test_base_vision_requires_passed_status(tmp_path, monkeypatch):
    router, store, text, _ = make_router(tmp_path, monkeypatch)
    store.save_model({
        "id": text["id"], "connection_id": store.public_state()["models"][0]["connection_id"],
        "model": "text-model", "text_status": "passed", "vision_status": "untested",
    })
    store.set_assignments({"base_model_id": text["id"], "vision_mode": "disabled"})

    with pytest.raises(model_profiles.ModelProfileError, match="图片测试"):
        router.one_shot_base_fallback()
