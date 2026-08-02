from pathlib import Path

from spine_semantic_faces import extract_semantic_face_combinations


KEI_DATE = Path(
    r"D:\桌面\蔚蓝档案二创\角色立绘与美术周边\官方角色立绘\天童凯伊（约会服）\Kei_Date_Outfit\Kei_Date_Outfit.skel"
)


def test_kei_semantic_skeleton_exposes_actual_numbered_face_combinations():
    combinations = extract_semantic_face_combinations(KEI_DATE)

    assert {"00", "01", "42", "99"}.issubset(combinations)
    assert all(combinations[face_id]["parts"] for face_id in ("00", "01", "42"))
    assert combinations["99"]["special"] is True


def test_face_combinations_keep_raw_parts_and_deduplicated_semantic_labels():
    combinations = extract_semantic_face_combinations(KEI_DATE)

    for face_id, record in combinations.items():
        assert record["face_id"] == face_id
        assert record["raw_parts"]
        assert record["labels"] == list(dict.fromkeys(record["labels"]))


def test_delayed_blink_timeline_does_not_replace_the_stable_eye_expression():
    combinations = extract_semantic_face_combinations(KEI_DATE)

    assert "普通睁眼" in combinations["01"]["raw_parts"]
    assert "半闭眼（眨眼差分用）" not in combinations["01"]["raw_parts"]
    assert "普通睁眼" in combinations["05"]["raw_parts"]
    assert "微笑嘴" in combinations["05"]["raw_parts"]
    assert "闭眼（可眨眼差分）" in combinations["99"]["raw_parts"]


def test_plain_creator_part_names_become_useful_semantic_labels():
    combinations = extract_semantic_face_combinations(KEI_DATE)

    assert "轻微微笑" in combinations["05"]["labels"]
    assert "闭眼" in combinations["99"]["labels"]
    assert "眨眼差分用" not in combinations["01"]["labels"]


def test_semantic_summary_does_not_let_neutral_parts_override_surprise():
    combinations = extract_semantic_face_combinations(KEI_DATE)

    surprised = combinations["03"]
    assert surprised["primary_emotion"] == "惊讶"
    assert surprised["semantic_labels"][:2] == ["惊讶", "意外"]
    assert "平静" not in surprised["semantic_labels"]
    assert "正常" not in surprised["semantic_labels"]


def test_semantic_summary_does_not_call_an_angry_face_calm():
    combinations = extract_semantic_face_combinations(KEI_DATE)

    angry = combinations["35"]
    assert angry["primary_emotion"] == "愤怒"
    assert "生气" in angry["semantic_labels"]
    assert "冷静" not in angry["semantic_labels"]
    assert "理性" not in angry["semantic_labels"]


def test_semantic_summary_keeps_neutral_and_subtle_smile_distinct():
    combinations = extract_semantic_face_combinations(KEI_DATE)

    assert combinations["00"]["primary_emotion"] == "平静"
    assert combinations["05"]["primary_emotion"] == "轻微微笑"


def test_semantic_summary_uses_the_strongest_component_instead_of_the_first_part():
    combinations = extract_semantic_face_combinations(KEI_DATE)

    assert combinations["11"]["primary_emotion"] == "开心"
    assert combinations["25"]["primary_emotion"] == "紧张"
    assert combinations["32"]["primary_emotion"] == "大哭"


def test_semantic_summary_keeps_visible_modifiers_for_model_selection():
    combinations = extract_semantic_face_combinations(KEI_DATE)

    assert combinations["15"]["semantic_labels"] == ["平静", "害羞", "脸红"]
    assert combinations["42"]["primary_emotion"] == "慌张"
    assert combinations["42"]["semantic_labels"][:3] == ["慌张", "害羞", "强烈脸红"]


def test_semantic_summary_distinguishes_neutral_mouth_and_eye_states():
    combinations = extract_semantic_face_combinations(KEI_DATE)

    assert combinations["02"]["semantic_labels"] == ["平静", "开口", "露齿"]
    assert combinations["99"]["semantic_labels"] == ["平静", "闭眼"]
