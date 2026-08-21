from pathlib import Path

import json
import pytest

from tools.run_blind_validation import (
    BLIND_LAYOUT_MODE,
    BlindCheckpointProvider,
    RUNTIME_FINGERPRINT_FILES,
    ResponseNeeded,
    build_run_status,
    build_runtime_fingerprint,
)


def test_runtime_fingerprint_covers_shared_prompt_backend_and_compiler():
    fingerprint = build_runtime_fingerprint()

    assert set(fingerprint["files"]) == set(RUNTIME_FINGERPRINT_FILES)
    assert len(fingerprint["sha256"]) == 64
    assert all(len(value) == 64 for value in fingerprint["files"].values())
    assert "tools/run_blind_validation.py" in fingerprint["files"]


def test_blind_runner_uses_the_ai_owned_layout_contract():
    assert BLIND_LAYOUT_MODE == "pure_ai"


def test_runtime_fingerprint_changes_when_a_tracked_file_changes(tmp_path: Path):
    for relative in RUNTIME_FINGERPRINT_FILES:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")
    before = build_runtime_fingerprint(tmp_path)

    (tmp_path / "prompt.py").write_text("changed", encoding="utf-8")
    after = build_runtime_fingerprint(tmp_path)

    assert before["sha256"] != after["sha256"]
    assert before["files"]["prompt.py"] != after["files"]["prompt.py"]


def test_checkpoint_provider_keeps_explicit_model_identity(tmp_path: Path):
    provider = BlindCheckpointProvider(
        tmp_path,
        provider_name="codex-sol-subagent",
        model_name="gpt-5.6-sol",
    )

    assert provider.name == "codex-sol-subagent"
    assert provider.model == "gpt-5.6-sol"
    assert provider.cfg["annotation_max_tokens"] == 128_000


def test_checkpoint_provider_can_refresh_persisted_response_attempts(tmp_path: Path):
    normal = BlindCheckpointProvider(tmp_path)
    refresh = BlindCheckpointProvider(tmp_path, replay_checkpoint_outputs=False)

    assert normal.replay_checkpoint_outputs is True
    assert refresh.replay_checkpoint_outputs is False


def test_run_status_does_not_call_review_artifact_complete():
    status = build_run_status(
        {
            "out": "scene.annotated.txt",
            "model_audit": "scene.model-audit.json",
            "agent": {"needs_review": True},
        },
        {"aap_file": "scene.aap", "quality": {"scripts": 12}},
    )

    assert status["status"] == "needs_review"
    assert status["needs_review"] is True
    assert status["aap_file"] == "scene.aap"


def test_run_status_calls_review_clean_artifact_complete():
    status = build_run_status(
        {"out": "scene.annotated.txt", "agent": {"needs_review": False}},
        {"aap_file": "scene.aap"},
    )

    assert status["status"] == "complete"
    assert status["needs_review"] is False


def test_checkpoint_provider_detects_new_repair_response_without_overwriting_raw_attempt(
    tmp_path: Path,
):
    provider = BlindCheckpointProvider(tmp_path)
    user = "G2_EXECUTION_REPAIR"
    with pytest.raises(ResponseNeeded) as needed:
        provider.complete_json("rules", "context", user, {"type": "object"})

    first_response = {"lines": [{"source_id": "line-1", "face": "00"}]}
    needed.value.response_path.parent.mkdir(parents=True, exist_ok=True)
    needed.value.response_path.write_text(
        json.dumps(first_response, ensure_ascii=False), encoding="utf-8",
    )
    assert provider.complete_json("rules", "context", user, {"type": "object"}) == first_response
    record = provider.request_records[-1]
    saved_output = {"model_attempts": [{
        "phase": "g2_repair",
        "request_fingerprint": record["request_fingerprint"],
        "response_sha256": record["response_sha256"],
    }]}
    first_raw = Path(record["raw_path"])

    assert provider.checkpoint_replay_mode(saved_output) == "reuse"
    legacy_saved = {"model_attempts": [{"phase": "g2_repair", "response": first_response}]}
    assert provider.checkpoint_replay_mode(legacy_saved) == "reuse"
    second_response = {"lines": [{"source_id": "line-1", "face": "05"}]}
    needed.value.response_path.write_text(
        json.dumps(second_response, ensure_ascii=False), encoding="utf-8",
    )
    assert provider.checkpoint_replay_mode(saved_output) == "g2_repair"
    assert provider.checkpoint_replay_mode(legacy_saved) == "g2_repair"
    assert json.loads(first_raw.read_text(encoding="utf-8")) == first_response

    assert provider.complete_json("rules", "context", user, {"type": "object"}) == second_response
    raw_attempts = sorted((tmp_path / "raw-ai").glob("g2-repair-*.raw.json"))
    assert len(raw_attempts) == 2
    assert json.loads(raw_attempts[0].read_text(encoding="utf-8")) == first_response
    assert json.loads(raw_attempts[1].read_text(encoding="utf-8")) == second_response


def test_checkpoint_provider_consumes_immutable_response_attempt_suffix(tmp_path: Path):
    provider = BlindCheckpointProvider(tmp_path)
    user = "G2_EXECUTION_REPAIR"
    with pytest.raises(ResponseNeeded) as needed:
        provider.complete_json("rules", "context", user, {"type": "object"})

    first_response = {"lines": [{"source_id": "line-1", "face": "bad"}]}
    needed.value.response_path.parent.mkdir(parents=True, exist_ok=True)
    needed.value.response_path.write_text(
        json.dumps(first_response, ensure_ascii=False), encoding="utf-8",
    )
    assert provider.complete_json("rules", "context", user, {"type": "object"}) == first_response
    first_raw = Path(provider.request_records[-1]["raw_path"])

    second_response = {"lines": [{"source_id": "line-1", "face": "fixed"}]}
    alternate = needed.value.response_path.with_name(
        needed.value.response_path.name.removesuffix(".response.json")
        + ".attempt-2.response.json"
    )
    alternate.write_text(json.dumps(second_response, ensure_ascii=False), encoding="utf-8")
    assert provider.complete_json("rules", "context", user, {"type": "object"}) == second_response
    assert json.loads(needed.value.response_path.read_text(encoding="utf-8")) == first_response
    assert json.loads(alternate.read_text(encoding="utf-8")) == second_response
    assert json.loads(first_raw.read_text(encoding="utf-8")) == first_response
