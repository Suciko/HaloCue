import pytest


@pytest.mark.parametrize("field", ["spine", "spine_signature", "outfit_key"])
def test_teacher_declaration_cannot_restore_portrait_assets(field):
    from teacher_identity import (
        TeacherIdentityError,
        prepare_teacher_binding,
        teacher_override_from_mapping,
    )

    cast, _, _ = prepare_teacher_binding(
        {"cast": {}},
        {},
        "Teacher",
        {
            "kind": "teacher",
            "schema_version": "teacher-identity/1.0",
            "preset_id": "teacher_shale",
        },
    )
    mapping = {**cast["cast"]["Teacher"], field: "synthetic-portrait"}
    with pytest.raises(TeacherIdentityError) as error:
        teacher_override_from_mapping(mapping)
    assert error.value.code == "teacher_identity_conflict"


def test_teacher_creation_prepares_one_no_portrait_identity_and_resource():
    from teacher_identity import prepare_teacher_binding

    cast, resources, affected = prepare_teacher_binding(
        {"cast": {}},
        {"characters": []},
        "SourceTeacher",
        {"kind": "teacher", "schema_version": "teacher-identity/1.0", "preset_id": "teacher_shale"},
    )
    identity = cast["teacher_identity"]
    binding = cast["cast"]["SourceTeacher"]
    assert identity["display_name"] == "老师"
    assert identity["organization"] == "沙勒"
    assert identity["character_id"].startswith("hc-teacher-")
    assert binding["id"] == identity["character_id"]
    assert binding["role"] == "teacher"
    assert binding["portrait"] is False
    assert resources["characters"][0]["identifier"] == binding["id"]
    assert resources["characters"][0]["spine"] == ""
    assert affected == ["SourceTeacher"]


@pytest.mark.parametrize("selection", [None, [], "teacher", 1, True])
def test_teacher_selection_rejects_non_object_inputs(selection):
    from teacher_identity import TeacherIdentityError, prepare_teacher_binding

    with pytest.raises(TeacherIdentityError) as exc:
        prepare_teacher_binding({"cast": {}}, {"characters": []}, "Teacher", selection)
    assert exc.value.code == "invalid_teacher_identity"


@pytest.mark.parametrize("damage", ["alias", "resource", "portrait", "catalogue", "cast"])
def test_teacher_update_does_not_silently_repair_corrupt_frozen_identity(damage):
    from teacher_identity import TeacherIdentityError, prepare_teacher_binding

    selection = {
        "kind": "teacher",
        "schema_version": "teacher-identity/1.0",
        "preset_id": "teacher_shale",
    }
    cast, resources, _ = prepare_teacher_binding({"cast": {}}, {}, "Teacher", selection)
    if damage == "alias":
        cast["cast"]["Teacher"]["name"] = "Tampered"
    elif damage == "resource":
        resources["characters"][0]["club"] = "Tampered"
    elif damage == "portrait":
        cast["cast"]["Teacher"]["portrait"] = True
    elif damage == "catalogue":
        resources = []
    else:
        cast = []

    with pytest.raises(TeacherIdentityError) as exc:
        prepare_teacher_binding(cast, resources, "Teacher", selection)
    assert exc.value.status == 409


@pytest.mark.parametrize(
    "preset,name,organization",
    [
        ("sensei_shale", "sensei", "沙勒"),
        ("sensei_xialai", "sensei", "夏莱"),
        ("teacher_shale", "老师", "沙勒"),
        ("teacher_xialai", "老师", "夏莱"),
    ],
)
def test_all_four_presets_round_trip_and_reuse_identity(preset, name, organization):
    import json
    from teacher_identity import prepare_teacher_binding, validate_teacher_identity

    selection = {"kind": "teacher", "schema_version": "teacher-identity/1.0", "preset_id": preset}
    original_cast, original_resources = (
        {"cast": {"Clerk": {"kind": "voice", "id": "clerk"}}},
        {"characters": []},
    )
    cast, resources, _ = prepare_teacher_binding(
        original_cast, original_resources, "Teacher", selection
    )
    assert original_cast == {"cast": {"Clerk": {"kind": "voice", "id": "clerk"}}}
    assert original_resources == {"characters": []}
    assert (cast["teacher_identity"]["display_name"], cast["teacher_identity"]["organization"]) == (
        name,
        organization,
    )
    assert (
        validate_teacher_identity(json.loads(json.dumps(cast["teacher_identity"])))
        == cast["teacher_identity"]
    )
    unchanged, same_resources, affected = prepare_teacher_binding(
        cast, resources, "Teacher", selection
    )
    assert unchanged == cast
    assert same_resources == resources
    assert affected == []
    assert cast["cast"]["Clerk"] == original_cast["cast"]["Clerk"]


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"schema_version": "teacher-identity/2.0"}, "teacher_identity_version_unsupported"),
        ({"preset_id": "missing"}, "invalid_teacher_preset"),
        ({"id": "supplied-id"}, "invalid_teacher_identity"),
        ({"organization": "override"}, "invalid_teacher_identity"),
        ({"preset_id": "custom", "display_name": ""}, "invalid_teacher_identity"),
        ({"preset_id": "custom", "display_name": "name\nsecond"}, "invalid_teacher_identity"),
        ({"preset_id": "custom", "display_name": "a" * 81}, "invalid_teacher_identity"),
        (
            {"preset_id": "custom", "display_name": "Teacher", "organization": []},
            "invalid_teacher_identity",
        ),
    ],
)
def test_teacher_selection_validation_is_versioned_and_strict(changes, code):
    from teacher_identity import TeacherIdentityError, prepare_teacher_binding

    selection = {
        "kind": "teacher",
        "schema_version": "teacher-identity/1.0",
        "preset_id": "teacher_shale",
        **changes,
    }
    with pytest.raises(TeacherIdentityError) as exc:
        prepare_teacher_binding({"cast": {}}, {}, "Teacher", selection)
    assert exc.value.code == code


@pytest.mark.parametrize(
    "collision", ["portrait", "ordinary_cast", "duplicate", "face_capability", "other_teacher"]
)
def test_teacher_identity_never_reuses_colliding_resource_or_ordinary_character(collision):
    import copy
    from teacher_identity import TeacherIdentityError, prepare_teacher_binding

    selection = {
        "kind": "teacher",
        "schema_version": "teacher-identity/1.0",
        "preset_id": "teacher_shale",
    }
    cast, resources, _ = prepare_teacher_binding({"cast": {}}, {}, "Teacher", selection)
    identifier = cast["teacher_identity"]["character_id"]
    if collision == "portrait":
        resources["characters"][0]["spine"] = "portrait"
    elif collision == "ordinary_cast":
        cast["cast"]["Clerk"] = {"id": identifier, "kind": "voice"}
    elif collision == "duplicate":
        resources["characters"].append(copy.deepcopy(resources["characters"][0]))
    elif collision == "face_capability":
        resources["face_capabilities"] = {identifier: []}
    else:
        resources["characters"].append({"identifier": "other", "role": "teacher"})
    with pytest.raises(TeacherIdentityError) as exc:
        prepare_teacher_binding(cast, resources, "Teacher", selection)
    assert exc.value.code == "teacher_identity_conflict"


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": "teacher-identity/2.0"},
        {"character_id": "../unsafe"},
        {"display_name": None},
        {"organization": []},
        {"preset_id": "unknown"},
    ],
)
def test_persisted_teacher_identity_has_a_stable_corruption_error(changes):
    from teacher_identity import TeacherIdentityError, validate_teacher_identity

    identity = {
        "schema_version": "teacher-identity/1.0",
        "character_id": "hc-teacher-" + "1" * 32,
        "preset_id": "custom",
        "display_name": "Advisor",
        "organization": "",
        **changes,
    }
    with pytest.raises(TeacherIdentityError) as exc:
        validate_teacher_identity(identity)
    assert exc.value.code == "teacher_identity_corrupt"
    assert exc.value.status == 409
