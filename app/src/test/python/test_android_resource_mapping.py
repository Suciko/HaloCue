import json

import android_resource_mapping
import script2aap


def test_mapping_keeps_pc_identifier_and_refreshes_faces_by_outfit():
    index = {
        "bg": {},
        "sounds": [],
        "characters": [
            {
                "identifier": "pc-id",
                "name": "old name",
                "club": "old club",
                "spine": "characters/old/CH0001_spr",
                "outfit_key": "CH0001_spr",
                "faces": [{"id": "00", "raw": "normal", "label": "normal"}],
            }
        ],
        "face_capabilities": {},
    }
    mapping = {
        "schema_version": 1,
        "identifier_aliases": {"pc-id": "package-id"},
        "characters": [
            {
                "identifier": "pc-id",
                "package_identifier": "package-id",
                "name": "new translation",
                "club": "new club",
                "spine": "characters/new/CH0001_spr",
                "outfit_key": "CH0001_spr",
                "faces": [
                    {"id": "00", "raw": "normal", "label": "normal"},
                    {"id": "01", "raw": "smile", "label": "smile"},
                ],
                "new_to_pc_index": False,
            }
        ],
        "summary": {"mapped_characters": 1},
    }

    merged = android_resource_mapping.merge_mapping(index, mapping)

    assert merged["characters"][0]["identifier"] == "pc-id"
    assert merged["characters"][0]["name"] == "old name"
    assert [face["id"] for face in merged["characters"][0]["faces"]] == ["00", "01"]
    assert merged["identifier_aliases"] == {"pc-id": "package-id"}
    variants = merged["face_capabilities"]["pc-id"]
    assert variants[0]["outfit_key"] == "CH0001_spr"
    assert [face["id"] for face in variants[0]["faces"]] == ["00", "01"]


def test_mapping_adds_package_characters_missing_from_pc_index():
    index = {"bg": {}, "sounds": [], "characters": [], "face_capabilities": {}}
    mapping = {
        "schema_version": 1,
        "identifier_aliases": {},
        "characters": [
            {
                "identifier": "new-id",
                "package_identifier": "new-id",
                "name": "new name",
                "club": "new club",
                "spine": "characters/new/CH9999_spr",
                    "outfit_key": "CH9999_spr",
                "faces": [{"id": "03", "raw": "smile", "label": "smile"}],
                "new_to_pc_index": True,
            }
        ],
        "summary": {"mapped_characters": 1},
    }

    merged = android_resource_mapping.merge_mapping(index, mapping)

    assert merged["characters"] == [
        {
            "identifier": "new-id",
            "name": "new name",
                "club": "new club",
                "spine": "characters/new/CH9999_spr",
                "avatar": "CH9999_spr",
                "outfit_key": "CH9999_spr",
            "faces": [{"id": "03", "raw": "smile", "label": "smile"}],
            "android_package_identifier": "new-id",
        }
    ]


def test_bundled_mapping_matches_the_supplied_extra_package():
    mapping = android_resource_mapping.load_mapping()

    assert mapping["source_package"] == "And20241023前-20260609.zip"
    assert mapping["summary"] == {
        "package_characters": 194,
        "mapped_characters": 192,
        "identifier_aliases": 52,
        "new_characters": 40,
        "skipped_characters": 1,
    }
    assert mapping["identifier_aliases"]["阿露(礼服)"] == "阿露（礼服）"


def test_compiler_translates_only_serialized_character_identifiers():
    scenes = [
        (
            "scene",
            [
                {
                    "characters": {
                        "$values": [
                            {"name": "pc-id", "faceId": "03"},
                            {"name": "unchanged", "faceId": "00"},
                            {"name": "", "faceId": "00"},
                        ]
                    }
                }
            ],
        )
    ]

    script2aap.apply_identifier_aliases(scenes, {"pc-id": "package-id"})

    characters = scenes[0][1][0]["characters"]["$values"]
    assert characters[0] == {"name": "package-id", "faceId": "03"}
    assert characters[1]["name"] == "unchanged"
    assert characters[2]["name"] == ""


def test_compiler_resolves_ambiguous_alias_by_selected_outfit():
    index = {
        "characters": [
            {"identifier": "pc-id", "outfit_key": "official_spr"},
            {
                "identifier": "pc-id",
                "outfit_key": "extra_spr",
                "android_package_identifier": "package-extra-id",
            },
        ],
        "identifier_aliases": {"pc-id": "package-extra-id"},
    }

    assert script2aap.identifier_aliases_for_cast(
        index, {"cast": {"角色": {"id": "pc-id", "outfit_key": "extra_spr"}}}
    ) == {"pc-id": "package-extra-id"}
    assert script2aap.identifier_aliases_for_cast(
        index, {"cast": {"角色": {"id": "pc-id", "outfit_key": "official_spr"}}}
    ) == {}
    assert script2aap.identifier_aliases_for_cast(
        index, {"cast": {"角色": {"id": "pc-id"}}}
    ) == {}


def test_compiler_allows_unambiguous_alias_without_outfit():
    index = {
        "characters": [
            {
                "identifier": "pc-id",
                "outfit_key": "only_spr",
                "android_package_identifier": "package-id",
            }
        ],
        "identifier_aliases": {"pc-id": "package-id"},
    }

    assert script2aap.identifier_aliases_for_cast(
        index, {"cast": {"角色": {"id": "pc-id"}}}
    ) == {"pc-id": "package-id"}
