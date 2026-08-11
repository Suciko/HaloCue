import copy
import re

import pytest

import llm

from annotation_agent import (
    AnnotationAgentError,
    apply_review_patches,
    build_review_windows,
    run_annotation_agent,
)
from annotation_protocol import validate_review_patches
from annotation_chunks import assign_annotation_ids
from annotation_memory import AnnotationCheckpointStore, build_run_fingerprint


FIELDS = ("face", "emo", "act", "fx", "se", "bg", "bg_request", "place", "bgfx", "trans", "shot")


def make_items(count, separator_at=None):
    items = []
    for index in range(count):
        if separator_at is not None and index == separator_at:
            items.append({"kind": "other", "raw": "---"})
        items.append({
            "kind": "line", "line_no": index + 1, "split_index": 0,
            "who": "凯伊", "text": f"第{index + 1}句。", "raw": f"凯伊: 第{index + 1}句。",
        })
    return assign_annotation_ids(items)


def empty_row(source_id, fingerprint):
    row = {name: "" for name in FIELDS}
    row.update({"source_id": source_id, "text_fingerprint": fingerprint, "shake": False, "move": 0})
    return row


class RecordingProvider:
    name = "fake"
    model = "fake"

    def __init__(self, fail_after=None, omit_last_calls=0):
        self.fail_after = fail_after
        self.omit_last_calls = omit_last_calls
        self.calls = 0
        self.requests = []

    def complete_json(self, static, volatile, user, schema):
        self.calls += 1
        if self.fail_after is not None and self.calls > self.fail_after:
            raise RuntimeError("forced failure")
        ids = re.findall(r"\[TARGET ([^\]]+)\]", user)
        fingerprints = dict(re.findall(r"\[TARGET ([^\]]+)\].*?fingerprint=([0-9a-f]+)", user))
        self.requests.append({"volatile": volatile, "user": user, "target_ids": ids})
        rows = [empty_row(source_id, fingerprints[source_id]) for source_id in ids]
        if self.calls <= self.omit_last_calls and rows:
            rows.pop()
        delta = {}
        events = []
        if self.calls == 1 and rows:
            delta = {"background": "BG_Street", "visible_characters": ["凯伊"]}
            first_id = ids[0]
            text_match = re.search(rf"\[TARGET {re.escape(first_id)}\] [^:]+: ([^|]+) \|", user)
            evidence = text_match.group(1).strip() if text_match else ""
            events = [{
                "kind": "relationship_callback", "participants": ["凯伊"],
                "keywords": ["第1句"], "summary": "记住第一句", "source_ids": [first_id],
                "evidence": evidence, "importance": .9, "status": "open",
            }]
        return {"lines": rows, "state_delta": delta, "memory_events": events}

    def report(self):
        return f"fake calls={self.calls}"


def fixture(
    tmp_path, provider, count=70, cancelled=None, progress=None,
    model_activity=None, **agent_options,
):
    items = make_items(count)
    constraints = {"ok_bg": {"BG_Street"}, "faces_by_id": {"kei": {"00"}}}
    fingerprint = build_run_fingerprint(
        "\n".join(item.get("raw", "") for item in items), {"凯伊": {"id": "kei"}},
        {"bg": ["BG_Street"]}, "v1", 1, "v1",
        {"provider": "fake", "model": "fake", "max_tokens": 16000},
    )
    return run_annotation_agent(
        items, provider=provider, static_system="rules", cast={"凯伊": {"id": "kei", "portrait": True}},
        constraints=constraints, usage_chain=[], checkpoint_store=AnnotationCheckpointStore(tmp_path),
        run_fingerprint=fingerprint, cancelled=cancelled, progress=progress,
        model_activity=model_activity,
        **agent_options,
    )


def test_agent_carries_state_and_event_into_next_chunk(tmp_path):
    provider = RecordingProvider()
    result = fixture(tmp_path, provider, count=70)
    assert provider.calls == 2
    assert "BG_Street" in provider.requests[1]["volatile"]
    assert "记住第一句" in provider.requests[1]["volatile"]
    assert result["completed_chunks"] == 2
    assert len(result["rows_by_id"]) == 70


def test_agent_attaches_request_telemetry_to_chunk_without_prompt_text(tmp_path):
    class TelemetryProvider(RecordingProvider):
        def __init__(self):
            super().__init__()
            self.request_records = []

        def complete_json(self, static, volatile, user, schema):
            result = super().complete_json(static, volatile, user, schema)
            self.request_records.append({
                "request_index": self.calls,
                "input_tokens": 100,
                "cache_read_tokens": 70,
                "uncached_input_tokens": 30,
                "output_tokens": 9,
                "reasoning_tokens": 7,
                "reasoning_chars": 5,
                "content_chars": 2,
                "finish_reason": "stop",
            })
            return result

    result = fixture(tmp_path, TelemetryProvider(), count=10)

    records = result["metrics"]["request_records"]
    assert records[0]["scene_id"] == "scene-1"
    assert records[0]["chunk_id"] == "scene-1-chunk-1"
    assert records[0]["request_index"] == 1
    assert records[0]["retry_count"] == 0
    assert records[0]["subdivision_count"] == 0
    assert records[0]["stable_prefix_hash"]
    assert records[0]["dynamic_tail_hash"]
    assert records[0]["schema_hash"]
    assert records[0]["target_count"] == 10
    assert records[0]["adaptation_reason"] == "initial"
    assert "user" not in records[0]
    assert "volatile" not in records[0]


def test_agent_writes_reasoning_diagnostics_outside_checkpoint(tmp_path):
    class ReasoningProvider(RecordingProvider):
        def __init__(self):
            super().__init__()
            self.request_records = []
            self.reasoning_records = []

        def complete_json(self, static, volatile, user, schema):
            result = super().complete_json(static, volatile, user, schema)
            self.request_records.append({"request_index": self.calls})
            self.reasoning_records.append({
                "request_index": self.calls,
                "model": self.model,
                "reasoning_text": "重复检查 TARGET 格式",
                "reasoning_chars": 10,
                "content_chars": 2,
                "finish_reason": "stop",
            })
            return result

    provider = ReasoningProvider()
    fixture(tmp_path, provider, count=10)

    files = list((tmp_path / "annotation-telemetry").rglob("reasoning.jsonl"))
    assert len(files) == 1
    assert "重复检查 TARGET 格式" in files[0].read_text(encoding="utf-8")
    assert "scene-1-chunk-1" in files[0].read_text(encoding="utf-8")
    assert not list((tmp_path / "annotation-checkpoints").rglob("*reasoning*"))


def test_reasoning_cursor_is_independent_from_request_record_cursor(tmp_path):
    class LateReasoningProvider(RecordingProvider):
        def __init__(self):
            super().__init__()
            self.request_records = []
            self.reasoning_records = []

        def complete_json(self, static, volatile, user, schema):
            result = super().complete_json(static, volatile, user, schema)
            self.request_records.append({"request_index": self.calls})
            if self.calls == 2:
                self.reasoning_records.append({
                    "request_index": 2, "reasoning_text": "late reasoning",
                    "reasoning_chars": 14, "content_chars": 2, "finish_reason": "stop",
                })
            return result

    fixture(tmp_path, LateReasoningProvider(), count=70)

    files = list((tmp_path / "annotation-telemetry").rglob("reasoning.jsonl"))
    assert len(files) == 1
    assert "late reasoning" in files[0].read_text(encoding="utf-8")


def test_structural_failure_retries_without_partial_commit(tmp_path):
    provider = RecordingProvider(omit_last_calls=1)
    result = fixture(tmp_path, provider, count=25)
    assert provider.calls == 3
    assert result["completed_chunks"] == 2
    assert len(result["memory"]["progress"]["completed_target_ids"]) == 25
    assert result["metrics"]["retries"] == 0
    assert result["metrics"]["subdivisions"] == 1


def test_provider_json_failure_subdivides_chunk_instead_of_aborting(tmp_path):
    class LengthLimitedProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            ids = re.findall(r"\[TARGET ([^\]]+)\]", user)
            if len(ids) > 20:
                self.calls += 1
                raise llm.OutputCapacityError("finish_reason=length; response was truncated")
            return super().complete_json(static, volatile, user, schema)

    provider = LengthLimitedProvider()

    result = fixture(tmp_path, provider, count=25)

    assert result["completed_chunks"] == 2
    assert len(result["rows_by_id"]) == 25
    assert provider.calls == 3
    assert any(diagnostic["code"] == "chunk_subdivided" for diagnostic in result["diagnostics"])


def test_resume_after_subdivision_requests_only_unfinished_targets(tmp_path):
    class InterruptedSubdivisionProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            ids = re.findall(r"\[TARGET ([^\]]+)\]", user)
            if len(ids) > 20:
                self.calls += 1
                raise llm.OutputCapacityError("finish_reason=length")
            if self.calls >= 2:
                self.calls += 1
                raise RuntimeError("interrupted")
            return super().complete_json(static, volatile, user, schema)

    with pytest.raises(AnnotationAgentError):
        fixture(tmp_path, InterruptedSubdivisionProvider(), count=25)

    resumed = RecordingProvider()
    result = fixture(tmp_path, resumed, count=25)

    assert len(resumed.requests) == 1
    assert len(resumed.requests[0]["target_ids"]) == 5
    completed_ids = result["memory"]["progress"]["completed_target_ids"]
    assert len(completed_ids) == len(set(completed_ids)) == 25


def test_empty_stop_response_retries_once_without_partial_commit(tmp_path):
    class EmptyOnceProvider(RecordingProvider):
        def __init__(self):
            super().__init__()
            self.empty = True

        def complete_json(self, static, volatile, user, schema):
            if self.empty:
                self.empty = False
                self.calls += 1
                raise llm.EmptyModelResponseError("empty stop response")
            return super().complete_json(static, volatile, user, schema)

    provider = EmptyOnceProvider()
    result = fixture(tmp_path, provider, count=10)

    assert provider.calls == 2
    assert result["completed_chunks"] == 1
    assert len(result["rows_by_id"]) == 10
    assert result["metrics"]["retries"] == 1


def test_reasoning_only_empty_response_retries_at_lower_effort_then_restores_mode(tmp_path):
    class ReasoningEmptyProvider(RecordingProvider):
        supports_compact_annotation = False

        def __init__(self):
            super().__init__()
            self.cfg = {"reasoning_mode": "deep"}
            self.modes = []

        def complete_json(self, static, volatile, user, schema):
            self.modes.append(self.cfg["reasoning_mode"])
            if self.calls == 0:
                self.calls += 1
                raise llm.EmptyModelResponseError(
                    "empty stop response", finish_reason="stop", reasoning_chars=1200,
                )
            return super().complete_json(static, volatile, user, schema)

    provider = ReasoningEmptyProvider()
    result = fixture(tmp_path, provider, count=10)

    assert provider.modes == ["deep", "balanced"]
    assert provider.cfg["reasoning_mode"] == "deep"
    assert result["metrics"]["retries"] == 1


def test_reasoning_mode_is_restored_when_empty_retry_exhausts(tmp_path):
    class AlwaysReasoningEmptyProvider(RecordingProvider):
        supports_compact_annotation = False

        def __init__(self):
            super().__init__()
            self.cfg = {"reasoning_mode": "deep"}
            self.modes = []

        def complete_json(self, static, volatile, user, schema):
            self.modes.append(self.cfg["reasoning_mode"])
            raise llm.EmptyModelResponseError(
                "empty stop response", finish_reason="stop", reasoning_chars=1200,
            )

    provider = AlwaysReasoningEmptyProvider()
    with pytest.raises(AnnotationAgentError):
        fixture(tmp_path, provider, count=10)

    assert provider.modes == ["deep", "balanced"]
    assert provider.cfg["reasoning_mode"] == "deep"


def test_empty_without_reasoning_does_not_lower_effort(tmp_path):
    class EmptyWithoutReasoningProvider(RecordingProvider):
        supports_compact_annotation = False

        def __init__(self):
            super().__init__()
            self.cfg = {"reasoning_mode": "deep"}
            self.modes = []

        def complete_json(self, static, volatile, user, schema):
            self.modes.append(self.cfg["reasoning_mode"])
            if self.calls == 0:
                self.calls += 1
                raise llm.EmptyModelResponseError(
                    "empty stop response", finish_reason="stop", reasoning_chars=0,
                )
            return super().complete_json(static, volatile, user, schema)

    provider = EmptyWithoutReasoningProvider()
    result = fixture(tmp_path, provider, count=10)

    assert provider.modes == ["deep", "deep"]
    assert result["metrics"]["retries"] == 1


def test_chunk_recovery_progress_explains_retry_and_subdivision(tmp_path):
    class LengthLimitedProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            ids = re.findall(r"\[TARGET ([^\]]+)\]", user)
            if len(ids) > 20:
                self.calls += 1
                raise llm.OutputCapacityError("finish_reason=length")
            return super().complete_json(static, volatile, user, schema)

    events = []
    provider = LengthLimitedProvider()
    result = fixture(tmp_path, provider, count=25, progress=lambda *args: events.append(args))

    assert result["completed_chunks"] == 2
    assert any("自动缩小" in str(event[-1]) for event in events)


def test_subdivision_keeps_user_progress_total_stable(tmp_path):
    class LengthLimitedProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            ids = re.findall(r"\[TARGET ([^\]]+)\]", user)
            if len(ids) > 20:
                self.calls += 1
                raise llm.OutputCapacityError("finish_reason=length")
            return super().complete_json(static, volatile, user, schema)

    events = []
    fixture(
        tmp_path,
        LengthLimitedProvider(),
        count=25,
        progress=lambda *args: events.append(args),
    )

    annotation_events = [event for event in events if event[0] == "annotating"]
    assert {(event[1], event[2]) for event in annotation_events} == {(1, 1)}


def test_large_structured_failure_records_explicit_fallback_chain(tmp_path):
    class FailingLargeProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            ids = re.findall(r"\[TARGET ([^\]]+)\]", user)
            if len(ids) > 20:
                self.calls += 1
                raise llm.OutputCapacityError("response too large")
            return super().complete_json(static, volatile, user, schema)

    provider = FailingLargeProvider()
    result = fixture(tmp_path, provider, count=55)

    limits = [d["maximum"] for d in result["diagnostics"] if d["code"] == "chunk_subdivided"]
    assert limits == [50, 30, 20]


def test_agent_chunk_request_explicitly_uses_source_identity_protocol(tmp_path):
    provider = RecordingProvider()

    fixture(tmp_path, provider, count=2)

    request = provider.requests[0]["user"]
    assert "source_id" in request
    assert "text_fingerprint" in request
    assert "state_delta" in request
    assert "memory_events" in request


def test_failed_later_chunk_keeps_previous_checkpoint(tmp_path):
    provider = RecordingProvider(fail_after=1)
    with pytest.raises(AnnotationAgentError):
        fixture(tmp_path, provider, count=70)
    checkpoints = list(tmp_path.rglob("checkpoint.json"))
    assert len(checkpoints) == 1
    saved = AnnotationCheckpointStore(tmp_path).load(checkpoints[0].parent.name)
    assert saved["memory"]["progress"]["completed_chunks"] == ["scene-1-chunk-1"]


def test_resume_skips_completed_provider_calls(tmp_path):
    first = RecordingProvider(fail_after=1)
    with pytest.raises(AnnotationAgentError):
        fixture(tmp_path, first, count=70)
    resumed = RecordingProvider()
    result = fixture(tmp_path, resumed, count=70)
    assert resumed.calls == 1
    assert result["resumed_chunks"] == 1
    assert len(result["rows_by_id"]) == 70


def test_resume_preserves_dialogue_free_beats_from_completed_chunks(tmp_path):
    class BeatProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            response = super().complete_json(static, volatile, user, schema)
            if self.calls == 1:
                anchor_id = self.requests[-1]["target_ids"][0]
                response["beats"] = [{
                    "anchor_id": anchor_id, "position": "after", "who": "凯伊",
                    "face": "00", "emo": "", "act": "", "wait_ms": 2500,
                    "reason": "listener_reaction",
                }]
            return response

    first = BeatProvider(fail_after=1)
    with pytest.raises(AnnotationAgentError):
        fixture(tmp_path, first, count=70)

    resumed = RecordingProvider()
    result = fixture(tmp_path, resumed, count=70)

    assert len(result["beats"]) == 1
    assert result["beats"][0]["wait_ms"] == 2500
    assert result["beats"][0]["reason"] == "listener_reaction"


def test_cancellation_stops_before_next_call_and_keeps_checkpoint(tmp_path):
    provider = RecordingProvider()
    result = fixture(tmp_path, provider, count=70, cancelled=lambda: provider.calls >= 1)
    assert result["cancelled"] is True
    assert provider.calls == 1
    assert result["memory"]["progress"]["completed_chunks"] == ["scene-1-chunk-1"]


def test_review_windows_include_chunk_boundaries_and_open_events():
    source = make_items(70)
    scenes = [{"scene_id": "scene-1", "target_indices": list(range(70))}]
    events = [{
        "id": "event-name", "kind": "relationship_callback", "participants": ["凯伊"],
        "keywords": ["凯伊酱"], "summary": "凯伊酱称呼", "source_ids": [source[0]["annotation_id"]],
        "evidence": "第1句。", "importance": .9, "status": "open",
    }]
    windows = build_review_windows(source, scenes, events, chunk_size=30)
    assert any(window["kind"] == "chunk_boundary" for window in windows)
    assert any("凯伊酱" in window["context"] for window in windows)


def test_review_patch_cannot_change_dialogue_or_unseen_line():
    source = make_items(2)
    response = {"patches": [
        {"source_id": source[0]["annotation_id"], "field": "text", "before": "原文", "after": "改写", "reason": "润色", "evidence_source_ids": [source[0]["annotation_id"]]},
        {"source_id": "unknown", "field": "face", "before": "01", "after": "03", "reason": "调整", "evidence_source_ids": [source[0]["annotation_id"]]},
    ]}
    assert validate_review_patches(response, source, {}) == []


def test_review_patch_requires_matching_before_value():
    source = make_items(1)
    source[0]["face"] = "01"
    patch = {"source_id": source[0]["annotation_id"], "field": "face", "before": "00", "after": "03", "reason": "情绪变化", "evidence_source_ids": [source[0]["annotation_id"]]}
    updated, diagnostics = apply_review_patches(source, [patch])
    assert updated[0]["face"] == "01"
    assert diagnostics[0]["code"] == "review_before_mismatch"


def test_seventh_chunk_optional_state_null_finishes_without_retry(tmp_path):
    class NullStateProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            response = super().complete_json(static, volatile, user, schema)
            if self.calls == 7:
                response["state_delta"] = {"bgfx": None}
            return response

    provider = NullStateProvider()
    result = fixture(tmp_path, provider, count=301)

    assert result["cancelled"] is False
    assert len(result["rows_by_id"]) == 301
    assert result["metrics"]["retries"] == 0


def test_protocol_error_gets_one_correction_and_never_subdivides(tmp_path):
    class WrongTypeProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            response = super().complete_json(static, volatile, user, schema)
            response["state_delta"] = {"positions": []}
            return response

    provider = WrongTypeProvider()
    with pytest.raises(AnnotationAgentError, match="invalid_state_delta"):
        fixture(tmp_path, provider, count=25)

    assert provider.calls == 2


def test_capacity_success_teaches_remaining_chunks_the_safe_limit(tmp_path):
    class TenLineProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            ids = re.findall(r"\[TARGET ([^\]]+)\]", user)
            if len(ids) > 10:
                self.calls += 1
                self.requests.append({"target_ids": ids, "user": user, "volatile": volatile})
                raise llm.OutputCapacityError("finish_reason=length")
            return super().complete_json(static, volatile, user, schema)

    provider = TenLineProvider()
    result = fixture(tmp_path, provider, count=80)
    successful_sizes = [
        len(row["target_ids"])
        for row in provider.requests
        if len(row["target_ids"]) <= 10
    ]

    assert result["metrics"]["subdivisions"] >= 1
    assert successful_sizes
    assert all(size <= 10 for size in successful_sizes)
    first_safe = next(
        i for i, row in enumerate(provider.requests) if len(row["target_ids"]) <= 10
    )
    assert all(len(row["target_ids"]) <= 10 for row in provider.requests[first_safe:])


def test_reasoning_mode_does_not_change_chunk_capacity(tmp_path):
    speed = RecordingProvider()
    deep = RecordingProvider()

    fixture(tmp_path / "speed", speed, count=80, reasoning_mode="speed")
    fixture(tmp_path / "deep", deep, count=80, reasoning_mode="deep")

    assert [len(request["target_ids"]) for request in speed.requests] == [
        len(request["target_ids"]) for request in deep.requests
    ]


def test_request_deadline_returns_checkpointed_partial_result(tmp_path):
    class DeadlineProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            raise llm.RequestDeadlineError("deadline")

    result = fixture(tmp_path, DeadlineProvider(), count=25)
    assert result["timed_out"] is True
    assert result["completed_chunks"] == 0
    assert result["rows_by_id"] == {}
    assert any(item["code"] == "request_deadline" for item in result["diagnostics"])


def test_model_activity_adds_chunk_context_to_provider_events(tmp_path):
    events = []
    fixture(tmp_path, RecordingProvider(), count=10, model_activity=events.append)

    assert events
    assert events[0]["state"] == "waiting"
    assert events[-1]["state"] == "completed"
    assert events[0]["scene_id"] == "scene-1"
    assert events[0]["chunk_id"] == "scene-1-chunk-1"
    assert events[0]["request_index"] == 1


def test_non_stream_activity_uses_one_request_clock(tmp_path, monkeypatch):
    clock = iter([1000.0, 1000.25])
    monkeypatch.setattr("annotation_agent.time.time", lambda: next(clock))
    events = []

    fixture(tmp_path, RecordingProvider(), count=10, model_activity=events.append)

    waiting, completed = events[0], events[-1]
    assert waiting["request_started_at_ms"] == completed["request_started_at_ms"] == 1000000
    assert completed["elapsed_ms"] == 250


def test_agent_recovery_events_include_request_context(tmp_path):
    class LengthLimitedProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            ids = re.findall(r"\[TARGET ([^\]]+)\]", user)
            if len(ids) > 20:
                self.calls += 1
                raise llm.OutputCapacityError("finish_reason=length")
            return super().complete_json(static, volatile, user, schema)

    events = []
    fixture(tmp_path, LengthLimitedProvider(), count=25, model_activity=events.append)

    recovery = [event for event in events if event["state"] == "subdividing"]
    assert recovery
    assert recovery[0]["scene_id"] == "scene-1"
    assert recovery[0]["chunk_id"] == "scene-1-chunk-1"
    assert recovery[0]["chunk_current"] == recovery[0]["chunk_total"] == 1
    assert recovery[0]["request_index"] == 1


def test_later_protocol_failure_keeps_prior_checkpoint_without_subdivision(tmp_path):
    class FailingSecondChunkProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            response = super().complete_json(static, volatile, user, schema)
            if self.calls >= 2:
                response["state_delta"] = {"positions": []}
            return response

    provider = FailingSecondChunkProvider()
    with pytest.raises(AnnotationAgentError, match="invalid_state_delta"):
        fixture(tmp_path, provider, count=70)

    assert provider.calls == 3
    checkpoints = list(tmp_path.rglob("checkpoint.json"))
    assert len(checkpoints) == 1
    saved = AnnotationCheckpointStore(tmp_path).load(checkpoints[0].parent.name)
    assert saved["memory"]["progress"]["completed_chunks"] == ["scene-1-chunk-1"]


def test_agent_metrics_distinguish_reported_cache_from_missing_telemetry(tmp_path):
    provider = RecordingProvider()
    provider.stats = {
        "in": 100,
        "out": 20,
        "cache_read": 70,
        "cache_miss": 30,
        "cache_write": 0,
        "cache_reports": 1,
        "calls": 0,
    }

    result = fixture(tmp_path, provider, count=10)

    assert result["metrics"]["cache_reported"] is False
    assert result["metrics"]["cache_read_tokens"] is None
    assert result["metrics"]["uncached_input_tokens"] is None
    assert result["metrics"]["actual_model"] == "fake"
