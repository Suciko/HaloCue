import base64
import io
import json
import zipfile
from pathlib import Path
import pytest
from halocue_writing.service import WritingService
from halocue_writing.model_settings import WritingModelSettings, UserPreferencesStore, ModelSecretStore
from halocue_writing.providers import LLMWritingProvider
from halocue_writing.errors import DomainError


def test_model_settings_uses_searchable_provider_master_detail_ui():
    web_root = Path(__file__).resolve().parents[1] / "web"
    html = (web_root / "index.html").read_text(encoding="utf-8")
    script = (web_root / "app.js").read_text(encoding="utf-8")
    styles = (web_root / "shell.css").read_text(encoding="utf-8")

    assert 'class="model-config-workspace"' in html
    assert 'id="providerPresetSearch"' in html
    assert 'id="providerPresetCount"' in html
    assert 'id="selectedProviderName"' in html
    assert 'id="selectedProviderNotes"' in html
    assert 'id="selectedProviderProtocol"' in html
    assert 'role="listbox"' in html
    assert "renderProviderPresets()" in script
    assert "updateSelectedProviderSummary(preset)" in script
    assert "providerSearchQuery" in script
    assert 'aria-selected="${selected ? \'true\' : \'false\'}"' in script
    assert ".model-config-workspace {" in styles
    assert "grid-template-columns: 238px minmax(0, 1fr);" in styles
    assert ".model-provider-detail {" in styles
    assert "@media (max-width: 430px)" in styles


def test_model_secret_store_and_settings(tmp_path):
    settings = WritingModelSettings(tmp_path)

    # Initially empty
    pub = settings.public()
    assert pub["ok"] is True
    assert pub["model"]["configured"] is False
    assert len(pub["presets"]) >= 8

    # Save DeepSeek config with key
    saved = settings.save({
        "preset_id": "deepseek",
        "provider": "openai",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "api_key": "sk-test-secret-key-123456",
        "max_tokens": 4096,
        "timeout": 60,
        "reasoning_mode": "balanced",
    })

    assert saved["model"]["configured"] is True
    assert saved["model"]["model"] == "deepseek-chat"
    assert saved["model"]["secret_source"] == "dpapi"

    # Verify secret is loaded without leaking into public JSON
    provider_type, conf = settings.provider_settings()
    assert provider_type == "openai"
    assert conf["api_key"] == "sk-test-secret-key-123456"
    assert conf["model"] == "deepseek-chat"

    # Public JSON file does NOT contain api_key
    file_content = json.loads(settings.path.read_text(encoding="utf-8"))
    assert "api_key" not in file_content


def test_user_preferences_store(tmp_path):
    store = UserPreferencesStore(tmp_path)

    # Defaults
    defaults = store.load()
    assert defaults["writing_tone"] == "bond_short"
    assert defaults["char_warning_threshold"] == 35

    # Save update
    updated = store.save({
        "writing_tone": "main_battle",
        "char_warning_threshold": 40,
        "aa_pacing_wait_ms": 3000,
        "max_stage_characters": 3,
    })

    assert updated["writing_tone"] == "main_battle"
    assert updated["char_warning_threshold"] == 40
    assert updated["aa_pacing_wait_ms"] == 3000
    assert updated["max_stage_characters"] == 3


def test_service_settings_and_diagnostics(tmp_path):
    service = WritingService(tmp_path)

    initial_diag = service.system_diagnostics()
    assert initial_diag["real_provider_run"]["status"] == "blocked"
    assert initial_diag["real_provider_run"]["blocking_reasons"][0]["code"] == (
        "real_provider_credentials_missing"
    )
    assert initial_diag["real_provider_run"]["acceptance_completed"] is False

    # Initial settings
    state = service.writing_model_settings_public()
    assert state["ok"] is True
    assert state["model"]["configured"] is False

    # Configure
    configured = service.configure_writing_model({
        "preset_id": "siliconflow",
        "provider": "openai",
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "deepseek-ai/DeepSeek-V3",
        "api_key": "sk-siliconflow-test",
    })
    assert configured["model"]["configured"] is True

    # Preferences
    prefs = service.user_preferences()
    assert prefs["ok"] is True
    assert prefs["preferences"]["writing_tone"] == "bond_short"

    saved_prefs = service.save_user_preferences({"char_warning_threshold": 50})
    assert saved_prefs["preferences"]["char_warning_threshold"] == 50

    # System Diagnostics
    diag = service.system_diagnostics()
    assert diag["ok"] is True
    assert "writing_service" in diag
    assert "production_service" in diag


def test_full_writing_backup_restores_database_and_content_files(tmp_path):
    service = WritingService(tmp_path)
    original = service.create_work({"title": "可恢复作品", "idea": "保存这条想法。"})
    service.save_work_canon(original["id"], {
        "expected_version": original["version"],
        "facts": [{
            "text": "旧校舍的钟会在傍晚响起。",
            "source": "备份测试",
            "scope": "work",
            "confidence_status": "confirmed",
        }],
    })

    filename, content, summary = service.export_writing_backup()

    assert filename.endswith(".halocue")
    assert summary["work_count"] == 1
    assert summary["work_titles"] == ["可恢复作品"]
    assert "API Key" in summary["excludes"]
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        assert "manifest.json" in archive.namelist()
        assert "data/writing.db" in archive.namelist()
        assert all("writing-model" not in name and "secrets/" not in name for name in archive.namelist())

    service.create_work({"title": "备份后新增", "idea": "恢复后应消失。"})
    payload = {"content_base64": base64.b64encode(content).decode("ascii")}
    inspected = service.inspect_writing_backup(payload)
    restored = service.restore_writing_backup({
        **payload,
        "expected_backup_hash": inspected["backup_hash"],
        "replace_all_works": True,
    })

    assert restored["restored"] is True
    assert restored["safety_backup"].startswith("before-restore-")
    assert [item["title"] for item in service.list_works()] == ["可恢复作品"]
    restored_work = service.get_work(original["id"])
    canon = next(item for item in restored_work["artifacts"] if item["kind"] == "work_canon")
    assert canon["current_revision"]["content"]["facts"][0]["text"] == "旧校舍的钟会在傍晚响起。"


def test_backup_restore_requires_preflight_hash_and_explicit_confirmation(tmp_path):
    service = WritingService(tmp_path)
    service.create_work({"title": "受保护作品"})
    _, content, summary = service.export_writing_backup()
    payload = {"content_base64": base64.b64encode(content).decode("ascii")}

    with pytest.raises(DomainError) as missing_confirmation:
        service.restore_writing_backup({**payload, "expected_backup_hash": summary["backup_hash"]})
    assert missing_confirmation.value.code == "backup_restore_confirmation_required"

    with pytest.raises(DomainError) as stale_preflight:
        service.restore_writing_backup({
            **payload,
            "expected_backup_hash": "sha256:stale",
            "replace_all_works": True,
        })
    assert stale_preflight.value.code == "backup_changed"


def test_backup_inspection_rejects_tampered_content(tmp_path):
    service = WritingService(tmp_path)
    service.create_work({"title": "哈希校验"})
    _, content, _ = service.export_writing_backup()
    source = zipfile.ZipFile(io.BytesIO(content))
    output = io.BytesIO()
    with source, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as changed:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename == "data/writing.db":
                data += b"tampered"
            changed.writestr(info.filename, data)

    with pytest.raises(DomainError) as captured:
        service.inspect_writing_backup({
            "content_base64": base64.b64encode(output.getvalue()).decode("ascii")
        })
    assert captured.value.code == "backup_hash_mismatch"


@pytest.mark.parametrize(
    ("method_name", "args", "operation"),
    [
        ("discuss_work", ([], {}), "作品讨论"),
        ("generate_blueprint", ({"idea": "测试"},), "故事方向生成"),
        ("generate_chapter_plan", ([], {}), "章节细纲生成"),
        ("generate_scene", ({},), "场景起草"),
        ("rewrite_scene", ({}, "爱丽丝: 测试", "重写"), "场景改写"),
    ],
)
def test_real_provider_failure_never_falls_back_to_simulation(monkeypatch, tmp_path, method_name, args, operation):
    service = WritingService(tmp_path / "prompt-pack")
    provider = LLMWritingProvider(
        {
            "provider": "openai",
            "base_url": "https://example.invalid/v1",
            "model": "test-model",
            "api_key": "test-key",
        },
        service.ba_prompt_assembler,
    )

    def fail_call(*_args, **_kwargs):
        raise OSError("network unavailable")

    monkeypatch.setattr(provider, "_call_llm", fail_call)

    if method_name in {"generate_scene", "rewrite_scene"}:
        scene_context = {
            "rules": {"mode_key": "bond_short"},
            "brief": {"mode": "bond_short", "has_sensei": False},
            "scene_contract": {"goal": "测试失败闭合"},
            "runtime_character_cards": [],
            "scene_writing_pack": {
                "schema_version": "scene-writing-pack/1.0",
                "digest": "sha256:test-scene-pack",
                "scene_id": "scene-test",
                "mode_key": "bond_short",
                "has_sensei": False,
            },
        }
        args = (scene_context, *args[1:])

    with pytest.raises(DomainError) as captured:
        getattr(provider, method_name)(*args)

    error = captured.value
    assert error.code == "writing_provider_failed"
    assert error.status == 502
    assert error.details["operation"] == operation
    assert "network unavailable" in error.details["reason"]
