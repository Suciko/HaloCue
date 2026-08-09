import json

from annotation_telemetry import (
    ReasoningTelemetryWriter, RequestTelemetryWriter, build_request_prompt_hashes,
)


def test_request_prompt_hashes_are_stable_and_do_not_include_prompt_text():
    first = build_request_prompt_hashes("stable rules", "dynamic one", "targets one", {"type": "object"}, 2)
    second = build_request_prompt_hashes("stable rules", "dynamic two", "targets two", {"type": "object"}, 3)

    assert first["stable_prefix_hash"] == second["stable_prefix_hash"]
    assert first["dynamic_tail_hash"] != second["dynamic_tail_hash"]
    assert first["schema_hash"] == second["schema_hash"]
    assert first["target_count"] == 2
    assert all("dynamic one" not in str(value) for value in first.values())


def test_reasoning_telemetry_writer_keeps_bounded_jsonl_history(tmp_path):
    writer = ReasoningTelemetryWriter(tmp_path, "run-1", max_records=2, max_bytes=10000)

    writer.write({"request_index": 1, "reasoning_text": "first"})
    writer.write({"request_index": 2, "reasoning_text": "second"})
    path = writer.write({"request_index": 3, "reasoning_text": "third"})

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [record["request_index"] for record in records] == [2, 3]
    assert records[-1]["reasoning_text"] == "third"


def test_reasoning_telemetry_writer_caps_large_reasoning_text(tmp_path):
    writer = ReasoningTelemetryWriter(tmp_path, "run-2", max_records=2, max_bytes=280)

    path = writer.write({"request_index": 1, "reasoning_text": "x" * 1000})

    record = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
    assert len(record["reasoning_text"]) < 1000
    assert record["reasoning_text_truncated"] is True


def test_request_telemetry_writer_persists_sanitized_bounded_records(tmp_path):
    writer = RequestTelemetryWriter(tmp_path, "run-3", max_records=2, max_bytes=10000)

    writer.write({"request_index": 1, "stable_prefix_hash": "a", "input_tokens": 10})
    writer.write({"request_index": 2, "stable_prefix_hash": "a", "input_tokens": 11})
    path = writer.write({"request_index": 3, "stable_prefix_hash": "a", "input_tokens": 12})

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [record["request_index"] for record in records] == [2, 3]
    assert all("prompt" not in record for record in records)
