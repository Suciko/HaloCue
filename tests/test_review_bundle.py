"""The collaborator entry must remain isolated and export the real worktree."""

import json
import zipfile

import pytest

from tools import build_review_bundle as bundle
from tools.review_start import reviewer_environment
from tools.review_fixture import create_review_sample


@pytest.mark.parametrize(
    "path",
    [
        "开始验收.cmd",
        "START_REVIEW.md",
        "requirements-review.txt",
        "tools/review_start.py",
        "tools/review_fixture.py",
        "services/halocue/writing/web/card-assistance.js",
        "services/halocue/writing/web/knowledge-impact.js",
        "docs/review/审查流程与清单.md",
    ],
)
def test_review_export_includes_required_paths(path):
    assert bundle.selected_path(path)


@pytest.mark.parametrize(
    "path",
    [
        ".review-data/user/settings.json",
        ".review-venv/pyvenv.cfg",
        "migration-status.json",
        "docs/handoffs/private.md",
        "services/backup-before-review/source.py",
        "services/.tmp/notes.json",
        "services/halocue/writing/docs/six-goal-evidence-audit.md",
        "llm.json",
        "assets/private.bundle",
        "data/aa_resources.json",
    ],
)
def test_review_export_excludes_private_or_transient_paths(path):
    assert not bundle.selected_path(path)


def test_review_environment_does_not_inherit_private_configuration(monkeypatch, tmp_path):
    for key in (
        "HALOCUE_FEEDBACK_SYNC_URL",
        "HALOCUE_BA_CORPUS_DIR",
        "HALOCUE_AA_ROOT",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "OPENAI_BASE_URL",
        "ANTHROPIC_BASE_URL",
    ):
        monkeypatch.setenv(key, "private-review-test-value")
    monkeypatch.setenv("PATH", "ordinary-system-path")
    env = reviewer_environment(tmp_path)
    assert env["PATH"] == "ordinary-system-path"
    assert "private-review-test-value" not in env.values()
    assert not any(key.endswith("_API_KEY") for key in env)
    assert env["HALOCUE_USER_DATA_DIR"] == str(tmp_path / "user")
    assert env["HALOCUE_BA_CORPUS_DIR"] == str(tmp_path / "no-corpus")


@pytest.mark.parametrize("name", ["review-test", "源码 验收包"])
def test_export_reads_current_and_untracked_bytes_not_git_index(monkeypatch, tmp_path, name):
    source = tmp_path / "source"
    (source / "tools").mkdir(parents=True)
    (source / "START_REVIEW.md").write_text("working copy", encoding="utf-8")
    (source / "tools/new.py").write_text("# untracked source", encoding="utf-8")
    monkeypatch.setattr(bundle, "ROOT", source)

    def git(*args):
        if args[0] == "ls-files":
            assert "--others" in args
            return "START_REVIEW.md\0tools/new.py"
        return "review-test-base" if args[0] == "rev-parse" else "review-test"

    monkeypatch.setattr(bundle, "git", git)
    result = bundle.build(tmp_path / "output", name)
    with zipfile.ZipFile(result["archive"]) as archive:
        assert archive.read(name + "/START_REVIEW.md") == b"working copy"
        assert archive.read(name + "/tools/new.py") == b"# untracked source"
        manifest = json.loads(archive.read(name + "/REVIEW_MANIFEST.json"))
    assert manifest["source_state"] == "working_tree_snapshot_not_pushed"
    assert manifest["product"] == "HaloCue"
    assert manifest["product_version"] == "1.0.0"
    assert manifest["package_kind"] == "collaborator_source_review"
    assert manifest["entrypoint"] == "开始验收.cmd"
    assert manifest["scan_findings"] == []
    with pytest.raises(ValueError, match="never overwritten"):
        bundle.build(tmp_path / "output", name)


def test_review_sample_is_local_and_has_three_distinct_impact_states(tmp_path):
    from halocue_writing.service import WritingService

    service = WritingService(tmp_path)
    try:
        assert service.provider.is_simulation
        sample = create_review_sample(service)
        before = service.get_work(sample["work_id"])
        report = service.get_knowledge_change_impact(sample["work_id"])
        assert [row["status"] for row in report["scenes"]] == [
            "needs_review",
            "unchanged",
            "not_reviewed",
        ]
        assert service.get_work(sample["work_id"]) == before
        assert len(service.list_works()) == 1
        assert len(sample["card_ids"]) == 2
        assert len(sample["scene_ids"]) == 3
    finally:
        service.close()


def test_local_stop_request_matches_only_recorded_instance(monkeypatch, tmp_path):
    from tools import review_start

    status = tmp_path / "runtime.json"
    review_start.write_json(status, {"pid": 7123, "status": "running"})

    def acknowledge(_):
        assert (tmp_path / "stop.request").read_text(encoding="ascii") == "7123"
        review_start.write_json(status, {"pid": 7123, "status": "stopped"})

    monkeypatch.setattr(review_start.time, "sleep", acknowledge)
    assert review_start.request_stop(tmp_path) == 0


def test_local_stop_does_not_claim_success_for_another_instance(monkeypatch, tmp_path):
    from tools import review_start

    status = tmp_path / "runtime.json"
    review_start.write_json(status, {"pid": 7123, "status": "running"})
    monkeypatch.setattr(
        review_start.time,
        "sleep",
        lambda _: review_start.write_json(status, {"pid": 7124, "status": "running"}),
    )
    assert review_start.request_stop(tmp_path) == 2
