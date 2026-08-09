from annotate import annotation_constraints, build_static


def test_semantic_binary_face_evidence_allows_only_its_actual_non_special_ids():
    index = {
        "bg": {}, "sounds": [], "enums": {"emoticon": {}, "action": {}},
        "characters": [{
            "identifier": "626652156", "faces": [],
            "expression_mode": "semantic_modular",
        }],
        "face_capabilities": {"626652156": [{
            "spine_signature": "date", "outfit_key": "Kei_Date_Outfit",
            "faces": [
                {"id": "03", "sources": ["spine_semantic"], "cn": "surprise"},
                {"id": "99", "sources": ["aap_observed"], "cn": ""},
            ],
        }]},
    }
    cast = {"Kei": {
        "id": "626652156", "portrait": True,
        "spine_signature": "date", "outfit_key": "Kei_Date_Outfit",
    }}

    constraints = annotation_constraints(index, cast)

    assert constraints["faces_by_id"]["626652156"] == {"03"}


def test_prompt_receives_semantic_face_ids_with_their_labels():
    index = {
        "bg": {}, "sounds": [], "enums": {"emoticon": {}, "action": {}},
        "characters": [{"identifier": "626652156", "expression_mode": "semantic_modular"}],
        "face_capabilities": {"626652156": [{
            "spine_signature": "date", "outfit_key": "Kei_Date_Outfit",
            "faces": [{"id": "03", "label": "surprise", "cn": "surprise", "sources": ["spine_semantic"]}],
        }]},
    }
    cast = {"Kei": {
        "id": "626652156", "portrait": True,
        "spine_signature": "date", "outfit_key": "Kei_Date_Outfit",
    }}

    prompt = build_static(index, cast, ["Kei"])

    assert "03=surprise" in prompt
