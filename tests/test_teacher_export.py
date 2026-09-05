"""Synthetic compiler/build/install acceptance for managed teacher identities."""

import json
from pathlib import Path

import pytest

from aa_registry import load_manifest, write_manifest_atomic
from build_bundle import BuildBundleManager, calc_file_sha256
from draft_store import DraftStore
from install_manager import InstallManager
from script2aap import compile_script
from teacher_identity import TeacherIdentityError


TEACHER_ID = "hc-teacher-0123456789abcdef0123456789abcdef"


def _json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _inputs(tmp_path, *, name="sensei", organization="Schale"):
    teacher = {
        "kind": "voice",
        "role": "teacher",
        "id": TEACHER_ID,
        "name": name,
        "club": organization,
        "portrait": False,
        "narrator": False,
        "teacher_identity_schema": "teacher-identity/1.0",
        "teacher_preset_id": "custom",
    }
    cast = {
        "default_bg": "BG_Black",
        "camera": {"enabled": False},
        "cast": {"SourceTeacher": teacher},
        "alias": {"OriginalAlias": "SourceTeacher"},
        "teacher_identity": {
            "schema_version": "teacher-identity/1.0",
            "character_id": TEACHER_ID,
            "preset_id": "custom",
            "display_name": name,
            "organization": organization,
        },
    }
    resources = {
        "bg": {"BG_Black": 0},
        "sounds": [],
        "characters": [
            {
                "identifier": TEACHER_ID,
                "name": name,
                "club": organization,
                "role": "teacher",
                "source": "halocue_teacher",
                "portrait": False,
                "spine": "",
                "faces": [],
            }
        ],
        "enums": {"emoticon": {}, "action": {}, "appear": {}, "shape": {}},
    }
    script = tmp_path / "source.txt"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        "SourceTeacher: Keep this line.\nOriginalAlias: And this reply.\n", encoding="utf-8"
    )
    _json(tmp_path / "cast.json", cast)
    _json(tmp_path / "resources.json", resources)
    aa_data = tmp_path / "synthetic-aa"
    for part in ("projects", "saves", "overrides", "settings"):
        (aa_data / part).mkdir(parents=True, exist_ok=True)
    options = {
        "script": str(script),
        "out": "TeacherDemo",
        "cast": str(tmp_path / "cast.json"),
        "index": str(tmp_path / "resources.json"),
        "output_root": str(tmp_path / "output"),
        "aa_data": str(aa_data),
        "install": False,
    }
    return options, cast, resources


def _characters(result):
    return load_manifest(result["project_dir"])["CharacterOverrides"]


def _files(root):
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def _scripts(aap):
    payload = json.loads(Path(aap).read_text(encoding="utf-8"))
    return [
        row
        for node in payload["nodes"]["$values"]
        for row in node.get("Scripts", {}).get("$values", [])
    ]


def _build_environment(tmp_path):
    options, cast, resources = _inputs(tmp_path)
    store = DraftStore(base_dir=str(tmp_path / "drafts"))
    store.create_draft(
        token="teacher-draft",
        text="SourceTeacher: Keep this line.\n",
        project="TeacherDemo",
        cast=cast,
    )
    _json(store.get_draft_path("teacher-draft") / "resources.json", resources)
    manager = BuildBundleManager(
        store=store,
        output_root=options["output_root"],
        aa_data=options["aa_data"],
    )
    installer = InstallManager(
        store=store,
        aa_data_dir=options["aa_data"],
        record_path=str(tmp_path / "install-record.json"),
        running_probe=lambda: False,
    )
    return options, cast, resources, store, manager, installer


def test_recompile_updates_managed_teacher_name_and_clears_organization(tmp_path):
    options, cast, resources = _inputs(tmp_path)
    first = compile_script(options)
    assert _characters(first)[0]["Nickname"] == "Schale"

    cast["cast"]["SourceTeacher"].update(name="New Teacher", club="")
    cast["teacher_identity"].update(display_name="New Teacher", organization="")
    resources["characters"][0].update(name="New Teacher", club="")
    _json(Path(options["cast"]), cast)
    _json(Path(options["index"]), resources)
    second = compile_script(options)

    assert _characters(second) == [
        {
            "Identifier": TEACHER_ID,
            "Name": "New Teacher",
            "Nickname": "",
            "CharacterReference": None,
            "OriginalIdentifier": None,
            "SpinePortraitPath": None,
            "SmallPortraitPath": None,
        }
    ]


@pytest.mark.parametrize(
    "collision",
    [
        "SpinePortraitPath",
        "SmallPortraitPath",
        "CharacterReference",
        "OriginalIdentifier",
        "directory",
    ],
)
def test_compile_refuses_existing_portrait_without_overwriting_outputs(tmp_path, collision):
    options, _, _ = _inputs(tmp_path)
    first = compile_script(options)
    root = Path(first["project_dir"])
    if collision == "directory":
        (root / "characters" / TEACHER_ID).mkdir(parents=True)
    else:
        manifest = load_manifest(root)
        manifest["CharacterOverrides"][0][collision] = "existing-portrait"
        write_manifest_atomic(root, manifest)
    before = _files(Path(options["output_root"]))
    with pytest.raises(TeacherIdentityError) as caught:
        compile_script(options)
    assert caught.value.code == "teacher_identity_conflict"
    assert _files(Path(options["output_root"])) == before


def test_frozen_bundle_and_explicit_install_keep_teacher_identity_authoritative(tmp_path):
    options, cast, resources, store, manager, installer = _build_environment(tmp_path)
    aa_data = Path(options["aa_data"])
    aa_before = _files(aa_data)
    old_id = manager.create_compile_snapshot("teacher-draft", 1)

    store.update_teacher_identity(
        token="teacher-draft",
        speaker="SourceTeacher",
        expected_draft_version=1,
        selection={
            "kind": "teacher",
            "schema_version": "teacher-identity/1.0",
            "preset_id": "custom",
            "display_name": "New Teacher",
            "organization": "",
        },
    )
    old_bundle = Path(manager.execute_build_worker("teacher-draft", old_id)["bundle_dir"])
    old_files = _files(old_bundle)
    old_manifest = load_manifest(old_bundle / "project")
    assert old_manifest["CharacterOverrides"][0]["Name"] == "sensei"
    assert old_manifest["CharacterOverrides"][0]["Nickname"] == "Schale"
    assert _files(aa_data) == aa_before
    installer.install_build("teacher-draft", old_id)

    new_id = manager.create_compile_snapshot("teacher-draft", 2)
    new_bundle = Path(manager.execute_build_worker("teacher-draft", new_id)["bundle_dir"])
    before_install = _files(aa_data)
    installer.verify_bundle(new_bundle)
    installer.install_build("teacher-draft", new_id)
    new_manifest = load_manifest(new_bundle / "project")
    assert new_manifest["CharacterOverrides"][0]["Name"] == "New Teacher"
    assert new_manifest["CharacterOverrides"][0]["Nickname"] == ""
    for scope in ("projects", "saves"):
        installed = load_manifest(aa_data / scope / "TeacherDemo")
        assert installed["CharacterOverrides"] == new_manifest["CharacterOverrides"]
    assert _files(aa_data) != before_install
    assert _files(old_bundle) == old_files


@pytest.mark.parametrize(
    "collision",
    ["ordinary_voice", "different_teacher_name", "frozen_portrait", "missing_frozen_declaration"],
)
def test_compile_rejects_ambiguous_teacher_identity_before_writing(tmp_path, collision):
    options, cast, resources = _inputs(tmp_path)
    if collision == "ordinary_voice":
        cast["cast"]["Clerk"] = {"id": TEACHER_ID, "name": "Clerk", "portrait": False}
    elif collision == "different_teacher_name":
        cast["cast"]["AnotherAlias"] = {**cast["cast"]["SourceTeacher"], "name": "Different"}
    elif collision == "frozen_portrait":
        resources["characters"][0].update(spine="unexpected-portrait")
    else:
        resources["characters"] = []
    _json(Path(options["cast"]), cast)
    _json(Path(options["index"]), resources)
    with pytest.raises(TeacherIdentityError) as caught:
        compile_script(options)
    assert caught.value.code == "teacher_identity_conflict"
    assert not Path(options["output_root"]).exists()


def test_teacher_shares_five_portrait_stage_without_changing_source_aliases_or_voice_ids(tmp_path):
    options, cast, resources = _inputs(tmp_path)
    for name in "ABCDE":
        cast["cast"][name] = {"id": name.lower(), "portrait": True, "kind": "portrait"}
        resources["characters"].append(
            {"identifier": name.lower(), "name": name, "spine": "synthetic", "faces": []}
        )
    text = "@camera A,B,C,D,E\nSourceTeacher: All five stay.\n@camera A,B,C,D,E\nOriginalAlias: Continue.\n"
    Path(options["script"]).write_text(text, encoding="utf-8")
    _json(Path(options["cast"]), cast)
    _json(Path(options["index"]), resources)
    aa_before = _files(Path(options["aa_data"]))
    first = compile_script(options)
    rows = _scripts(first["aap_file"])
    for row in rows:
        assert row["speakerSlotNum"] == 0
        assert row["characters"]["$values"][0]["name"] == TEACHER_ID
        assert {c["name"] for c in row["characters"]["$values"][1:]} == set("abcde")
    assert [row["text"] for row in rows] == ["All five stay.", "Continue."]
    original_manifest = _characters(first)
    frozen = json.loads(
        (Path(first["project_dir"]) / "aa_resources.json").read_text(encoding="utf-8")
    )
    assert frozen["characters"][0] == resources["characters"][0]
    second = compile_script(options)
    assert _scripts(second["aap_file"]) == rows
    assert _characters(second) == original_manifest
    cast["cast"]["SourceTeacher"].update(name="Updated Teacher", club="")
    cast["teacher_identity"].update(display_name="Updated Teacher", organization="")
    resources["characters"][0].update(name="Updated Teacher", club="")
    _json(Path(options["cast"]), cast)
    _json(Path(options["index"]), resources)
    renamed = compile_script(options)
    assert _scripts(renamed["aap_file"]) == rows
    assert _characters(renamed)[0]["Name"] == "Updated Teacher"
    assert _characters(renamed)[0]["Nickname"] == ""
    assert Path(options["script"]).read_text(encoding="utf-8") == text
    assert _files(Path(options["aa_data"])) == aa_before


@pytest.mark.parametrize("scope", ["projects", "saves"])
@pytest.mark.parametrize(
    "collision",
    [
        "SpinePortraitPath",
        "SmallPortraitPath",
        "CharacterReference",
        "OriginalIdentifier",
        "directory",
    ],
)
def test_install_teacher_collision_preserves_aa_files_and_bundle(tmp_path, scope, collision):
    options, _, _, _, manager, installer = _build_environment(tmp_path)
    build_id = manager.create_compile_snapshot("teacher-draft", 1)
    bundle = Path(manager.execute_build_worker("teacher-draft", build_id)["bundle_dir"])
    aa_data = Path(options["aa_data"])
    target = aa_data / scope / "TeacherDemo"
    if collision == "directory":
        (target / "characters" / TEACHER_ID).mkdir(parents=True)
        (target / "characters" / TEACHER_ID / "private.bin").write_bytes(b"synthetic-marker")
    else:
        row = {
            "Identifier": TEACHER_ID,
            "Name": "Existing",
            "Nickname": "Previous",
            collision: "existing-portrait",
        }
        _json(target / "manifest.json", {"CharacterOverrides": [row]})
    before = _files(aa_data)
    bundle_before = _files(bundle)
    with pytest.raises(TeacherIdentityError) as caught:
        installer.install_build("teacher-draft", build_id)
    assert caught.value.code == "teacher_identity_conflict"
    assert _files(aa_data) == before
    assert _files(bundle) == bundle_before


def test_teacher_install_does_not_restore_an_unrelated_project_portrait(tmp_path):
    options, _, _, _, manager, installer = _build_environment(tmp_path)
    build_id = manager.create_compile_snapshot("teacher-draft", 1)
    bundle = Path(manager.execute_build_worker("teacher-draft", build_id)["bundle_dir"])
    aa_data = Path(options["aa_data"])
    other = aa_data / "projects" / "Unrelated"
    asset_dir = other / "characters" / TEACHER_ID
    asset_dir.mkdir(parents=True)
    for suffix in (".skel", ".atlas", ".png"):
        (asset_dir / f"other{suffix}").write_bytes(b"synthetic-resource")
    _json(
        other / "manifest.json",
        {
            "CharacterOverrides": [
                {
                    "Identifier": TEACHER_ID,
                    "Name": "Other Portrait",
                    "Nickname": "Other",
                    "SpinePortraitPath": f"characters\\{TEACHER_ID}\\other",
                }
            ]
        },
    )
    before = _files(other)
    installer.install_build("teacher-draft", build_id)
    expected = load_manifest(bundle / "project")["CharacterOverrides"]
    for scope in ("projects", "saves"):
        target = aa_data / scope / "TeacherDemo"
        assert load_manifest(target)["CharacterOverrides"] == expected
        assert not (target / "characters" / TEACHER_ID).exists()
    assert _files(other) == before


def test_install_rejects_missing_teacher_declaration_even_when_previous_install_has_one(tmp_path):
    options, _, _, _, manager, installer = _build_environment(tmp_path)
    build_id = manager.create_compile_snapshot("teacher-draft", 1)
    bundle = Path(manager.execute_build_worker("teacher-draft", build_id)["bundle_dir"])
    installer.install_build("teacher-draft", build_id)
    manifest_path = bundle / "project" / "manifest.json"
    manifest = load_manifest(bundle / "project")
    manifest["CharacterOverrides"] = []
    _json(manifest_path, manifest)
    entries = json.loads((bundle / "files.json").read_text(encoding="utf-8"))
    for entry in entries:
        if entry["path"] == "project/manifest.json":
            entry.update(size=manifest_path.stat().st_size, sha256=calc_file_sha256(manifest_path))
    _json(bundle / "files.json", entries)
    before = _files(Path(options["aa_data"]))
    with pytest.raises(TeacherIdentityError) as caught:
        installer.install_build("teacher-draft", build_id)
    assert caught.value.code == "teacher_identity_conflict"
    assert _files(Path(options["aa_data"])) == before
