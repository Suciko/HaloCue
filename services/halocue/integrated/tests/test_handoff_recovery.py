"""Ordinary frozen handoff retries repair a partial run/receipt publication."""

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
for context in ("writing", "production", "integrated"):
    sys.path.insert(0, str(REPO / "services/halocue" / context / "src"))
sys.path.insert(0, str(REPO / "services/halocue/writing/tests"))
from halocue_integrated.server import IntegratedRuntime  # noqa: E402 — standalone cross-context test imports
from halocue_writing.errors import DomainError  # noqa: E402 — standalone cross-context test imports
from halocue_writing.workflow_pack import ENGINE_RULE_SOURCE, MODE_SOURCES, WORKFLOW_RULE_SOURCES  # noqa: E402 — standalone cross-context test imports
from test_scene_asset_references import _freeze_asset_release  # noqa: E402 — standalone cross-context test imports


@pytest.mark.parametrize("restart", [False, True])
@pytest.mark.parametrize("corruption", [None, "wrong-schema", "wrong-run"])
def test_normal_handoff_retry_repairs_missing_receipt(tmp_path, monkeypatch, restart, corruption):
    rules = tmp_path / "rules"
    paths = [path for group in WORKFLOW_RULE_SOURCES.values() for path in group]
    paths += list(MODE_SOURCES.values()) + [ENGINE_RULE_SOURCE, "knowledge/老师在场规则.md"]
    for relative in paths:
        target = rules / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("Synthetic workflow rule only.\n", encoding="utf-8")
    monkeypatch.setenv("HALOCUE_BA_WRITING_SKILL_DIR", str(rules))
    monkeypatch.setenv("HALOCUE_NAME_BASELINE", str(tmp_path / "absent-baseline.json"))
    monkeypatch.delenv("HALOCUE_AA_DATA", raising=False)
    index = tmp_path / "resources.json"
    index.write_text(
        json.dumps({"bg": {"BG_Greenhouse": "aa-hash-121522699"}, "sounds": [], "characters": []}),
        encoding="utf-8",
    )

    def create():
        runtime = IntegratedRuntime(
            host="127.0.0.1",
            port=0,
            writing_data_dir=tmp_path / "writing",
            production_data_dir=tmp_path / "production",
            resource_index=index,
        )
        assert runtime.production_service.settings.legacy_root.is_relative_to(tmp_path)
        assert runtime.production_service.settings.aa_data is None
        runtime.start_upstreams()
        return runtime

    runtime = create()
    try:
        _, _, release = _freeze_asset_release(runtime.writing_service)
        write = runtime.production_service._write_asset_receipt

        def fail_write(*args):
            raise OSError("synthetic receipt persistence interruption")

        runtime.production_service._write_asset_receipt = fail_write
        with pytest.raises(DomainError):
            runtime.writing_service.handoff_release(release["release_id"])
        assert len(runtime.production_service.repository.list_runs()) == 1
        runtime.production_service._write_asset_receipt = write
        run_id = runtime.production_service.repository.list_runs()[0].run_id
        if corruption:
            path = runtime.production_service._receipt_path(run_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "wrong/1.0"
                        if corruption == "wrong-schema"
                        else "production-asset-usage/1.0",
                        "production_run_id": "run-wrong" if corruption == "wrong-run" else run_id,
                        "references": [],
                    }
                ),
                encoding="utf-8",
            )
        # A changed author scene must not be used to repair this frozen release.
        work = runtime.writing_service.get_work(release["work"]["id"])
        scene_id = release["manifest"]["asset_references"][0]["scene_id"]
        runtime.writing_service.set_scene_asset_references(
            work["id"], scene_id, {"expected_version": work["version"], "references": []}
        )
        if restart:
            runtime.close(stop_gateway=False)
            runtime = create()
        retry = runtime.writing_service.handoff_release(release["release_id"])
        assert retry["asset_handoff"]["status"] == "complete"
        assert len(runtime.production_service.repository.list_runs()) == 1
        assert retry["production_run_id"] == run_id
        assert runtime.writing_service.production_asset_status(release["release_id"])["references"]
    finally:
        runtime.close(stop_gateway=False)


def test_concurrent_custom_copy_replay_produces_one_task_asset_and_receipt(
    tmp_path, monkeypatch, isolated_legacy_root
):
    import hashlib
    import io
    import threading
    from concurrent.futures import ThreadPoolExecutor, TimeoutError
    from PIL import Image
    from halocue_integrated.production_assets import IntegratedProductionService
    from halocue_production.config import Settings

    index = tmp_path / "resources.json"
    index.write_text(json.dumps({"bg": {}, "sounds": [], "characters": []}), encoding="utf-8")
    service = IntegratedProductionService(
        Settings(
            project_root=REPO / "services/halocue/production",
            data_dir=tmp_path / "production",
            legacy_root=isolated_legacy_root,
            resource_index=index,
            aa_data=None,
            port=0,
        )
    )
    stream = io.BytesIO()
    Image.new("RGB", (960, 540), "#345643").save(stream, format="PNG")
    uploaded = service.upload_asset(filename="synthetic.png", content=stream.getvalue())
    asset = service.register_custom_asset(
        {
            "kind": "background",
            "upload_token": uploaded["upload_token"],
            "display_name": "Synthetic background",
        }
    )["asset"]
    reference = {
        "reference_id": "reference-synthetic",
        "asset_kind": "background",
        "source_type": "custom_library",
        "source_asset_id": asset["asset_id"],
        "source_version": str(asset["metadata_version"]),
        "content_hash": "sha256:" + asset["sha256"].removeprefix("sha256:"),
        "content_hash_kind": "file_sha256",
        "source_snapshot": {
            "source": "custom_library",
            "asset_id": asset["asset_id"],
            "metadata_version": asset["metadata_version"],
            "sha256": asset["sha256"],
        },
        "production_copy": None,
    }
    canonical = json.dumps([reference], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    text = "旁白: 合成场景。\n"
    payload = {
        "project": "Synthetic replay",
        "source": {"kind": "inline", "text": text},
        "script_release": {
            "id": "release-000000000001",
            "display_version": "v1",
            "content_hash": hashlib.sha256(text.encode()).hexdigest(),
            "source_set_digest": "sha256:" + "b" * 64,
        },
        "asset_handoff": {
            "schema_version": "production-asset-handoff/1.0",
            "release_id": "release-000000000001",
            "source_set_digest": "sha256:" + "b" * 64,
            "references": [
                {
                    "scene_id": "scene-synthetic",
                    "references": [reference],
                    "digest": "sha256:" + hashlib.sha256(canonical.encode()).hexdigest(),
                }
            ],
        },
    }
    original = service._write_asset_receipt

    def fail(*args):
        raise OSError("synthetic interrupted receipt")

    try:
        monkeypatch.setattr(service, "_write_asset_receipt", fail)
        with pytest.raises(OSError):
            service.create_run(payload)
        run = service.repository.list_runs()[0]
        before_assets = service.task_assets(run.run_id)["items"]
        assert len(before_assets) == 1
        started, finish = threading.Event(), threading.Event()

        def delayed(*args):
            started.set()
            assert finish.wait(5)
            return original(*args)

        monkeypatch.setattr(service, "_write_asset_receipt", delayed)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(service.create_run, payload)
            assert started.wait(3)
            second = pool.submit(service.create_run, payload)
            try:
                with pytest.raises(TimeoutError):
                    second.result(timeout=0.2)
            finally:
                finish.set()
            assert first.result(timeout=5)["run"]["run_id"] == run.run_id
            assert second.result(timeout=5)["run"]["run_id"] == run.run_id
        assert service.task_assets(run.run_id)["items"] == before_assets
        assert len(service.repository.list_runs()) == 1
        assert service.resource_usage(run.run_id)["references"][0]["production_copy"]["copy_id"]
        assert not list(service._asset_receipt_dir.glob("*.tmp"))
    finally:
        service.jobs.close()
