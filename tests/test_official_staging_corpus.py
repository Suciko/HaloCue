import json
from pathlib import Path

import pytest

from official_staging_corpus import (
    OfficialStagingExtractor,
    extract_corpus,
    normalize_command,
    parse_script_events,
)


def test_parse_preserves_order_and_staging_arguments():
    events = parse_script_events(
        "3;모모카;17\n#3;em;[반응]\n#3;m2\n#wait;1000"
    )
    assert [event["line_type"] for event in events] == [
        "character",
        "slot_command",
        "slot_command",
        "wait",
    ]
    assert events[0]["raw_line"] == "3;모모카;17"
    assert events[1]["slot"] == 3
    assert events[1]["command_normalized"] == "em"
    assert events[1]["arguments_raw"] == ["[반응]"]
    assert events[2]["command_normalized"] == "m2"
    assert events[3]["milliseconds"] == 1000


def test_parse_keeps_empty_text_staging_node_and_unknown_commands():
    events = parse_script_events("3;모모카;17\n#3;neverSeen;abc\n#Wait;2500")
    assert events[0]["line_type"] == "character"
    assert events[0]["dialogue_kr"] == ""
    assert events[1]["parse_status"] == "unknown"
    assert events[1]["raw_line"] == "#3;neverSeen;abc"
    assert events[2]["command_normalized"] == "wait"
    assert events[2]["parse_status"] == "case_variant"


def test_normalize_command_reports_alias_status():
    assert normalize_command("#Title") == ("title", "case_variant")
    assert normalize_command("#closuep") == ("closuep", "unknown")


def test_extract_row_keeps_raw_fields_and_resource_resolution(tmp_path):
    repo = tmp_path / "repo"
    excel = repo / "ExcelDB"
    excel.mkdir(parents=True)
    (excel / "ScenarioBGNameGlobalExcel.json").write_text(
        json.dumps({"data_list": [{"id": 123, "name": "BG_Test"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    extractor = OfficialStagingExtractor(repo)
    row = {
        "group_id": 7,
        "script_kr": "3;모모카;17",
        "text_tw": "",
        "text_jp": "",
        "text_en": "",
        "text_th": "",
        "bg_name": 123,
        "bgm_id": 999,
        "bg_effect": 0,
        "transition": 0,
        "sound": "",
        "popup_file_name": "",
        "voice_id": 0,
        "selection_group": 0,
        "teen_mode": False,
    }
    record = extractor.extract_row(row, "ExcelDB/ScenarioScriptExcel_0.json", 0, 4, 4)
    assert record["raw"]["script_kr"] == row["script_kr"]
    assert record["raw"]["bg_name"] == 123
    assert record["resources"]["background"]["resolved"] == "BG_Test"
    assert record["text"]["localization_status"] == "empty_by_design"
    assert record["has_staging"] is True


def test_extract_row_separates_dialogue_speakers_from_silent_staging_characters(tmp_path):
    repo = tmp_path / "repo"
    (repo / "ExcelDB").mkdir(parents=True)
    record = OfficialStagingExtractor(repo).extract_row(
        {
            "group_id": 31070,
            "script_kr": "5;아즈사;02\n1;하나코;03;이건 대화야.\n#5;closeup\n#1;wait;5000",
            "text_tw": "这是一句对白。",
        },
        "ExcelDB/ScenarioScriptExcel_0.json", 0, 0, 0,
    )
    assert record["speakers"] == ["하나코"]
    assert record["dialogue_speakers"] == ["하나코"]
    assert record["declared_character_names"] == ["아즈사", "하나코"]
    assert [item["character_name_kr"] for item in record["staged_characters"]] == ["아즈사", "하나코"]


def test_extract_row_classifies_localized_screen_text_without_character_dialogue(tmp_path):
    repo = tmp_path / "repo"
    (repo / "ExcelDB").mkdir(parents=True)
    record = OfficialStagingExtractor(repo).extract_row(
        {"group_id": 9, "script_kr": "", "text_tw": "[ns]「感觉不错呢。」"},
        "ExcelDB/ScenarioScriptExcel_0.json", 0, 0, 0,
    )
    assert record["speakers"] == []
    assert record["semantic_kind"] == "screen_text"
    assert record["screen_text_events"][0]["screen_text_raw"] == "[ns]「感觉不错呢。」"


def test_extract_corpus_writes_shards_and_manifest(tmp_path):
    repo = tmp_path / "repo"
    excel = repo / "ExcelDB"
    excel.mkdir(parents=True)
    rows = [{"group_id": 1, "script_kr": "#wait;100", "text_tw": ""}]
    for index in range(3):
        (excel / f"ScenarioScriptExcel_{index}.json").write_text(
            json.dumps({"data_list": rows}, ensure_ascii=False), encoding="utf-8"
        )
    output = tmp_path / "out"
    manifest = extract_corpus(repo, output)
    assert manifest["record_counts"]["total"] == 3
    assert (output / "records" / "scenario_0.jsonl").is_file()
    assert (output / "records" / "scenario_2.jsonl").is_file()
    exported = [
        json.loads(line)
        for line in (output / "records" / "scenario_0.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert exported[0]["record_uid"] == "scenario_0:0"
    assert exported[0]["next_record_uid"] == "scenario_1:0"


def test_extract_corpus_links_noncontiguous_rows_within_the_same_group(tmp_path):
    repo = tmp_path / "repo"
    excel = repo / "ExcelDB"
    excel.mkdir(parents=True)
    rows = [
        {"group_id": 1, "script_kr": "#wait;100", "text_tw": ""},
        {"group_id": 2, "script_kr": "#wait;200", "text_tw": ""},
        {"group_id": 1, "script_kr": "#wait;300", "text_tw": ""},
    ]
    for index in range(3):
        (excel / f"ScenarioScriptExcel_{index}.json").write_text(
            json.dumps({"data_list": rows if index == 0 else []}, ensure_ascii=False),
            encoding="utf-8",
        )
    output = tmp_path / "out"
    extract_corpus(repo, output)
    records = [json.loads(line) for line in (output / "records" / "scenario_0.jsonl").read_text(encoding="utf-8").splitlines()]
    assert records[0]["next_record_uid"] == "scenario_0:2"
    assert records[2]["previous_record_uid"] == "scenario_0:0"


def test_narration_without_tw_is_marked_as_missing_localization(tmp_path):
    repo = tmp_path / "repo"
    (repo / "ExcelDB").mkdir(parents=True)
    record = OfficialStagingExtractor(repo).extract_row(
        {"group_id": 9, "script_kr": "#na;검은 양복;아주 오래전의 일입니다.", "text_tw": ""},
        "ExcelDB/ScenarioScriptExcel_0.json", 0, 0, 0,
    )
    assert record["text"]["kr_script_dialogue"] == ["아주 오래전의 일입니다."]
    assert record["text"]["localization_status"] == "missing_tw_with_kr_text"


def test_nondefault_top_level_fields_become_ordered_field_events(tmp_path):
    repo = tmp_path / "repo"
    (repo / "ExcelDB").mkdir(parents=True)
    record = OfficialStagingExtractor(repo).extract_row(
        {
            "group_id": 9, "script_kr": "", "text_tw": "",
            "sound": "SE_Test", "popup_file_name": "Popup_Test", "voice_id": 42,
            "selection_group": 2, "teen_mode": True,
        },
        "ExcelDB/ScenarioScriptExcel_0.json", 0, 0, 0,
    )
    assert [event["event_type"] for event in record["field_events"]] == [
        "sound", "popup", "voice", "selection_group", "teen_mode"
    ]
    assert record["resources"]["sound"]["raw_value"] == "SE_Test"


def test_manifest_contains_source_hashes_and_extractor_copy(tmp_path):
    repo = tmp_path / "repo"
    excel = repo / "ExcelDB"
    excel.mkdir(parents=True)
    for index in range(3):
        (excel / f"ScenarioScriptExcel_{index}.json").write_text(
            json.dumps({"data_list": []}), encoding="utf-8"
        )
    output = tmp_path / "out"
    manifest = extract_corpus(repo, output)
    assert set(manifest["sources"]) == set(SHARD_NAMES_FOR_TEST)
    assert manifest["sources"]["ScenarioScriptExcel_0.json"]["sha256"]
    assert (output / "tools" / "extract_official_staging_corpus.py").is_file()


SHARD_NAMES_FOR_TEST = (
    "ScenarioScriptExcel_0.json",
    "ScenarioScriptExcel_1.json",
    "ScenarioScriptExcel_2.json",
)
