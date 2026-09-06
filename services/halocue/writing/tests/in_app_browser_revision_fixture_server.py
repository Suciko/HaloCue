"""Disposable Browser fixture for the post-Revision scene review flow."""

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
    work = service.create_work({"title": "Revision 后审查引导夹具"})
    card = service.save_character_card(
        work["id"],
        {
            "expected_version": work["version"],
            "card_id": "character-alice",
            "name": "爱丽丝",
            "source_refs": ["Browser 隔离夹具"],
            "trust_status": "confirmed",
            "voice_anchors": ["先确认眼前的情况。"],
        },
    )
    brief = service.save_brief(
        work["id"],
        {
            "expected_version": card["work"]["version"],
            "idea": "爱丽丝在走廊确认一盏异常提示灯。",
            "mode": "bond_short",
            "characters": ["爱丽丝"],
        },
    )
    blueprint = service.generate_blueprint(
        work["id"], {"expected_version": brief["work"]["version"]}
    )
    chapter = service.create_chapter(
        work["id"],
        {"expected_version": blueprint["work"]["version"], "title": "第一章"},
    )
    scene = service.create_scene(
        work["id"],
        chapter["chapter_id"],
        {
            "expected_version": chapter["work"]["version"],
            "title": "走廊的提示灯",
            "location": "学校走廊",
            "goal": "确认提示灯熄灭的原因",
        },
    )
    candidate = service.generate_scene_candidate(
        work["id"], scene["scene_id"], {"expected_version": scene["work"]["version"]}
    )
    accepted = service.accept_proposal(
        work["id"],
        candidate["proposal_id"],
        {
            "expected_version": candidate["work"]["version"],
            "text": "旁白: 走廊尽头的提示灯忽然亮了一下。\n爱丽丝: 先确认眼前的情况。\n旁白: 她没有急着下结论，而是走近了控制面板。\n",
        },
    )
    return accepted["work"]["id"], scene["scene_id"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="halocue-iab-revision-") as data_dir:
        service = WritingService(Path(data_dir))
        service.start()
        work_id, scene_id = build_fixture(service)
        server = ThreadingHTTPServer(
            ("127.0.0.1", args.port), make_handler(service, PROJECT_ROOT / "web")
        )

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
