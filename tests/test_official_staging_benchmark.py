import json

from official_staging_benchmark import (
    BenchmarkSample,
    benchmark_sample,
    dialogue_source,
    generated_profile,
    load_sample_records,
    official_profile,
    verify_generated_scope,
)


def record(index, script, *, dialogue=False, zh_cn="", sound="", transition=0):
    events = []
    for line in script.splitlines():
        bits = line.lstrip("#").split(";")
        # Slot commands use the second field: #3;al, #3;em, etc.
        command = (
            bits[0] if bits and bits[0].lower() in {"wait", "all", "enter", "exit"}
            else (bits[1] if len(bits) > 1 else "")
        ) if line.startswith("#") else ""
        if command:
            events.append({"command_normalized": command, "dialogue_kr": ""})
        elif ";" in line:
            events.append({
                "command_normalized": "",
                "character_name_kr": bits[1] if dialogue and len(bits) > 1 else "",
                "dialogue_kr": bits[-1] if dialogue else "",
            })
    return {
        "global_record_index": index, "has_dialogue": dialogue,
        "raw": {"sound": sound, "transition": transition, "bg_name": 1 if transition else 0},
        "text": {"zh_cn": zh_cn}, "script_events": events,
    }


def write_fixture_corpus(tmp_path):
    root = tmp_path / "corpus"
    records = root / "records"
    records.mkdir(parents=True)
    rows = [
        record(10, "#all;hide"),
        record(11, "3;Alice;01;发现了。\n#3;em;[惊叹]\n#3;jump", dialogue=True, zh_cn="发现了。"),
        record(12, "#3;al\n#wait;800", sound="SE_Step"),
        record(13, "#3;d"),
    ]
    (records / "scenario_0.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    return root


def test_benchmark_extracts_a_bounded_sample_and_exports_dialogue_only(tmp_path):
    root = write_fixture_corpus(tmp_path)
    sample = BenchmarkSample("fixture", "Fixture", "scenario_0", 11, 13, "event", "test")

    rows = load_sample_records(root, sample)
    profile = official_profile(rows)

    assert [row["global_record_index"] for row in rows] == [11, 12, 13]
    assert profile["features"]["real_entrance"] == 0
    assert profile["features"]["real_exit"] == 0
    assert profile["features"]["reveal_or_appearance"] == 1
    assert profile["features"]["reaction"] == 2
    assert profile["features"]["emoticon"] == 1
    assert profile["features"]["action"] == 1
    assert profile["feature_evidence_basis"]["camera_cut"].startswith("normalized_command_only")
    assert profile["feature_confidence"]["silent_staging"] == "low"
    assert dialogue_source(rows) == "Alice: 发现了。\n"


def test_benchmark_reports_missing_structural_capabilities_without_exact_count_scoring(tmp_path):
    root = write_fixture_corpus(tmp_path)
    sample = BenchmarkSample("fixture", "Fixture", "scenario_0", 11, 13, "event", "test")

    report = benchmark_sample(
        root,
        sample,
        "Alice(01): 发现了。\n",
        expected_dialogue="Alice: 发现了。\n",
    )
    generated = generated_profile("@enter Alice 3 左\n@exit Alice 右\nAlice[惊叹]{jump}: 发现了。\n")

    assert "wait" in set(report["missing"])
    assert "silent_staging" in set(report["low_confidence"])
    assert generated["features"]["real_entrance"] == 1
    assert generated["features"]["reaction"] == 1


def test_benchmark_is_explicitly_not_a_similarity_percentage(tmp_path):
    root = write_fixture_corpus(tmp_path)
    sample = BenchmarkSample("fixture", "Fixture", "scenario_0", 11, 13, "event", "test")

    report = benchmark_sample(
        root,
        sample,
        "Alice(01): 发现了。\n",
        expected_dialogue="Alice: 发现了。\n",
    )

    assert report["not_similarity_percentage"] is True
    assert report["method"] == "feature_presence_and_count_report"
    assert "visual similarity" in report["warning"]
    assert all(item["count_comparable"] is False for item in report["comparison"])


def test_generated_profile_counts_camera_reveals_and_silent_staging_without_misclassifying_reactions():
    generated = generated_profile(
        "@bg BG_Room\n@camera_hold Alice,Bob\nAlice[惊叹]{jump}: 找到了。\n"
        "@camera_hold Bob,Carol\n@nodialog\nCarol{open_door}: \n"
        "Carol: 请进。\n"
    )

    assert generated["features"]["background_change"] == 1
    assert generated["features"]["reveal_or_appearance"] == 3
    assert generated["features"]["silent_staging"] == 1
    assert generated["dialogue_lines"] == 2
    assert generated["features"]["reaction"] == 1
    assert generated["features"]["action"] == 2


def test_generated_profile_counts_visual_reveal_separately_from_real_entry():
    generated = generated_profile(
        "@camera_hold 圣娅,绿\n@reveal 绿 5 右\n绿: 第一次接话。\n"
    )

    assert generated["features"]["reveal_or_appearance"] == 3
    assert generated["features"]["visual_reveal"] == 1
    assert generated["features"].get("real_entrance", 0) == 0
    assert generated["features"]["silent_staging"] == 0


def test_generated_profile_does_not_count_camera_hold_as_a_hard_cut():
    generated = generated_profile(
        "@camera_hold Alice,Bob\nAlice: 继续说。\n"
        "@camera_cut Bob\nBob: 反打。\n"
    )

    assert generated["features"]["camera_cut"] == 1


def test_generated_profile_does_not_treat_layout_moves_as_physical_actions():
    generated = generated_profile(
        "@camera_cut Alice,Bob\n@move Alice 2\n@move Bob 4\nAlice: 你好。\n"
    )

    assert "move" not in generated["features"]
    assert generated["features"]["silent_staging"] == 0


def test_scope_verification_ignores_localized_names_but_rejects_content_drift():
    expected = "Alice: first line\nBob: second line\n"
    generated = "## Scene\n甲(01): first line\n@camera_cut 甲\n乙: second line\n"

    verified = verify_generated_scope(expected, generated)
    assert verified["verified"] is True
    assert verified["expected_dialogue_lines"] == 2
    assert verified["generated_dialogue_lines"] == 2

    drifted = verify_generated_scope(expected, generated.replace("second line", "different"))
    assert drifted["verified"] is False
    assert drifted["first_mismatch_index"] == 1


def test_scope_verification_rejoins_annotated_newline_continuations():
    expected = "Alice: first line#nsecond line\n"
    generated = "Alice(01): first line\nAlice(02): #nsecond line\n"

    assert verify_generated_scope(expected, generated)["verified"] is True


def test_benchmark_marks_scope_unverified_without_exact_generation_input(tmp_path):
    root = write_fixture_corpus(tmp_path)
    sample = BenchmarkSample("fixture", "Fixture", "scenario_0", 11, 13, "event", "test")

    report = benchmark_sample(root, sample, "Alice(01): 发现了。\n")

    assert report["scope_verification"]["verified"] is False
    assert report["scope_verification"]["status"] == "not_provided"
    assert report["comparison_interpretable"] is False
    assert report["missing"] == []
    assert {item["status"] for item in report["comparison"]} == {"scope_unverified"}


def test_benchmark_verifies_scope_when_exact_dialogue_input_is_supplied(tmp_path):
    root = write_fixture_corpus(tmp_path)
    sample = BenchmarkSample("fixture", "Fixture", "scenario_0", 11, 13, "event", "test")

    report = benchmark_sample(
        root,
        sample,
        "Alice(01): 发现了。\n",
        expected_dialogue="Alice: 发现了。\n",
        generated_scope="fixture",
    )

    assert report["scope_verification"]["verified"] is True
    assert report["scope_verification"]["official_to_input"]["verified"] is True
    assert report["scope_verification"]["input_to_generated"]["verified"] is True
    assert report["comparison_interpretable"] is True
    assert report["generated_scope"] == "fixture"
