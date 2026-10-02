import json

from halocue_production.name_baseline import CharacterNameBaseline


def test_clean_install_uses_reviewed_name_without_a_private_baseline():
    original = {"identifier": "세리카", "name": "茜香", "spine": "serika"}
    resolved = CharacterNameBaseline().decorate(original)
    assert resolved["name"] == "芹香"
    assert resolved["identifier"] == "세리카"
    assert resolved["spine"] == "serika"
    assert resolved["source_name"] == "茜香"
    assert {"黑见茜香", "黑见芹香", "芹香"}.issubset(resolved["aliases"])
    assert original == {"identifier": "세리카", "name": "茜香", "spine": "serika"}


def test_user_baseline_overrides_reviewed_default(tmp_path):
    path = tmp_path / "names.json"
    path.write_text(
        json.dumps({"characters": [{"identifier": "세리카", "name_ja_fandom": "黑见芹香"}]}),
        encoding="utf-8",
    )
    assert (
        CharacterNameBaseline(path).resolve({"identifier": "세리카", "name": "茜香"})["name"]
        == "黑见芹香"
    )


def test_explicit_resource_translation_is_not_overridden_by_default():
    result = CharacterNameBaseline().resolve(
        {"identifier": "세리카", "name": "茜香", "name_ja_fandom": "用户确认名称"}
    )
    assert result["name"] == "用户确认名称"


def test_unreviewed_variant_keeps_its_identity_and_source_name():
    result = CharacterNameBaseline().decorate({"identifier": "세리카_UNKNOWN", "name": "变体原名"})
    assert result["name"] == "变体原名"
    assert result["name_source"] == "legacy_source_unreviewed"
