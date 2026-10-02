from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from halocue_writing.errors import DomainError
from halocue_writing.model_settings import UserPreferencesStore


DEFAULTS = {
    "writing_tone": "bond_short",
    "char_warning_threshold": 35,
    "aa_pacing_wait_ms": 2500,
    "max_stage_characters": 4,
    "camera_switch_mode": "speaker_first",
    "editor_font_size": "medium",
}
INVALID_VALUES = (
    [
        (key, value)
        for key in DEFAULTS
        for value in [None, True, False, [], {}, "", "not-a-preference"]
    ]
    + [
        (key, value)
        for key, low, high in [
            ("char_warning_threshold", 15, 100),
            ("aa_pacing_wait_ms", 1000, 5000),
            ("max_stage_characters", 1, 5),
        ]
        for value in [low - 1, high + 1, float(low), str(low)]
    ]
    + [(key, 1) for key in ["writing_tone", "camera_switch_mode", "editor_font_size"]]
)


def test_missing_file_returns_fresh_defaults_without_creating_directory(tmp_path):
    store = UserPreferencesStore(tmp_path / "absent")
    loaded = store.load()
    assert loaded == DEFAULTS
    loaded["writing_tone"] = "changed"
    assert store.load() == DEFAULTS
    assert not store.path.parent.exists()


def test_valid_legacy_unknown_fields_are_not_echoed_or_persisted(tmp_path):
    store = UserPreferencesStore(tmp_path)
    store.path.write_text(json.dumps({**DEFAULTS, "legacy": "ignore me"}), encoding="utf-8")
    assert store.load() == DEFAULTS
    saved = store.save({"writing_tone": "main_battle", "legacy": {"nested": [True]}})
    assert saved == {**DEFAULTS, "writing_tone": "main_battle"}
    assert store.load() == saved
    assert json.loads(store.path.read_text(encoding="utf-8")) == saved
    assert store.save({"unknown": object()}) == saved


def test_partial_save_preserves_other_known_fields(tmp_path):
    store = UserPreferencesStore(tmp_path)
    store.save({"char_warning_threshold": 60, "editor_font_size": "large"})
    expected = {
        **DEFAULTS,
        "char_warning_threshold": 60,
        "editor_font_size": "large",
        "max_stage_characters": 2,
    }
    assert store.save({"max_stage_characters": 2}) == expected
    assert store.save({}) == expected
    assert UserPreferencesStore(tmp_path).load() == expected


@pytest.mark.parametrize(
    "key,value",
    [
        ("writing_tone", value)
        for value in ["bond_short", "main_battle", "long_comedy", "text_reading"]
    ]
    + [("editor_font_size", value) for value in ["small", "medium", "large"]]
    + [
        ("camera_switch_mode", "speaker_first"),
        ("char_warning_threshold", 15),
        ("char_warning_threshold", 100),
        ("aa_pacing_wait_ms", 1000),
        ("aa_pacing_wait_ms", 5000),
        ("aa_pacing_wait_ms", 1001),
        ("max_stage_characters", 1),
        ("max_stage_characters", 5),
    ],
)
def test_valid_enums_and_boundaries_roundtrip(tmp_path, key, value):
    store = UserPreferencesStore(tmp_path)
    assert store.save({key: value}) == {**DEFAULTS, key: value}
    assert store.load() == {**DEFAULTS, key: value}


@pytest.mark.parametrize("key,value", INVALID_VALUES)
def test_invalid_update_rejected_before_any_file_change(tmp_path, key, value):
    store = UserPreferencesStore(tmp_path)
    store.save({"char_warning_threshold": 55})
    original = store.path.read_bytes()
    with pytest.raises(DomainError) as exc:
        store.save({"editor_font_size": "large", key: value})
    assert exc.value.code == "invalid_user_preferences"
    assert exc.value.status == 400
    assert exc.value.details["field"] == key
    assert store.path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [store.path]


@pytest.mark.parametrize("key,value", INVALID_VALUES)
def test_invalid_saved_known_value_blocks_load_and_save_preserving_bytes(tmp_path, key, value):
    store = UserPreferencesStore(tmp_path)
    raw = json.dumps({key: value}, indent=4).encode()
    store.path.write_bytes(raw)
    for operation in [store.load, lambda: store.save({key: DEFAULTS[key]})]:
        with pytest.raises(DomainError) as exc:
            operation()
        assert exc.value.code == "invalid_user_preferences"
        assert exc.value.details["field"] == key
        assert store.path.read_bytes() == raw
    assert list(tmp_path.iterdir()) == [store.path]


@pytest.mark.parametrize("payload", [None, [], ["writing_tone"], "wrong", 5, True])
def test_nonobject_update_rejected_without_creating_directory(tmp_path, payload):
    store = UserPreferencesStore(tmp_path / "absent")
    with pytest.raises(DomainError) as exc:
        store.save(payload)
    assert exc.value.code == "invalid_user_preferences"
    assert not store.path.parent.exists()


def test_invalid_known_update_does_not_create_directory(tmp_path):
    store = UserPreferencesStore(tmp_path / "absent")
    with pytest.raises(DomainError):
        store.save({"writing_tone": "bad"})
    assert not store.path.parent.exists()


@pytest.mark.parametrize("raw", [b"{", b"", b"[]", b"null", b"42", b'"text"', b"true", b"\xff"])
def test_corrupt_saved_json_is_observable_and_preserved(tmp_path, raw):
    store = UserPreferencesStore(tmp_path)
    store.path.write_bytes(raw)
    for operation in [store.load, lambda: store.save({"max_stage_characters": 2})]:
        with pytest.raises(DomainError) as exc:
            operation()
        assert exc.value.code == "invalid_user_preferences"
        assert store.path.read_bytes() == raw
    assert list(tmp_path.iterdir()) == [store.path]


def test_empty_saved_object_uses_defaults(tmp_path):
    store = UserPreferencesStore(tmp_path)
    store.path.write_bytes(b"{}")
    assert store.load() == DEFAULTS


@pytest.mark.parametrize("existing", [True, False])
def test_atomic_replace_failure_preserves_original_and_cleans_temporary(
    tmp_path, monkeypatch, existing
):
    store = UserPreferencesStore(tmp_path)
    if existing:
        store.save({"max_stage_characters": 3})
    original = store.path.read_bytes() if existing else None
    replacements = []

    def fail_replace(source, target):
        source, target = Path(source), Path(target)
        assert target == store.path
        assert source.parent == store.path.parent and source != target
        assert json.loads(source.read_text(encoding="utf-8"))["max_stage_characters"] == 2
        replacements.append(source)
        raise OSError("synthetic replace failure")

    monkeypatch.setattr("halocue_writing.model_settings.os.replace", fail_replace)
    with pytest.raises(DomainError) as exc:
        store.save({"max_stage_characters": 2})
    assert exc.value.code == "user_preferences_save_failed"
    assert replacements
    assert (store.path.read_bytes() if store.path.exists() else None) == original
    assert list(tmp_path.iterdir()) == ([store.path] if existing else [])


def test_successful_save_uses_complete_atomic_replacement(tmp_path, monkeypatch):
    import os

    store = UserPreferencesStore(tmp_path)
    store.save({})
    original = store.path.read_bytes()
    real_replace = os.replace
    replacements = []

    def inspect_replace(source, target):
        assert store.path.read_bytes() == original
        assert json.loads(Path(source).read_text(encoding="utf-8")) == {
            **DEFAULTS,
            "editor_font_size": "small",
        }
        replacements.append(source)
        return real_replace(source, target)

    monkeypatch.setattr("halocue_writing.model_settings.os.replace", inspect_replace)
    assert store.save({"editor_font_size": "small"})["editor_font_size"] == "small"
    assert len(replacements) == 1
    assert list(tmp_path.iterdir()) == [store.path]


def test_concurrent_partial_saves_are_serialized_within_one_store(tmp_path, monkeypatch):
    store = UserPreferencesStore(tmp_path)
    store.save({})
    first_read, release_first, second_started, second_read = (threading.Event() for _ in range(4))
    real_read = Path.read_text

    def controlled_read(path, *args, **kwargs):
        result = real_read(path, *args, **kwargs)
        if path == store.path:
            if not first_read.is_set():
                first_read.set()
                assert release_first.wait(5), "first writer not released"
            else:
                second_read.set()
        return result

    monkeypatch.setattr(Path, "read_text", controlled_read)

    def second_save():
        second_started.set()
        return store.save({"max_stage_characters": 2})

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(store.save, {"char_warning_threshold": 44})
        try:
            assert first_read.wait(5)
            second = pool.submit(second_save)
            assert second_started.wait(5)
            interleaved = second_read.wait(0.2)
        finally:
            release_first.set()
        first.result(timeout=5)
        second.result(timeout=5)
    assert not interleaved, "read-modify-write must hold the store lock"
    assert store.load() == {**DEFAULTS, "char_warning_threshold": 44, "max_stage_characters": 2}


def test_nonfile_path_is_not_treated_as_missing_preferences(tmp_path):
    store = UserPreferencesStore(tmp_path)
    store.path.mkdir()
    with pytest.raises(DomainError) as exc:
        store.load()
    assert exc.value.code == "user_preferences_read_failed"
    with pytest.raises(DomainError) as exc:
        store.save({"editor_font_size": "large"})
    assert exc.value.code == "user_preferences_read_failed"
    assert store.path.is_dir()
    assert list(tmp_path.iterdir()) == [store.path]


def test_read_io_failure_is_observable_without_write(tmp_path, monkeypatch):
    store = UserPreferencesStore(tmp_path)
    store.save({})
    original = store.path.read_bytes()

    def fail_read(*args, **kwargs):
        raise PermissionError("synthetic read failure")

    monkeypatch.setattr(Path, "read_text", fail_read)
    for operation in [store.load, lambda: store.save({"editor_font_size": "large"})]:
        with pytest.raises(DomainError) as exc:
            operation()
        assert exc.value.code == "user_preferences_read_failed"
        assert store.path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [store.path]


def test_partial_temporary_write_failure_cleans_up_without_changing_original(tmp_path, monkeypatch):
    store = UserPreferencesStore(tmp_path)
    store.save({})
    original = store.path.read_bytes()

    def fail_write(path, *args, **kwargs):
        path.write_bytes(b"partial write")
        raise OSError("synthetic write failure")

    monkeypatch.setattr(Path, "write_text", fail_write)
    with pytest.raises(DomainError) as exc:
        store.save({"editor_font_size": "large"})
    assert exc.value.code == "user_preferences_save_failed"
    assert store.path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [store.path]


def test_directory_creation_failure_is_observable(tmp_path, monkeypatch):
    store = UserPreferencesStore(tmp_path / "absent")

    def fail_mkdir(*args, **kwargs):
        raise PermissionError("synthetic directory creation failure")

    monkeypatch.setattr(Path, "mkdir", fail_mkdir)
    with pytest.raises(DomainError) as exc:
        store.save({})
    assert exc.value.code == "user_preferences_save_failed"
    assert not store.path.parent.exists()
