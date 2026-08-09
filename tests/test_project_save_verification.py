import hashlib
import json
import shutil
from pathlib import Path

from verify import verify_project_assets


def _write(path: Path, content: bytes = b"asset"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _manifest(*, sound="sounds/click.wav", bg="bgs/room.png", voice="voices/line.wav", character=None):
    return {
        "BgOverrides": [bg],
        "SoundOverrides": [sound],
        "VoiceOverrides": [voice],
        "CharacterOverrides": [character or {
            "Identifier": "1516544", "Name": "Kei", "Nickname": "",
            "SpinePortraitPath": "characters/1516544/winter",
            "SmallPortraitPath": "characters/1516544/winter-avatar.png",
        }],
    }


def _write_project(root: Path, manifest=None):
    manifest = manifest or _manifest()
    (root / "manifest.json").parent.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    _write(root / "bgs/room.png", b"background")
    _write(root / "sounds/click.wav", b"sound")
    _write(root / "voices/line.wav", b"voice")
    _write(root / "characters/1516544/winter.skel", b"\0spine\04.2.33\0")
    _write(root / "characters/1516544/winter.atlas", b"winter.png\nsize:1,1\n")
    _write(root / "characters/1516544/winter.png", b"texture")
    _write(root / "characters/1516544/winter-avatar.png", b"avatar")


def _aap(path: Path, *, face_id=None, capabilities=None):
    scripts = [] if face_id is None else [{"characters": {"$values": [{
        "name": "1516544", "faceId": face_id,
    }]}}]
    payload = {"nodes": {"$values": [{"Scripts": {"$values": scripts}}]}}
    if capabilities is not None:
        payload["face_capabilities"] = capabilities
    path.write_text(json.dumps(payload), encoding="utf-8")


def _mirrored(tmp_path):
    project, save, aap = tmp_path / "project", tmp_path / "save", tmp_path / "scene.aap"
    _write_project(project)
    shutil.copytree(project, save)
    _aap(aap)
    return project, save, aap


def test_save_manifest_missing_registered_asset_is_reported(tmp_path):
    project, save, aap = _mirrored(tmp_path)
    manifest = json.loads((save / "manifest.json").read_text(encoding="utf-8"))
    manifest["SoundOverrides"] = []
    (save / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    report = verify_project_assets(aap, project, save_dir=save)

    assert any("save manifest" in error and "sounds/click.wav" in error for error in report.errors)


def test_speaking_only_character_does_not_require_spine_face_evidence(tmp_path):
    project = tmp_path / "project"
    _write_project(project, _manifest(character={
        "Identifier": "speaker", "Name": "Voice only", "Nickname": "",
        "SpinePortraitPath": None,
    }))
    aap = tmp_path / "scene.aap"
    aap.write_text(json.dumps({"nodes": {"$values": [{"Scripts": {"$values": [{
        "characters": {"$values": [{"name": "speaker", "faceId": "00"}]},
    }]}}]}}), encoding="utf-8")

    report = verify_project_assets(aap, project)

    assert not any("speaker faceId" in error for error in report.errors)


def test_save_only_background_sound_and_character_registrations_are_reported(tmp_path):
    project, save, aap = _mirrored(tmp_path)
    manifest = json.loads((save / "manifest.json").read_text(encoding="utf-8"))
    manifest["BgOverrides"].append("bgs/save-only.png")
    manifest["SoundOverrides"].append("sounds/save-only.wav")
    manifest["CharacterOverrides"].append({
        "Identifier": "1516545", "Name": "Save only", "Nickname": "",
        "SpinePortraitPath": "characters/1516545/summer",
        "SmallPortraitPath": "characters/1516545/summer-avatar.png",
    })
    (save / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    _write(save / "bgs/save-only.png", b"save-only bg")
    _write(save / "sounds/save-only.wav", b"save-only sound")
    for suffix in (".skel", ".atlas", ".png", "-avatar.png"):
        _write(save / f"characters/1516545/summer{suffix}", b"save-only character")

    report = verify_project_assets(aap, project, save_dir=save)

    assert any("save-only" in error and "BgOverrides" in error for error in report.errors)
    assert any("save-only" in error and "SoundOverrides" in error for error in report.errors)
    assert any("save-only" in error and "1516545" in error for error in report.errors)


def test_save_background_and_sound_byte_drift_are_reported(tmp_path):
    project, save, aap = _mirrored(tmp_path)
    _write(save / "bgs/room.png", b"changed background")
    _write(save / "sounds/click.wav", b"changed sound")

    report = verify_project_assets(aap, project, save_dir=save)

    assert sum("SHA-256" in error for error in report.errors) == 2


def test_save_voice_manifest_missing_file_and_byte_drift_are_reported(tmp_path):
    """VoiceOverrides are mirror-owned assets, not an unchecked metadata list."""
    project, save, aap = _mirrored(tmp_path)
    (save / "voices/line.wav").unlink()

    missing = verify_project_assets(aap, project, save_dir=save)

    assert any("line.wav" in error and "missing" in error for error in missing.errors)
    _write(save / "voices/line.wav", b"changed voice")
    changed = verify_project_assets(aap, project, save_dir=save)
    assert any("VoiceOverrides" in error and "SHA-256" in error for error in changed.errors)
    manifest = json.loads((save / "manifest.json").read_text(encoding="utf-8"))
    manifest["VoiceOverrides"] = []
    (save / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    missing_registration = verify_project_assets(aap, project, save_dir=save)
    assert any("VoiceOverrides" in error and "save manifest missing" in error for error in missing_registration.errors)


def test_save_character_metadata_and_avatar_drift_are_reported(tmp_path):
    project, save, aap = _mirrored(tmp_path)
    manifest = json.loads((save / "manifest.json").read_text(encoding="utf-8"))
    manifest["CharacterOverrides"][0]["Name"] = "Different Kei"
    (save / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (save / "characters/1516544/winter-avatar.png").unlink()

    report = verify_project_assets(aap, project, save_dir=save)

    assert any("character metadata" in error for error in report.errors)
    assert any("winter-avatar.png" in error and "missing" in error for error in report.errors)


def test_slash_variants_are_duplicate_registrations_without_mutation(tmp_path):
    project, save, aap = _mirrored(tmp_path)
    manifest_path = project / "manifest.json"
    before = manifest_path.read_bytes()
    manifest = json.loads(before)
    manifest["BgOverrides"].append("bgs\\room.png")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    expected = manifest_path.read_bytes()

    report = verify_project_assets(aap, project, save_dir=save)

    assert any("duplicate" in error and "bgs" in error for error in report.errors)
    assert manifest_path.read_bytes() == expected


def test_project_only_reports_slash_equivalent_manifest_duplicate(tmp_path):
    project, _, aap = _mirrored(tmp_path)
    manifest_path = project / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["BgOverrides"].append("bgs\\room.png")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = verify_project_assets(aap, project)

    assert any("manifest.BgOverrides duplicate registration" in error for error in report.errors)


def test_custom_face_requires_evidence_but_accepts_observed_99(tmp_path):
    project, save, aap = _mirrored(tmp_path)
    signature = hashlib.sha256(
        (project / "characters/1516544/winter.skel").read_bytes()
    ).hexdigest()
    _aap(aap, face_id="99", capabilities={"1516544": [{
        "spine_signature": signature, "outfit_key": "winter", "faces": [{
            "id": "99", "sources": ["aap_observed"], "verified": False,
        }],
    }]})

    observed = verify_project_assets(aap, project, save_dir=save)
    _aap(aap, face_id="98", capabilities={"1516544": [{
        "spine_signature": signature, "outfit_key": "winter", "faces": [{
            "id": "99", "sources": ["aap_observed"], "verified": False,
        }],
    }]})
    unsupported = verify_project_assets(aap, project, save_dir=save)

    assert observed.ok
    assert any("faceId 98" in error for error in unsupported.errors)


def test_face_99_needs_observed_or_verified_source_not_boolean(tmp_path):
    project, _, aap = _mirrored(tmp_path)
    _aap(aap, face_id="99", capabilities={"1516544": [{
        "spine_signature": "", "outfit_key": "", "faces": [{
            "id": "99", "sources": ["atlas_candidate"], "verified": True,
        }],
    }]})

    report = verify_project_assets(aap, project)

    assert any("faceId 99" in error for error in report.errors)


def test_selected_variant_does_not_fallback_to_identifier_observation(tmp_path):
    project, _, aap = _mirrored(tmp_path)
    _aap(aap, face_id="99", capabilities={"1516544": [{
        "spine_signature": "", "outfit_key": "", "faces": [{
            "id": "99", "sources": ["aap_observed"], "verified": False,
        }],
    }]})

    report = verify_project_assets(aap, project)

    assert any("faceId 99" in error for error in report.errors)
