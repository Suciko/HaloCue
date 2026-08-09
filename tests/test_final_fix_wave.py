# -*- coding: utf-8 -*-
"""Regression tests added for the final custom-assets review fix wave."""

import contextlib
import hashlib
import json
import multiprocessing
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

import pytest
from PIL import Image

import aa_project_assets
from aa_project_assets import AAProjectTarget, resolve_project_target
from aa_registry import AssetRegistrationError, load_manifest, register_background, register_character, register_sound, write_manifest_atomic
from asset_import import AssetImportRequestError, register_asset_request
from asset_models import AssetCandidate, ValidationResult
from asset_validation import validate_background, validate_spine, validate_sound
import script2aap
from verify import verify_project_assets
import webui


def _make_spine(root: Path, stem: str = "kai") -> Path:
    root.mkdir(parents=True)
    (root / f"{stem}.skel").write_bytes(b"synthetic spine 4.2.33")
    (root / f"{stem}.atlas").write_text(
        f"{stem}.png\nsize:8,8\n00_default\nbounds:0,0,1,1\n",
        encoding="utf-8",
    )
    Image.new("RGBA", (8, 8), "white").save(root / f"{stem}.png")
    Image.new("RGBA", (4, 4), "white").save(root / f"{stem}-avatar.png")
    return root


def _make_wav(path: Path) -> None:
    import wave

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(22050)
        output.writeframes(b"\0\0" * 2205)


def _generator_inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    data = tmp_path / "data"
    (data / "projects").mkdir(parents=True)
    script = tmp_path / "story.txt"
    script.write_text("", encoding="utf-8")
    cast = tmp_path / "cast.json"
    cast.write_text(json.dumps({"cast": {}}), encoding="utf-8")
    index = tmp_path / "index.json"
    index.write_text(
        json.dumps({
            "bg": {}, "sounds": [], "characters": [],
            "enums": {"emoticon": {}, "action": {}},
        }),
        encoding="utf-8",
    )
    return data, script, cast, index


def _generator_args(data: Path, script: Path, cast: Path, index: Path, *extra: str) -> list[str]:
    return [
        str(script), "--aa-data", str(data), "--cast", str(cast), "--index", str(index),
        "-o", "Demo", *extra,
    ]


def test_non_install_output_root_preserves_relative_custom_asset_resolution(
    tmp_path, monkeypatch
):
    story_root = tmp_path / "story-root"
    tool_root = story_root / "tools" / "aa"
    tool_root.mkdir(parents=True)
    _make_spine(story_root / "custom" / "kai")
    data = tmp_path / "aa-data"
    (data / "projects").mkdir(parents=True)
    script = story_root / "story.txt"
    script.write_text("Kai: hello\n", encoding="utf-8")
    cast = story_root / "cast.json"
    cast.write_text(
        json.dumps(
            {
                "cast": {
                    "Kai": {
                        "id": "custom-kai",
                        "name": "Kai",
                        "portrait": True,
                        "custom": {"src": "custom/kai", "asset": "kai"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    index = story_root / "index.json"
    index.write_text(
        json.dumps(
            {
                "bg": {},
                "sounds": [],
                "characters": [],
                "enums": {"emoticon": {}, "action": {}},
            }
        ),
        encoding="utf-8",
    )
    output_root = tmp_path / "state" / "out"
    monkeypatch.setattr(script2aap, "HERE", str(tool_root))

    script2aap.main(
        _generator_args(
            data,
            script,
            cast,
            index,
            "--output-root",
            str(output_root),
        )
    )

    assert (output_root / "Demo.aap").is_file()
    manifest = load_manifest(output_root / "Demo")
    assert manifest["CharacterOverrides"][0]["Identifier"] == "custom-kai"
    assert script2aap.HERE == str(tool_root)
    assert not (tool_root / "out").exists()


def _generate_face99_project(tmp_path: Path, *, source_class: str):
    data = tmp_path / "data"
    (data / "projects").mkdir(parents=True)
    spine = _make_spine(tmp_path / "spine")
    signature = hashlib.sha256((spine / "kai.skel").read_bytes()).hexdigest()
    script = tmp_path / "story.txt"
    script.write_text("Kai(99): hello\n", encoding="utf-8")
    cast = tmp_path / "cast.json"
    cast.write_text(
        json.dumps({"cast": {"Kai": {
            "id": "1516544", "name": "Kai", "club": "", "portrait": True,
            "custom": {"src": str(spine), "asset": "kai"},
        }}}),
        encoding="utf-8",
    )
    index_payload = {
        "bg": {}, "sounds": [], "characters": [],
        "enums": {"emoticon": {}, "action": {}},
        "face_capabilities": {"1516544": [{
            "spine_signature": signature, "outfit_key": "kai", "spine": "",
            "faces": [{
                "id": "99", "raw": "99", "label": "", "cn": "",
                "sources": [source_class], "observed_count": 1,
                "verified": source_class == "aa_verified",
            }],
        }]},
    }
    index = tmp_path / "index.json"
    index.write_text(json.dumps(index_payload), encoding="utf-8")
    script2aap.main(
        _generator_args(data, script, cast, index, "--install"),
        running_probe=lambda: False,
    )
    return index_payload, data / "projects" / "Demo.aap", data / "projects" / "Demo"


def _custom_install_inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    """Create a complete synthetic custom-cast install without AA data."""
    data = tmp_path / "data"
    (data / "projects").mkdir(parents=True)
    spine = _make_spine(tmp_path / "spine")
    script = tmp_path / "story.txt"
    script.write_text("Kai: hello\n", encoding="utf-8")
    cast = tmp_path / "cast.json"
    cast.write_text(
        json.dumps({"cast": {"Kai": {
            "id": "1516544", "name": "Kai", "club": "Test Club", "portrait": True,
            "custom": {"src": str(spine), "asset": "kai"},
        }}}),
        encoding="utf-8",
    )
    index = tmp_path / "index.json"
    index.write_text(
        json.dumps({"bg": {}, "sounds": [], "characters": [], "enums": {"emoticon": {}, "action": {}}}),
        encoding="utf-8",
    )
    return data, script, cast, index, spine


def _hold_pair_lock(project_dir, save_dir, project_name, ready, release):
    target = AAProjectTarget(Path(project_dir), Path(save_dir), project_name)
    with aa_project_assets.project_target_lock(target):
        ready.set()
        release.wait(8)


@contextlib.contextmanager
def _web_server(tmp_path, monkeypatch):
    monkeypatch.setitem(webui.CFG, "aa_data", str(tmp_path / "data"))
    webui.JOB.update(running=False, log=[], done=False, ok=False)
    server = ThreadingHTTPServer(("127.0.0.1", 0), webui.H)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
        webui.JOB.update(running=False, log=[], done=False, ok=False)


def _post_json(base, path, payload):
    request = Request(
        base + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request) as response:
            return response.status, json.loads(response.read())
    except Exception as exc:
        with exc as response:
            return response.status, json.loads(response.read())


@pytest.mark.parametrize(
    "unsafe",
    ["", ".", "..", "../escape", r"..\escape", r"C:\\outside", r"\\\\server\\share", "NUL", "COM1.txt", "bad\x01name"],
)
def test_windows_path_component_validator_rejects_unsafe_names(unsafe):
    """Removing the shared validator would re-open a target-directory escape."""
    with pytest.raises(ValueError):
        aa_project_assets.validate_windows_path_component(unsafe, label="test")


def test_windows_path_component_validator_keeps_legal_chinese_spaces_hyphens_and_ids():
    assert aa_project_assets.validate_windows_path_component(
        "蔚蓝 档案-92707271", label="test"
    ) == "蔚蓝 档案-92707271"


def test_spine_validation_rejects_unsafe_identifier_before_registration(tmp_path):
    """Dropping identifier validation would let a character escape characters/<id>."""
    result = validate_spine(_make_spine(tmp_path / "source"), identifier=r"..\escape")

    assert not result.ok
    assert "unsafe_path_component" in {issue.code for issue in result.issues}


def test_direct_character_registration_rejects_unsafe_candidate_identifier_before_creating_paths(tmp_path):
    """The registry must still protect itself if an upstream validator is bypassed."""
    source = _make_spine(tmp_path / "source")
    files = {
        "skel": str(source / "kai.skel"),
        "atlas": str(source / "kai.atlas"),
        "texture": str(source / "kai.png"),
        "avatar": str(source / "kai-avatar.png"),
    }
    result = ValidationResult(
        AssetCandidate(
            kind="character",
            source_path=source,
            stem="kai",
            aa_key=r"..\escape",
            sha256="synthetic",
            metadata={"files": files},
        )
    )
    target = tmp_path / "data" / "projects" / "Legal Project"

    with pytest.raises(AssetRegistrationError, match="path component"):
        register_character(result, target, display_name="Kai")

    assert not target.exists()
    assert not (tmp_path / "data" / "projects" / "escape").exists()


def test_direct_registry_target_rejects_dot_component_before_creating_any_target(tmp_path):
    """Resolving a legacy directory before validation would silently turn ../escape into a write target."""
    source = tmp_path / "night.png"
    Image.new("RGB", (8, 8), "navy").save(source)
    unsafe_target = tmp_path / "data" / "projects" / ".." / "escape"

    with pytest.raises(AssetRegistrationError, match="safe Windows"):
        register_background(validate_background(source), unsafe_target)

    assert not (tmp_path / "data" / "escape").exists()


def test_asset_import_maps_unsafe_project_target_to_request_error_before_writes(tmp_path):
    """Leaking a raw ValueError from target resolution would turn malformed input into an HTTP 500."""
    source = tmp_path / "night.png"
    Image.new("RGB", (8, 8), "navy").save(source)

    with pytest.raises(AssetImportRequestError, match="Windows"):
        register_asset_request(
            {
                "kind": "background",
                "source": str(source),
                "project_dir": str(tmp_path / "data" / "projects" / "CON"),
            },
            saves_root=tmp_path / "data" / "saves",
        )

    assert not (tmp_path / "data" / "projects" / "CON").exists()


def test_web_build_rejects_unsafe_project_name_before_starting_worker(tmp_path, monkeypatch):
    """Removing web build validation would admit a path-shaped project name."""
    with _web_server(tmp_path, monkeypatch) as base:
        status, payload = _post_json(base, "/api/build", {"project": r"..\escape"})

    assert status == 400
    assert payload["ok"] is False
    assert not (tmp_path / "data" / "escape").exists()


def test_cli_install_rejects_unsafe_project_name_before_creating_output(tmp_path, monkeypatch):
    """Removing CLI validation would write an install outside data/projects."""
    data = tmp_path / "data"
    (data / "projects").mkdir(parents=True)
    script = tmp_path / "story.txt"
    script.write_text("", encoding="utf-8")
    cast = tmp_path / "cast.json"
    cast.write_text(json.dumps({"cast": {}}), encoding="utf-8")
    index = tmp_path / "index.json"
    index.write_text(
        json.dumps({
            "bg": {}, "sounds": [], "characters": [],
            "enums": {"emoticon": {}, "action": {}},
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "script2aap.py", str(script), "--install", "--aa-data", str(data),
            "--cast", str(cast), "--index", str(index), "-o", r"..\escape",
        ],
    )

    with pytest.raises(ValueError, match="project name"):
        script2aap.main()

    assert not (data / "escape").exists()


def test_registration_waits_for_project_pair_lock_before_running_guard(tmp_path):
    """A registration must not run its AA guard or manifest work outside the pair lock."""
    target = resolve_project_target(tmp_path / "data" / "projects" / "Demo")
    source = tmp_path / "night.png"
    Image.new("RGB", (8, 8), "navy").save(source)
    probe_called = threading.Event()
    finished = threading.Event()

    def register():
        register_background(
            validate_background(source),
            target,
            running_probe=lambda: probe_called.set() or False,
        )
        finished.set()

    with aa_project_assets.project_target_lock(target):
        worker = threading.Thread(target=register)
        worker.start()
        assert not probe_called.wait(0.25)
        assert not finished.is_set()
    worker.join(3)

    assert probe_called.is_set()
    assert finished.is_set()


def test_project_pair_lock_is_held_across_processes(tmp_path):
    """Replacing the file lock with a process-local mutex would fail this admission test."""
    target = resolve_project_target(tmp_path / "data" / "projects" / "Demo")
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    process = context.Process(
        target=_hold_pair_lock,
        args=(str(target.project_dir), str(target.save_dir), target.project_name, ready, release),
    )
    process.start()
    entered = threading.Event()
    try:
        assert ready.wait(5)

        def acquire_in_parent():
            with aa_project_assets.project_target_lock(target):
                entered.set()

        worker = threading.Thread(target=acquire_in_parent)
        worker.start()
        assert not entered.wait(0.25)
        release.set()
        worker.join(5)
        assert entered.is_set()
    finally:
        release.set()
        process.join(5)
        if process.is_alive():
            process.terminate()
            process.join(5)


def test_concurrent_different_asset_registration_keeps_both_mirrors_complete(tmp_path, monkeypatch):
    """A stale manifest read must not cause one concurrent registration to be lost."""
    target = resolve_project_target(tmp_path / "data" / "projects" / "Demo")
    image = tmp_path / "night.png"
    sound = tmp_path / "click.wav"
    Image.new("RGB", (8, 8), "navy").save(image)
    _make_wav(sound)
    barrier = threading.Barrier(2)
    copy_count = 0
    copy_count_lock = threading.Lock()
    real_copy2 = __import__("aa_registry").shutil.copy2

    def synchronized_copy(source, destination, *args, **kwargs):
        nonlocal copy_count
        with copy_count_lock:
            copy_count += 1
            wait_for_peer = copy_count <= 2
        if wait_for_peer:
            try:
                barrier.wait(timeout=0.25)
            except threading.BrokenBarrierError:
                pass
        return real_copy2(source, destination, *args, **kwargs)

    monkeypatch.setattr(__import__("aa_registry").shutil, "copy2", synchronized_copy)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(register_background, validate_background(image), target, running_probe=lambda: False)
        second = pool.submit(register_sound, validate_sound(sound), target, running_probe=lambda: False)
        first.result(timeout=5)
        second.result(timeout=5)

    for directory in (target.project_dir, target.save_dir):
        manifest = load_manifest(directory)
        assert manifest["BgOverrides"] == [r"bgs\night.png"]
        assert manifest["SoundOverrides"] == [r"sounds\click.wav"]


def test_same_project_build_requests_are_atomically_admitted_once(tmp_path, monkeypatch):
    """Moving the reservation into the worker would let two HTTP requests both win."""
    entered = threading.Event()
    release = threading.Event()

    def blocking_build(_payload):
        entered.set()
        release.wait(5)

    monkeypatch.setattr(webui, "run_build", blocking_build)
    try:
        with _web_server(tmp_path, monkeypatch) as base:
            with ThreadPoolExecutor(max_workers=2) as pool:
                requests = [
                    pool.submit(_post_json, base, "/api/build", {"project": "Demo", "script": "ignored", "mapping": {}})
                    for _ in range(2)
                ]
                results = [request.result(timeout=5) for request in requests]
            assert entered.wait(2)
            assert sorted(status for status, _ in results) == [200, 409]
    finally:
        release.set()


def test_cli_install_running_guard_is_injected_before_any_project_write(tmp_path):
    """Removing the CLI-local guard would create an AAP or manifest while AA is open."""
    data, script, cast, index = _generator_inputs(tmp_path)

    with pytest.raises(AssetRegistrationError, match="aa_running"):
        script2aap.main(
            _generator_args(data, script, cast, index, "--install"),
            running_probe=lambda: True,
        )

    assert not (data / "projects" / "Demo").exists()
    assert not (data / "projects" / "Demo.aap").exists()
    assert not (data / "saves" / "Demo").exists()


def test_cli_pure_output_remains_allowed_when_injected_probe_reports_running(tmp_path, monkeypatch):
    """Applying the guard to generation-only output would regress the documented workflow."""
    data, script, cast, index = _generator_inputs(tmp_path)
    tool_root = tmp_path / "tool"
    tool_root.mkdir()
    monkeypatch.setattr(script2aap, "HERE", str(tool_root))

    script2aap.main(
        _generator_args(data, script, cast, index),
        running_probe=lambda: True,
    )

    assert (tool_root / "out" / "Demo.aap").is_file()
    assert json.loads((tool_root / "out" / "Demo" / "aa_resources.json").read_text(encoding="utf-8")) == json.loads(index.read_text(encoding="utf-8"))
    assert not (data / "projects" / "Demo").exists()
    assert not (data / "saves" / "Demo").exists()


def test_cli_install_custom_cast_mirrors_character_metadata_files_and_verifies(tmp_path):
    """Install must make a complete project/save pair, not a project-only custom cast."""
    data, script, cast, index, _spine = _custom_install_inputs(tmp_path)

    script2aap.main(
        _generator_args(data, script, cast, index, "--install"),
        running_probe=lambda: False,
    )

    project = data / "projects" / "Demo"
    save = data / "saves" / "Demo"
    aap = data / "projects" / "Demo.aap"
    project_manifest = load_manifest(project)
    save_manifest = load_manifest(save)
    assert project_manifest["CharacterOverrides"] == save_manifest["CharacterOverrides"]
    for directory in (project, save):
        for filename in ("kai.skel", "kai.atlas", "kai.png", "kai-avatar.png"):
            assert (directory / "characters" / "1516544" / filename).is_file()
    report = verify_project_assets(aap, project, save_dir=save)
    assert not report.errors
    assert not report.warnings


def test_cli_install_preserves_and_reconciles_existing_voice_overrides_without_new_audio(tmp_path):
    """A no-voice rerun must retain both mirrors' legacy registrations and payloads."""
    data, script, cast, index, _spine = _custom_install_inputs(tmp_path)
    target = resolve_project_target(data / "projects" / "Demo")
    project_manifest = load_manifest(target.project_dir)
    save_manifest = load_manifest(target.save_dir)
    project_manifest["VoiceOverrides"] = ["voices/legacy.wav"]
    save_manifest["VoiceOverrides"] = ["voices/legacy.wav", "voices/save-only.wav"]
    write_manifest_atomic(target.project_dir, project_manifest)
    write_manifest_atomic(target.save_dir, save_manifest)
    _make_wav(target.project_dir / "voices" / "legacy.wav")
    _make_wav(target.save_dir / "voices" / "legacy.wav")
    _make_wav(target.save_dir / "voices" / "save-only.wav")

    script2aap.main(
        _generator_args(data, script, cast, index, "--install"),
        running_probe=lambda: False,
    )

    expected = ["voices/legacy.wav", "voices/save-only.wav"]
    for directory in (target.project_dir, target.save_dir):
        assert load_manifest(directory)["VoiceOverrides"] == expected
        assert (directory / "voices" / "legacy.wav").is_file()
        assert (directory / "voices" / "save-only.wav").is_file()


def test_cli_install_voices_are_mirrored_verifiable_and_idempotent(tmp_path):
    """--voices appends to legacy audio, mirrors it, and remains idempotent on rerun."""
    data, script, cast, index, _spine = _custom_install_inputs(tmp_path)
    target = resolve_project_target(data / "projects" / "Demo")
    for directory in (target.project_dir, target.save_dir):
        manifest = load_manifest(directory)
        manifest["VoiceOverrides"] = ["voices/legacy.wav"]
        write_manifest_atomic(directory, manifest)
        _make_wav(directory / "voices" / "legacy.wav")
    voices = tmp_path / "tts"
    voices.mkdir()
    guid = script2aap.voice_guid("Demo", 0)
    _make_wav(voices / f"{guid}.wav")
    args = _generator_args(data, script, cast, index, "--install", "--voices", str(voices))

    script2aap.main(args, running_probe=lambda: False)
    script2aap.main(args, running_probe=lambda: False)

    expected = ["voices/legacy.wav", f"voices/{guid}.wav"]
    for directory in (target.project_dir, target.save_dir):
        assert load_manifest(directory)["VoiceOverrides"] == expected
    project_voice = target.project_dir / "voices" / f"{guid}.wav"
    save_voice = target.save_dir / "voices" / f"{guid}.wav"
    assert project_voice.read_bytes() == save_voice.read_bytes()
    report = verify_project_assets(data / "projects" / "Demo.aap", target.project_dir, save_dir=target.save_dir)
    assert report.ok


@pytest.mark.parametrize(
    "unsafe",
    [
        r"voices\C:\evil.wav",
        r"\\server\share\evil.wav",
        r"C:\evil.wav",
        r"\absolute\evil.wav",
        r"voices\..\evil.wav",
        r"voices\CON.wav",
        r"voices\NUL",
        r"voices\safe.wav:evil",
        "voices\\bad\x01name.wav",
    ],
)
def test_unsafe_voice_overrides_are_rejected_before_creating_any_target(tmp_path, unsafe):
    """Voice mirror paths use the same Windows-safe component rules as all assets."""
    project = tmp_path / "project"
    save = tmp_path / "save"

    with pytest.raises(AssetRegistrationError):
        script2aap._reconcile_voice_files(project, save, [unsafe])

    assert not project.exists()
    assert not save.exists()


def test_voice_override_keeps_legal_chinese_and_spaces_within_both_roots(tmp_path):
    project = tmp_path / "project"
    save = tmp_path / "save"
    relative = r"voices\蔚蓝 档案.wav"
    source = project / "voices" / "蔚蓝 档案.wav"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"voice")

    script2aap._reconcile_voice_files(project, save, [relative])

    assert source.is_file()
    assert (save / "voices" / "蔚蓝 档案.wav").read_bytes() == b"voice"


def test_cli_install_serializes_with_asset_registration_on_the_same_target(tmp_path, monkeypatch):
    """A registration started during install must wait for the full install transaction."""
    data, script, cast, index, _spine = _custom_install_inputs(tmp_path)
    target = resolve_project_target(data / "projects" / "Demo")
    background = tmp_path / "night.png"
    Image.new("RGB", (8, 8), "navy").save(background)
    entered = threading.Event()
    release = threading.Event()
    install_done = threading.Event()
    registration_done = threading.Event()
    errors = []
    real_merge = script2aap.merge_project_registered_assets

    def pause_after_manifest_read(index_payload, project_dir):
        merged = real_merge(index_payload, project_dir)
        entered.set()
        assert release.wait(5)
        return merged

    monkeypatch.setattr(script2aap, "merge_project_registered_assets", pause_after_manifest_read)

    def install():
        try:
            script2aap.main(
                _generator_args(data, script, cast, index, "--install"),
                running_probe=lambda: False,
            )
        except BaseException as exc:  # surfaced below with the worker's traceback context
            errors.append(exc)
        finally:
            install_done.set()

    def register():
        try:
            register_background(validate_background(background), target, running_probe=lambda: False)
        except BaseException as exc:
            errors.append(exc)
        finally:
            registration_done.set()

    install_worker = threading.Thread(target=install)
    install_worker.start()
    assert entered.wait(3)
    registration_worker = threading.Thread(target=register)
    registration_worker.start()
    assert not registration_done.wait(0.25)
    release.set()
    install_worker.join(5)
    registration_worker.join(5)

    assert install_done.is_set()
    assert registration_done.is_set()
    assert errors == []
    project_manifest = load_manifest(target.project_dir)
    save_manifest = load_manifest(target.save_dir)
    assert project_manifest == save_manifest
    assert project_manifest["BgOverrides"] == [r"bgs\night.png"]
    assert (target.project_dir / "bgs" / "night.png").is_file()
    assert (target.save_dir / "bgs" / "night.png").is_file()


def test_cli_install_failure_restores_both_manifests_and_keeps_preexisting_assets(tmp_path, monkeypatch):
    """One failed install must leave neither mirror nor pre-existing assets half-updated."""
    data, script, cast, index, _spine = _custom_install_inputs(tmp_path)
    target = resolve_project_target(data / "projects" / "Demo")
    background = tmp_path / "existing.png"
    Image.new("RGB", (8, 8), "teal").save(background)
    register_background(validate_background(background), target, running_probe=lambda: False)
    before = {
        path: path.read_bytes()
        for path in (target.project_dir / "manifest.json", target.save_dir / "manifest.json")
    }

    def fail_sidecar(*_args, **_kwargs):
        raise OSError("injected sidecar failure")

    monkeypatch.setattr(script2aap, "write_project_resource_index", fail_sidecar)
    with pytest.raises(OSError, match="injected sidecar failure"):
        script2aap.main(
            _generator_args(data, script, cast, index, "--install"),
            running_probe=lambda: False,
        )

    assert {path: path.read_bytes() for path in before} == before
    for directory in (target.project_dir, target.save_dir):
        assert (directory / "bgs" / "existing.png").is_file()
        assert not (directory / "characters" / "1516544").exists()
    assert not (data / "projects" / "Demo.aap").exists()


def test_process_probe_failure_fails_closed_but_confirmed_closed_is_allowed(monkeypatch):
    """Treating a failed tasklist invocation as False would permit an unknown write state."""
    class FailedProbe:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(aa_project_assets.subprocess, "run", lambda *args, **kwargs: FailedProbe())

    with pytest.raises(AssetRegistrationError, match="aa_probe_failed"):
        aa_project_assets.assert_aa_closed()

    aa_project_assets.assert_aa_closed(running_probe=lambda: False)


def test_injected_copy_failure_leaves_no_temporary_or_target_asset_remnant(tmp_path, monkeypatch):
    """Appending to rollback only after copy2 returns leaves a half-written target behind."""
    target = resolve_project_target(tmp_path / "data" / "projects" / "Demo")
    source = tmp_path / "night.png"
    Image.new("RGB", (8, 8), "navy").save(source)

    def partial_copy(_source, destination, *args, **kwargs):
        Path(destination).write_bytes(b"partial")
        raise OSError("injected copy failure")

    monkeypatch.setattr(__import__("aa_registry").shutil, "copy2", partial_copy)

    with pytest.raises(OSError, match="injected copy failure"):
        register_background(validate_background(source), target, running_probe=lambda: False)

    for directory in (target.project_dir, target.save_dir):
        assert not (directory / "bgs" / "night.png").exists()
        assert not (directory / "manifest.json").exists()
        assert not list((directory / "bgs").glob("*.tmp"))


def test_new_asset_copy_uses_same_directory_temporary_then_atomic_replace(tmp_path, monkeypatch):
    """Replacing direct copy2(destination) with a non-atomic move would fail this transaction boundary."""
    target = resolve_project_target(tmp_path / "data" / "projects" / "Demo")
    source = tmp_path / "night.png"
    Image.new("RGB", (8, 8), "navy").save(source)
    real_replace = __import__("aa_registry").os.replace
    asset_replaces = []

    def observed_replace(source_path, destination_path):
        if Path(destination_path).name == "night.png":
            asset_replaces.append((Path(source_path), Path(destination_path)))
        return real_replace(source_path, destination_path)

    monkeypatch.setattr(__import__("aa_registry").os, "replace", observed_replace)

    register_background(validate_background(source), target, running_probe=lambda: False)

    assert len(asset_replaces) == 2
    assert all(source_path.parent == destination_path.parent for source_path, destination_path in asset_replaces)
    assert all(source_path != destination_path for source_path, destination_path in asset_replaces)


def test_generated_project_sidecar_carries_observed_face99_to_verifier(tmp_path):
    """Omitting the build index sidecar makes a legal generated face 99 unverifiable."""
    index, aap, project = _generate_face99_project(tmp_path, source_class="aap_observed")

    payload = json.loads(aap.read_text(encoding="utf-8"))
    assert "face_capabilities" not in payload
    assert json.loads((project / "aa_resources.json").read_text(encoding="utf-8")) == index
    assert verify_project_assets(aap, project).ok


def test_generated_project_sidecar_does_not_authorize_atlas_only_face99(tmp_path):
    """A sidecar must carry source classes, not convert atlas candidates into approval."""
    _index, aap, project = _generate_face99_project(tmp_path, source_class="atlas_candidate")

    report = verify_project_assets(aap, project)

    assert any("faceId 99" in error for error in report.errors)
