"""Disposable in-app Browser fixture for a blocked current-scene review."""

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


def build_fixture(service: WritingService) -> tuple[str, str, str]:
    work = service.create_work({"title": "当前场景阻塞审查夹具"})
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
        work["id"],
        chapter_id,
        {
            "expected_version": result["work"]["version"],
            "title": "温室门禁",
            "location": "格黑娜旧温室",
            "goal": "确认门禁记录改变的时间与影响",
        },
    )
    scene_id = result["scene_id"]
    result = service.generate_scene_candidate(
        work["id"], scene_id, {"expected_version": result["work"]["version"]}
    )
    manuscript = "\n".join(
        [
            "旁白: 作者已经安排好了这一幕，门禁灯在空旷温室里亮起。",
            "旁白: 玻璃上的雨水把室内外切成两层，旧记录仍停在昨夜。",
            "旁白: 温度计没有异常，只有访问时间被向后挪了三分钟。",
            "旁白: 老师把纸页压在桌角，没有替任何人先下结论。",
            "旁白: 远处的灌溉声停下，新的脚步却没有立刻出现。",
            "旁白: " + "门禁指示灯沿着潮湿的玻璃投下一道很长的光。" * 12,
            "老师: 先看记录。",
            "老师: 再核时间。",
            "老师: 保留原件。",
            "老师: 不先推断。",
            "老师: 等下一条证据。",
        ]
    ) + "\n"
    result = service.accept_proposal(
        work["id"],
        result["proposal_id"],
        {"expected_version": result["work"]["version"], "text": manuscript},
    )
    review = service.review_scene(
        work["id"], scene_id, {"expected_version": result["work"]["version"]}
    )
    blocking = next(item for item in review["findings"] if item["severity"] == "blocking")
    return work["id"], scene_id, blocking["id"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="halocue-iab-blocked-review-") as data_dir:
        service = WritingService(Path(data_dir))
        service.start()
        work_id, scene_id, finding_id = build_fixture(service)
        server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(service, PROJECT_ROOT / "web"))

        def stop_server(*_args: object) -> None:
            server.shutdown()

        signal.signal(signal.SIGINT, stop_server)
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, stop_server)
        print(
            json.dumps(
                {
                    "url": f"http://127.0.0.1:{server.server_port}/?section=writing&stage=draft&work_id={work_id}&scene_id={scene_id}",
                    "work_id": work_id,
                    "scene_id": scene_id,
                    "finding_id": finding_id,
                    "provider": "fake / local-rules",
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        try:
            server.serve_forever()
        finally:
            server.server_close()
            service.close()


if __name__ == "__main__":
    main()
