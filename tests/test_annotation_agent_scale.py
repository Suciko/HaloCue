import re

import pytest

from annotation_agent import AnnotationAgentError, run_annotation_agent
from annotation_chunks import assign_annotation_ids
from annotation_memory import AnnotationCheckpointStore, build_run_fingerprint


class SizedProvider:
    name = "fake"
    model = "scale"

    def __init__(self, interrupt_after=None):
        self.calls = 0
        self.interrupt_after = interrupt_after
        self.target_sizes = []
        self.past_sizes = []
        self.future_sizes = []
        self.event_sizes = []

    def complete_json(self, _static, volatile, user, _schema):
        self.calls += 1
        if self.interrupt_after is not None and self.calls > self.interrupt_after:
            raise RuntimeError("interrupted")
        targets = re.findall(r"\[TARGET ([^\]]+)\]", user)
        self.target_sizes.append(len(targets))
        self.past_sizes.append(len(re.findall(r"\[PAST_CONTEXT ", user)))
        self.future_sizes.append(len(re.findall(r"\[FUTURE_CONTEXT ", user)))
        self.event_sizes.append(min(8, volatile.count('"id":"event-')))
        fingerprints = dict(re.findall(r"\[TARGET ([^\]]+)\].*?fingerprint=([0-9a-f]+)", user))
        return {
            "lines": [{
                "source_id": source_id, "text_fingerprint": fingerprints[source_id],
                "face": "", "emo": "", "act": "", "fx": "", "se": "", "bg": "",
                "bg_request": "", "place": "", "shake": False, "bgfx": "", "trans": "",
                "move": 0, "shot": "",
            } for source_id in targets],
            "state_delta": {}, "memory_events": [],
        }


def run_script(tmp_path, provider, count):
    items = assign_annotation_ids([{
        "kind": "line", "line_no": index + 1, "split_index": 0,
        "who": "凯伊", "text": f"第{index + 1}句。", "raw": f"凯伊: 第{index + 1}句。",
    } for index in range(count)])
    fingerprint = build_run_fingerprint(
        "\n".join(item["raw"] for item in items), {"凯伊": {"id": "kei"}},
        {}, "v1", 1, "v1", {"provider": "fake", "model": "scale", "max_tokens": 16000},
    )
    return run_annotation_agent(
        items, provider=provider, static_system="rules", cast={"凯伊": {"id": "kei", "portrait": True}},
        constraints={"ok_bg": set(), "faces_by_id": {"kei": set()}}, usage_chain=[],
        checkpoint_store=AnnotationCheckpointStore(tmp_path), run_fingerprint=fingerprint,
    )


def test_240_line_script_has_exactly_one_validated_result_per_target(tmp_path):
    provider = SizedProvider()
    result = run_script(tmp_path, provider, 240)
    ids = [item["annotation_id"] for item in result["items"] if item["kind"] == "line"]
    assert len(ids) == 240
    assert len(set(ids)) == 240
    assert set(result["memory"]["progress"]["completed_target_ids"]) == set(ids)
    assert max(provider.target_sizes) <= 60
    assert 4 <= result["metrics"]["requests"] <= 6
    assert result["metrics"]["retries"] == 0
    assert result["metrics"]["input_tokens"] is None
    assert result["metrics"]["elapsed_ms"] >= 0


def test_3000_line_context_is_bounded_and_resume_skips_prefix(tmp_path):
    first = SizedProvider(interrupt_after=25)
    with pytest.raises(AnnotationAgentError):
        run_script(tmp_path, first, 3000)
    resumed = SizedProvider()
    result = run_script(tmp_path, resumed, 3000)
    assert result["resumed_chunks"] == 25
    assert max(resumed.target_sizes) <= 60
    assert max(resumed.past_sizes) <= 15
    assert max(resumed.future_sizes) <= 10
    assert max(resumed.event_sizes) <= 8


def test_run_local_successes_grow_only_future_scene_chunks(tmp_path):
    class EfficientProvider(SizedProvider):
        def __init__(self):
            super().__init__()
            self.request_records = []

        def complete_json(self, *args):
            result = super().complete_json(*args)
            self.request_records.append({"reasoning_chars": 10, "content_chars": 100})
            return result

    provider = EfficientProvider()
    items = []
    for scene in range(2):
        if scene:
            items.append({"kind": "other", "raw": "---"})
        items.extend({
            "kind": "line", "line_no": scene * 80 + index + 1,
            "split_index": 0, "who": "Kai", "text": f"line {index + 1}",
            "raw": f"Kai: line {index + 1}",
        } for index in range(80))
    assign_annotation_ids(items)
    fingerprint = build_run_fingerprint(
        "\n".join(item.get("raw", "") for item in items),
        {"Kai": {"id": "kai"}}, {}, "v1", 1, "v1",
        {"provider": "fake", "model": "scale", "max_tokens": 16000},
    )

    result = run_annotation_agent(
        items, provider=provider, static_system="rules",
        cast={"Kai": {"id": "kai", "portrait": True}},
        constraints={"ok_bg": set(), "faces_by_id": {"kai": set()}},
        usage_chain=[], checkpoint_store=AnnotationCheckpointStore(tmp_path),
        run_fingerprint=fingerprint, context_window_tokens=200_000,
    )

    assert provider.target_sizes == [40, 40, 45, 35]
    assert result["metrics"]["initial_chunk_limits"]["target"] == 40
    assert any(
        decision["reason"] == "two_efficient_successes"
        for decision in result["metrics"]["chunk_adaptations"]
    )


def test_resume_uses_completed_target_ids_when_adaptive_chunk_boundaries_change(tmp_path):
    class AdaptiveInterruptProvider(SizedProvider):
        def __init__(self, interrupt_after=None):
            super().__init__(interrupt_after=interrupt_after)
            self.request_records = []

        def complete_json(self, *args):
            result = super().complete_json(*args)
            self.request_records.append({"reasoning_chars": 700, "content_chars": 100})
            return result

    items = []
    for scene, count in ((0, 20), (1, 80)):
        if scene:
            items.append({"kind": "other", "raw": "---"})
        items.extend({
            "kind": "line", "line_no": scene * 100 + index + 1,
            "split_index": 0, "who": "Kai", "text": f"line {scene}-{index}",
            "raw": f"Kai: line {scene}-{index}",
        } for index in range(count))
    assign_annotation_ids(items)
    fingerprint = build_run_fingerprint(
        "\n".join(item.get("raw", "") for item in items),
        {"Kai": {"id": "kai"}}, {}, "v1", 1, "v1",
        {"provider": "fake", "model": "scale", "max_tokens": 16000},
    )

    def run(provider):
        return run_annotation_agent(
            items, provider=provider, static_system="rules",
            cast={"Kai": {"id": "kai", "portrait": True}},
            constraints={"ok_bg": set(), "faces_by_id": {"kai": set()}},
            usage_chain=[], checkpoint_store=AnnotationCheckpointStore(tmp_path),
            run_fingerprint=fingerprint,
        )

    with pytest.raises(AnnotationAgentError):
        run(AdaptiveInterruptProvider(interrupt_after=2))
    result = run(AdaptiveInterruptProvider())

    expected = {item["annotation_id"] for item in items if item.get("kind") == "line"}
    assert set(result["rows_by_id"]) == expected
