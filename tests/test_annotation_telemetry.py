import json

from annotation_telemetry import ReasoningTelemetryWriter


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
