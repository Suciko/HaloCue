import json

import aa_manifest_catalog


def _write_manifest(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"CharacterOverrides": rows}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_manifest_reader_uses_last_duplicate_without_modifying_source(tmp_path):
    manifest = tmp_path / "data" / "overrides" / "manifest.json"
    _write_manifest(manifest, [{
        "Identifier": "爱莉(乐队)", "Name": "爱莉",
        "SpinePortraitPath": r"characters\CH0251_spr\CH0251_spr",
    }, {
        "Identifier": "爱莉(乐队)", "Name": "爱莉",
        "SpinePortraitPath": r"characters\NP0189_spr\NP0189_spr",
    }])
    before = manifest.read_bytes()

    rows = aa_manifest_catalog.read_manifest_characters(manifest)

    assert len(rows) == 1
    assert rows[0].spine_key == "np0189_spr"
    assert manifest.read_bytes() == before


def test_runtime_catalog_groups_translation_aliases_without_merging_outfits():
    records = {
        "노아": {
            "ident": "노아", "name": "乃愛", "club": "研讨会",
            "spine": r"UIs\03_Scenario\02_Character\CharacterSpine_CH0095",
            "avatar": "", "source": "official", "nface": 8,
        },
        "诺亚（睡衣）": {
            "ident": "诺亚（睡衣）", "name": "诺亚", "club": "研讨会",
            "spine": r"characters\CH0285_spr\CH0285_spr",
            "avatar": "", "source": "overrides", "nface": 12,
        }
    }
    manifest = [aa_manifest_catalog.AAManifestCharacter(
        "诺亚（睡衣）", "乃爱", "研讨会",
        r"characters\诺亚（睡衣）\CH0285_spr", "",
    )]

    merged, aliases = aa_manifest_catalog.merge_runtime_catalog(
        records, [], manifest
    )

    assert merged["诺亚（睡衣）"]["name"] == "诺亚"
    assert merged["诺亚（睡衣）"]["manifest_bound"] is True
    assert merged["诺亚（睡衣）"]["user_custom"] is False
    assert merged["노아"]["preferred_name"] == "诺亚"
    assert merged["诺亚（睡衣）"]["preferred_name"] == "诺亚"
    targets = {
        ident for alias, ident, _, _ in aliases
        if aa_manifest_catalog.name_key(alias) == aa_manifest_catalog.name_key("乃爱")
    }
    assert targets >= {"노아", "诺亚（睡衣）"}


def test_runtime_catalog_rekeys_unique_spine_match_and_preserves_face_count():
    records = {
        "爱莉（鬼屋装扮）": {
            "ident": "爱莉（鬼屋装扮）", "name": "爱莉", "club": "甜点部",
            "spine": r"characters\NP0227_spr\NP0227_spr",
            "avatar": "", "source": "overrides", "nface": 9,
        }
    }
    manifest = [aa_manifest_catalog.AAManifestCharacter(
        "爱莉（鬼屋）", "愛莉", "甜点部",
        r"characters\爱莉（鬼屋）\NP0227_spr", "",
    )]

    merged, aliases = aa_manifest_catalog.merge_runtime_catalog(
        records, [], manifest
    )

    assert merged["爱莉（鬼屋）"]["catalog_ident"] == "爱莉（鬼屋装扮）"
    assert merged["爱莉（鬼屋）"]["nface"] == 9
    assert merged["爱莉（鬼屋）"]["user_custom"] is False
    alias_keys = {
        aa_manifest_catalog.name_key(alias)
        for alias, ident, _, _ in aliases
        if ident == "爱莉（鬼屋）"
    }
    assert alias_keys >= {
        aa_manifest_catalog.name_key("爱莉"),
        aa_manifest_catalog.name_key("爱莉（鬼屋装扮）"),
    }


def test_model_index_copies_face_capabilities_to_local_manifest_identifier():
    source_capabilities = [{
        "spine_signature": "sig", "outfit_key": "NP0227_spr",
        "spine": "NP0227_spr", "faces": [{"id": "03", "cn": "微笑"}],
    }]
    index = {
        "characters": [{
            "identifier": "爱莉（鬼屋装扮）", "name": "爱莉", "club": "甜点部",
            "spine": r"characters\NP0227_spr\NP0227_spr", "faces": [{"id": "03"}],
        }],
        "face_capabilities": {"爱莉（鬼屋装扮）": source_capabilities},
    }
    manifest = [aa_manifest_catalog.AAManifestCharacter(
        "爱莉（鬼屋）", "愛莉", "甜点部",
        r"characters\爱莉（鬼屋）\NP0227_spr", "",
    )]

    merged = aa_manifest_catalog.merge_model_index(index, manifest)

    local = next(
        row for row in merged["characters"]
        if row["identifier"] == "爱莉（鬼屋）"
    )
    assert local["catalog_identifier"] == "爱莉（鬼屋装扮）"
    assert merged["face_capabilities"]["爱莉（鬼屋）"] == source_capabilities
    assert merged["face_capabilities"]["爱莉（鬼屋）"] is not source_capabilities
    assert index["characters"] == [index["characters"][0]]


def test_unknown_manifest_character_remains_selectable_without_invented_faces():
    manifest = [aa_manifest_catalog.AAManifestCharacter(
        "新人物", "新人物", "", r"characters\新人物\NP9999_spr", "",
    )]

    merged, aliases = aa_manifest_catalog.merge_runtime_catalog({}, [], manifest)
    index = aa_manifest_catalog.merge_model_index({"characters": []}, manifest)

    assert merged["新人物"]["source"] == "aa_manifest"
    assert merged["新人物"]["user_custom"] is True
    assert merged["新人物"]["nface"] == 0
    assert aliases[0][1] == "新人物"
    assert index["characters"][0]["faces"] == []
    assert index["characters"][0]["user_custom"] is True


def test_user_rename_does_not_turn_known_resource_into_custom_content():
    records = {
        "노아": {
            "ident": "노아", "name": "乃愛", "club": "研讨会",
            "spine": "CharacterSpine_CH0095", "avatar": "",
            "source": "official", "nface": 9,
        }
    }
    manifest = [aa_manifest_catalog.AAManifestCharacter(
        "노아", "我自己改的诺亚名", "研讨会",
        "CharacterSpine_CH0095", "",
    )]

    merged, _ = aa_manifest_catalog.merge_runtime_catalog(records, [], manifest)

    assert merged["노아"]["manifest_bound"] is True
    assert merged["노아"]["user_custom"] is False
    assert merged["노아"]["manifest_name"] == "我自己改的诺亚名"


def test_name_key_normalizes_traditional_chinese_and_parentheses():
    assert aa_manifest_catalog.name_key(" 愛麗絲 ") == "爱丽丝"
    assert aa_manifest_catalog.name_key("诺亚（睡衣）") == aa_manifest_catalog.name_key("諾亞(睡衣)")


def test_bundled_alias_index_contains_regional_name_pairs():
    identities = {
        item.canonical_name: set(item.aliases)
        for item in aa_manifest_catalog.load_character_identities()
    }

    assert len(identities) >= 100
    assert identities["生盐诺亚"] >= {"诺亚", "乃爱"}
    assert identities["黑见芹香"] >= {"黑见芹香", "茜香"}
