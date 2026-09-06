"""Disposable in-app Browser fixture for asset-induced release Gate drift."""

from __future__ import annotations

import argparse
import json
import signal
import sys
import tempfile
from http.server import ThreadingHTTPServer
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from halocue_writing.app import make_handler
from halocue_writing.service import WritingService


def build_fixture(service: WritingService) -> tuple[str, str]:
    work = service.create_work({"title": "素材 Gate 失效夹具"})
    result = service.save_brief(
        work["id"],
        {
            "expected_version": work["version"],
            "idea": "老师在夜间温室核对一条被改写的门禁记录。",
            "mode": "bond_short",
            "characters": ["老师"],
        },
    )
    result = service.generate_blueprint(work["id"], {"expected_version": result["work"]["version"]})
    chapter_id = result["work"]["chapters"][0]["id"]
    result = service.create_scene(
        work["id"], chapter_id,
        {
            "expected_version": result["work"]["version"],
            "title": "温室门禁", "location": "格黑娜旧温室", "goal": "确认门禁记录改变的时间与影响",
        },
    )
    scene_id = result["scene_id"]
    result = service.generate_scene_candidate(work["id"], scene_id, {"expected_version": result["work"]["version"]})
    result = service.accept_proposal(work["id"], result["proposal_id"], {"expected_version": result["work"]["version"]})
    result = service.review_scene(work["id"], scene_id, {"expected_version": result["work"]["version"]})
    for finding in result["findings"]:
        if finding["severity"] == "blocking":
            result = service.resolve_review_finding(work["id"], finding["id"], {"expected_version": result["work"]["version"], "note": "夹具确认该项已处理。"})
    result = service.skip_scene_memory_maintenance(work["id"], scene_id, {"expected_version": result["work"]["version"], "note": "夹具不沉淀长期记忆。"})
    result = service.review_continuity(work["id"], {"expected_version": result["work"]["version"]})
    result = service.review_release(work["id"], {"expected_version": result["work"]["version"]})
    result = service.set_scene_asset_references(
        work["id"], scene_id,
        {
            "expected_version": result["work"]["version"],
            "references": [{
                "asset_kind": "background", "source_type": "resource_index", "source_asset_id": "BG_Greenhouse",
                "display_name": "温室背景", "source_version": "catalog:fixture-v2", "content_hash": "sha256:" + "a" * 64,
                "content_hash_kind": "aa_resource_hash", "source_snapshot": {"resource_id": "BG_Greenhouse", "fixture": True},
            }],
        },
    )
    return work["id"], scene_id


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="halocue-iab-asset-drift-") as data_dir:
        service = WritingService(Path(data_dir))
        service.start()
        work_id, scene_id = build_fixture(service)
        server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(service, PROJECT_ROOT / "web"))

        def stop_server(*_args: object) -> None:
            server.shutdown()

        signal.signal(signal.SIGINT, stop_server)
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, stop_server)
        print(json.dumps({"url": f"http://127.0.0.1:{server.server_port}/?section=writing&stage=release&work_id={work_id}", "work_id": work_id, "scene_id": scene_id, "provider": "fake / local-rules"}, ensure_ascii=False), flush=True)
        try:
            server.serve_forever()
        finally:
            server.server_close()
            service.close()


if __name__ == "__main__":
    main()
