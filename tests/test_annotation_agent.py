import re
from contextlib import contextmanager

import pytest

import llm

from annotation_agent import (
    AnnotationAgentError,
    apply_review_patches,
    build_review_windows,
    estimate_chunk_output_budget,
    grow_chunk_output_budget,
    run_annotation_agent,
)
from annotation_protocol import validate_review_patches
from annotation_chunks import assign_annotation_ids
from annotation_memory import AnnotationCheckpointStore, build_run_fingerprint


FIELDS = ("face", "emo", "act", "fx", "se", "bg", "bg_request", "place", "bgfx", "trans", "shot")


def test_chunk_output_budget_scales_with_wire_shape_and_reasoning_mode():
    compact = estimate_chunk_output_budget(
        20, compact=True, reasoning_mode="balanced", maximum=384_000,
    )
    full = estimate_chunk_output_budget(
        20, compact=False, reasoning_mode="balanced", maximum=384_000,
    )
    deep = estimate_chunk_output_budget(
        20, compact=True, reasoning_mode="deep", maximum=384_000,
    )

    assert 64_000 < compact < full
    assert full < deep < 160_000


def test_chunk_output_budget_respects_ceiling_and_can_grow_to_auto_ceiling():
    assert estimate_chunk_output_budget(
        20, compact=False, reasoning_mode="balanced", maximum=16_000,
    ) == 16_000
    assert grow_chunk_output_budget(16_000, 384_000) == 32_000
    assert grow_chunk_output_budget(256_000, 384_000) == 384_000
    assert grow_chunk_output_budget(384_000, 384_000) is None


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
    model_activity=None, separator_at=None, **agent_options,
):
    items = make_items(count, separator_at=separator_at)
    constraints = {
        "ok_bg": {"BG_Street"}, "confirmed_bg": set(),
        "faces_by_id": {"kei": {"00"}}, "sym2cn": {},
        "ok_emo": set(), "ok_act": set(), "ok_se": set(),
        "ok_shot": {"凯伊"},
    }
    story_type = str(agent_options.get("story_type") or "auto")
    fingerprint = build_run_fingerprint(
        "\n".join(item.get("raw", "") for item in items), {"凯伊": {"id": "kei"}},
        {"bg": ["BG_Street"]}, "v1", 1, "v1",
        {"provider": "fake", "model": "fake", "max_tokens": 16000},
        story_type=story_type, director_version="stateful-v1",
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


def test_compact_agent_accepts_a_fully_sparse_noop_response(tmp_path):
    class SparseProvider:
        name = "sparse"
        model = "sparse"
        supports_compact_annotation = True

        def __init__(self):
            self.calls = 0

        def complete_json(self, _static, _volatile, _user, _schema):
            self.calls += 1
            return {"lines": [], "state_delta": {}, "memory_events": []}

    provider = SparseProvider()
    result = fixture(tmp_path, provider, count=35)

    assert provider.calls >= 1
    assert len(result["rows_by_id"]) == 35
    assert all(not row.get("face") and not row.get("emo") for row in result["rows_by_id"].values())


def test_agent_persists_line_focus_and_continuity_without_overwriting_visible_snapshot(tmp_path):
    class DirectorProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            response = super().complete_json(static, volatile, user, schema)
            if self.calls == 1:
                response["lines"][-1]["fx"] = "通讯"
                response["lines"][-1]["direction"] = {
                    "scene_type": "bond",
                    "focus_kind": "listener",
                    "focus_character": "凯伊",
                    "visible_characters": [],
                    "relation_distance": "approaching",
                    "emotion_phase": "waiting",
                    "continuity": {"fx": "start"},
                }
            return response

    provider = DirectorProvider()
    result = fixture(tmp_path, provider, count=70, story_type="bond")

    assert '"scene_type":"bond"' in provider.requests[0]["volatile"]
    assert result["memory"]["direction"]["focus"] == {
        "kind": "listener", "character": "凯伊",
    }
    assert result["memory"]["direction"]["continuity"]["fx"] == "通讯"
    assert result["memory"]["direction"]["visible_characters"] == ["凯伊"]
    assert '"character":"凯伊"' in provider.requests[1]["volatile"]

    checkpoint_path = next(tmp_path.rglob("checkpoint.json"))
    checkpoint = AnnotationCheckpointStore(tmp_path).load(checkpoint_path.parent.name)
    assert checkpoint["schema_version"] == 2
    assert checkpoint["director_plan"]["story_type"] == "bond"
    assert checkpoint["memory"]["story"]["type"] == "bond"


def test_agent_memory_ignores_resource_values_rejected_by_final_application(tmp_path):
    class InvalidResourceProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            response = super().complete_json(static, volatile, user, schema)
            if self.calls == 1:
                response["lines"][-1].update({
                    "face": "99", "emo": "missing-emo", "act": "missing-act",
                    "fx": "missing-fx", "se": "missing-se", "bg": "missing-bg",
                    "direction": {"continuity": {"fx": "start"}},
                })
            return response

    provider = InvalidResourceProvider()
    result = fixture(tmp_path, provider, count=70)
    direction = result["memory"]["direction"]

    assert direction["last_faces"] == {}
    assert direction["recent_emoticons"] == []
    assert direction["recent_actions"] == []
    assert direction["recent_sounds"] == []
    assert "fx" not in direction["continuity"]
    assert all("missing-" not in request["volatile"] for request in provider.requests[1:])


def test_partial_director_intent_does_not_reset_prior_focus(tmp_path):
    character = make_items(1)[0]["who"]

    class PartialDirectorProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            response = super().complete_json(static, volatile, user, schema)
            response["lines"][-2]["direction"] = {
                "focus_kind": "listener",
                "focus_character": character,
            }
            response["lines"][-1]["direction"] = {"scene_type": "bond"}
            return response

    result = fixture(tmp_path, PartialDirectorProvider(), count=10, story_type="bond")

    assert result["memory"]["direction"]["focus"] == {
        "kind": "listener", "character": character,
    }
    assert result["memory"]["scene"]["scene_type"] == "bond"


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


def test_agent_reports_warm_cache_failed_cost_and_unit_efficiency(tmp_path):
    class CostProvider(RecordingProvider):
        def __init__(self):
            super().__init__()
            self.request_records = []
            self.stats = {
                "in": 0, "out": 0, "cache_read": 0, "cache_miss": 0,
                "cache_write": 0, "cache_reports": 0, "calls": 0,
            }

        def complete_json(self, static, volatile, user, schema):
            response = super().complete_json(static, volatile, user, schema)
            cache_read = 0 if self.calls == 1 else 80
            uncached = 100 if self.calls == 1 else 20
            cache_write = 100 if self.calls == 1 else 0
            self.stats["in"] += 100
            self.stats["out"] += 10
            self.stats["cache_read"] += cache_read
            self.stats["cache_miss"] += uncached
            self.stats["cache_write"] += cache_write
            self.stats["cache_reports"] += 1
            self.stats["calls"] += 1
            self.request_records.append({
                "request_index": self.calls,
                "input_tokens": 100,
                "cache_read_tokens": cache_read,
                "uncached_input_tokens": uncached,
                "cache_write_tokens": cache_write,
                "output_tokens": 10,
            })
            if self.calls == 1:
                response["state_delta"] = {"positions": []}
            return response

    result = fixture(
        tmp_path, CostProvider(), count=40, separator_at=20,
        target=20, soft_limit=24, hard_limit=30,
    )
    metrics = result["metrics"]

    assert metrics["requests"] == 3
    assert metrics["cache_write_tokens"] == 100
    assert metrics["cache_hit_rate"] == pytest.approx(160 / 300)
    assert metrics["warm_cache_read_tokens"] == 160
    assert metrics["warm_uncached_input_tokens"] == 40
    assert metrics["warm_cache_hit_rate"] == pytest.approx(0.8)
    assert metrics["completed_targets"] == 40
    assert metrics["input_tokens_per_completed_target"] == pytest.approx(7.5)
    assert metrics["uncached_input_tokens_per_completed_target"] == pytest.approx(3.5)
    assert metrics["failed_request_count"] == 1
    assert metrics["failed_request_input_tokens"] == 100
    assert metrics["failed_request_output_tokens"] == 10
    assert metrics["stable_prefix_consistent"] is True
    assert metrics["request_records"][0]["outcome"] == "failed"
    assert metrics["request_records"][0]["error_code"] == "invalid_state_delta"
    assert all(record["outcome"] == "succeeded" for record in metrics["request_records"][1:])


def test_cache_read_without_uncached_usage_does_not_invent_a_hit_rate(tmp_path):
    class ReadOnlyCacheProvider(RecordingProvider):
        def __init__(self):
            super().__init__()
            self.request_records = []
            self.stats = {
                "in": 0, "out": 0, "cache_read": 0, "cache_miss": 0,
                "cache_write": 0, "cache_reports": 0, "calls": 0,
            }

        def complete_json(self, static, volatile, user, schema):
            response = super().complete_json(static, volatile, user, schema)
            self.stats["in"] += 20
            self.stats["out"] += 5
            self.stats["cache_read"] += 80
            self.stats["cache_reports"] += 1
            self.stats["calls"] += 1
            self.request_records.append({
                "request_index": self.calls,
                "input_tokens": 20,
                "cache_read_tokens": 80,
                "cache_write_tokens": 0,
                "output_tokens": 5,
            })
            return response

    result = fixture(
        tmp_path, ReadOnlyCacheProvider(), count=40, separator_at=20,
        target=20, soft_limit=24, hard_limit=30,
    )
    metrics = result["metrics"]

    assert metrics["cache_reported"] is True
    assert metrics["cache_read_tokens"] == 160
    assert metrics["uncached_input_tokens"] is None
    assert metrics["cache_hit_rate"] is None
    assert metrics["warm_cache_read_tokens"] == 80
    assert metrics["warm_uncached_input_tokens"] is None
    assert metrics["warm_cache_hit_rate"] is None


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
    assert provider.calls == 2
    assert result["completed_chunks"] == 1
    assert len(result["memory"]["progress"]["completed_target_ids"]) == 25
    assert result["metrics"]["retries"] == 1
    assert result["metrics"]["subdivisions"] == 0


def test_transient_transport_errors_retry_without_subdividing(tmp_path):
    class TransientProvider(RecordingProvider):
        def __init__(self):
            super().__init__()
            self.cfg = {"transport_retry_delay": 0}

        def complete_json(self, static, volatile, user, schema):
            if self.calls < 2:
                self.calls += 1
                raise llm.ModelServiceUnavailableError("temporary gateway failure")
            return super().complete_json(static, volatile, user, schema)

    events = []
    provider = TransientProvider()
    result = fixture(
        tmp_path, provider, count=25,
        model_activity=lambda event: events.append(event),
    )

    assert provider.calls == 3
    assert result["metrics"]["transport_retries"] == 2
    assert result["metrics"]["subdivisions"] == 0
    retry_events = [event for event in events if event.get("state") == "retrying"]
    assert [event["transport_attempt"] for event in retry_events] == [1, 2]


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


def test_reasoning_only_empty_response_retries_without_lowering_effort(tmp_path):
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

    assert provider.modes == ["deep", "deep"]
    assert provider.cfg["reasoning_mode"] == "deep"
    assert result["metrics"]["retries"] == 1


def test_reasoning_capacity_increases_budget_without_disabling_thinking(tmp_path):
    class ReasoningCapacityProvider(RecordingProvider):
        supports_compact_annotation = False

        def __init__(self):
            super().__init__()
            self.cfg = {"reasoning_mode": "balanced"}
            self.modes = []
            self.budgets = []
            self.request_records = []

        @contextmanager
        def temporary_output_budget(self, maximum):
            self.budgets.append(maximum)
            yield

        def complete_json(self, static, volatile, user, schema):
            self.modes.append(self.cfg["reasoning_mode"])
            if self.calls == 0:
                self.calls += 1
                self.request_records.append({
                    "finish_reason": "length", "reasoning_tokens": 1875,
                    "reasoning_chars": 7000, "content_chars": 0,
                })
                raise llm.OutputCapacityError("reasoning exhausted output budget")
            return super().complete_json(static, volatile, user, schema)

    provider = ReasoningCapacityProvider()
    result = fixture(
        tmp_path, provider, count=10,
        reasoning_mode="balanced", annotation_max_tokens=384_000,
    )

    assert provider.modes == ["balanced", "balanced"]
    assert provider.budgets == [67_500, 135_000]
    assert provider.cfg["reasoning_mode"] == "balanced"
    assert result["metrics"]["retries"] == 1
    assert result["metrics"]["subdivisions"] == 0
    assert result["metrics"]["chunk_adaptations"] == []


def test_reasoning_capacity_at_ceiling_subdivides_without_disabling_thinking(tmp_path):
    class ReasoningCapacityProvider(RecordingProvider):
        supports_compact_annotation = False

        def __init__(self):
            super().__init__()
            self.cfg = {"reasoning_mode": "balanced"}
            self.modes = []
            self.request_records = []

        def complete_json(self, static, volatile, user, schema):
            self.modes.append(self.cfg["reasoning_mode"])
            ids = re.findall(r"\[TARGET ([^\]]+)\]", user)
            if len(ids) > 5:
                self.calls += 1
                self.request_records.append({
                    "finish_reason": "length", "reasoning_tokens": 16_000,
                    "reasoning_chars": 40_000, "content_chars": 0,
                })
                raise llm.OutputCapacityError("reasoning exhausted output budget")
            return super().complete_json(static, volatile, user, schema)

    provider = ReasoningCapacityProvider()
    result = fixture(
        tmp_path, provider, count=10,
        reasoning_mode="balanced", annotation_max_tokens=16_000,
    )

    assert all(mode == "balanced" for mode in provider.modes)
    assert result["metrics"]["retries"] == 0
    assert result["metrics"]["subdivisions"] == 1


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

    assert provider.modes == ["deep", "deep"]
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


def test_resume_discards_checkpoint_schema_older_than_two(tmp_path):
    fixture(tmp_path, RecordingProvider(), count=70)
    checkpoint_path = next(tmp_path.rglob("checkpoint.json"))
    store = AnnotationCheckpointStore(tmp_path)
    saved = store.load(checkpoint_path.parent.name)
    saved["schema_version"] = 1
    store.commit(checkpoint_path.parent.name, saved)

    provider = RecordingProvider()
    result = fixture(tmp_path, provider, count=70)

    assert provider.calls == 2
    assert result["resumed_chunks"] == 0


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


def test_cancellation_quarantines_the_inflight_chunk_result(tmp_path):
    provider = RecordingProvider()
    result = fixture(tmp_path, provider, count=70, cancelled=lambda: provider.calls >= 1)
    assert result["cancelled"] is True
    assert provider.calls == 1
    assert result["memory"]["progress"]["completed_chunks"] == []
    assert result["completed_targets"] == 0
    assert result["pending_targets"] == 70


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
    assert "上次响应无效：invalid_state_delta" in provider.requests[1]["user"]
    assert "保持相同 TARGET" in provider.requests[1]["user"]


def test_corrected_protocol_error_does_not_shrink_the_next_scene(tmp_path):
    class CorrectingProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            response = super().complete_json(static, volatile, user, schema)
            if self.calls == 1:
                response["state_delta"] = {"positions": []}
            return response

    provider = CorrectingProvider()
    result = fixture(
        tmp_path, provider, count=40, separator_at=20,
        target=20, soft_limit=24, hard_limit=30,
    )

    assert result["metrics"]["retries"] == 1
    assert [len(request["target_ids"]) for request in provider.requests] == [20, 20, 20]
    assert not result["metrics"]["chunk_adaptations"]


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


def test_capacity_remainder_does_not_lower_the_learned_safe_limit(tmp_path):
    class TenLineProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            ids = re.findall(r"\[TARGET ([^\]]+)\]", user)
            if len(ids) > 10:
                self.calls += 1
                self.requests.append({"target_ids": ids, "user": user, "volatile": volatile})
                raise llm.OutputCapacityError("finish_reason=length")
            return super().complete_json(static, volatile, user, schema)

    provider = TenLineProvider()
    result = fixture(
        tmp_path,
        provider,
        count=45,
        separator_at=25,
        target=25,
        soft_limit=30,
        hard_limit=40,
    )

    assert result["completed_targets"] == 45
    assert [len(request["target_ids"]) for request in provider.requests] == [
        25, 20, 10, 10, 5, 10, 10,
    ]


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
    assert result["total_targets"] == 25
    assert result["completed_targets"] == 0
    assert result["pending_targets"] == 25
    assert result["pending_start_line"] == 1
    assert result["pending_end_line"] == 25
    assert any(item["code"] == "request_deadline" for item in result["diagnostics"])

    checkpoint_path = next(tmp_path.rglob("checkpoint.json"))
    checkpoint = AnnotationCheckpointStore(tmp_path).load(checkpoint_path.parent.name)
    assert checkpoint["memory"]["progress"]["resume_target_limit"] == 12


def test_resume_after_deadline_uses_smaller_target_batches(tmp_path):
    class DeadlineProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            self.requests.append({
                "target_ids": re.findall(r"\[TARGET ([^\]]+)\]", user),
            })
            raise llm.RequestDeadlineError("deadline")

    first_provider = DeadlineProvider()
    first = fixture(tmp_path, first_provider, count=25)
    assert first["timed_out"] is True
    assert len(first_provider.requests[0]["target_ids"]) == 25

    resumed_provider = RecordingProvider()
    resumed = fixture(tmp_path, resumed_provider, count=25)

    assert resumed["timed_out"] is False
    assert resumed["completed_targets"] == 25
    assert resumed["pending_targets"] == 0
    assert resumed_provider.requests
    assert max(len(call["target_ids"]) for call in resumed_provider.requests) <= 12


def test_resume_after_deadline_emits_model_activity_before_provider_call(tmp_path):
    class DeadlineProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            self.requests.append({
                "target_ids": re.findall(r"\[TARGET ([^\]]+)\]", user),
            })
            raise llm.RequestDeadlineError("deadline")

    first = fixture(tmp_path, DeadlineProvider(), count=25)
    assert first["timed_out"] is True

    events = []
    provider = RecordingProvider()
    resumed = fixture(tmp_path, provider, count=25, model_activity=events.append)

    assert resumed["completed_targets"] == 25
    assert provider.requests
    subdivision = next(event for event in events if event["state"] == "subdividing")
    assert subdivision["reason"] == "learned_safe_limit"
    assert subdivision["chunk_current"] == 1
    assert subdivision["chunk_total"] == 1


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
