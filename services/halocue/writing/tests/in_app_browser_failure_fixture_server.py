"""Disposable failure-card fixture for Codex in-app Browser acceptance."""

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
from halocue_writing.errors import DomainError
from halocue_writing.providers import FakeWritingProvider
from halocue_writing.service import WritingService


class FailingProvider(FakeWritingProvider):
    def __init__(self, *, code: str, message: str, details: dict | None = None):
        super().__init__()
        self.code = code
        self.message = message
        self.details = details or {}

    def discuss_work(self, _messages: list[dict], _work_context: dict) -> dict:
        raise DomainError(
            self.code,
            self.message,
            status=502 if self.code == "writing_provider_failed" else 409,
            details=self.details,
        )

    def generate_scene(self, _context: dict) -> str:
        raise DomainError(
            self.code,
            self.message,
            status=502 if self.code == "writing_provider_failed" else 409,
            details=self.details,
        )

    def rewrite_scene(self, _context: dict, _base_text: str, _instruction: str) -> str:
        raise DomainError(
            self.code,
            self.message,
            status=502 if self.code == "writing_provider_failed" else 409,
            details=self.details,
        )


FAILURES = {
    "provider_timeout": {
        "code": "writing_provider_failed",
        "message": "模型服务没有在限定时间内响应。",
        "details": {"failure_kind": "provider_timeout"},
    },
    "provider_rate_limited": {
        "code": "writing_provider_failed",
        "message": "模型服务暂时限制请求频率。",
        "details": {"failure_kind": "provider_rate_limited"},
    },
    "agent_turn_budget_exceeded": {
        "code": "agent_turn_budget_exceeded",
        "message": "当前 Agent 授权轮次已经用完。",
    },
    "agent_snapshot_integrity_failed": {
        "code": "agent_snapshot_integrity_failed",
        "message": "固定输入与保存的校验值不一致。",
    },
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="halocue-iab-failure-") as data_dir:
        service = WritingService(Path(data_dir))
        service.start()
        works = {}
        try:
            for failure_kind, failure in FAILURES.items():
                service.provider = FakeWritingProvider()
                work = service.create_work({
                    "title": f"恢复验收 · {failure_kind}",
                    "idea": "雨夜的提示灯突然熄灭。",
                })
                thread = work["conversation_threads"][0]
                service.provider = FailingProvider(**failure)
                try:
                    service.post_conversation_message(
                        work["id"],
                        thread["id"],
                        {
                            "expected_thread_version": thread["version"],
                            "text": "请检查这次失败边界，但不要修改正式资料。",
                        },
                    )
                except DomainError as error:
                    if error.code != "agent_failed":
                        raise
                else:
                    raise RuntimeError("failure fixture did not create a failed AgentRun")
                works[failure_kind] = work["id"]
        except Exception:
            service.close()
            raise
        service.provider = FakeWritingProvider()
        scene_work = service.create_work({
            "title": "恢复验收 · 本场 Agent",
            "idea": "午后的走廊里，提示灯突然熄灭。",
        })
        brief = service.save_brief(
            scene_work["id"],
            {
                "expected_version": scene_work["version"],
                "idea": "午后的走廊里，提示灯突然熄灭。",
                "mode": "bond_short",
                "characters": ["爱丽丝"],
            },
        )
        blueprint = service.generate_blueprint(
            scene_work["id"], {"expected_version": brief["work"]["version"]}
        )
        chapter = service.create_chapter(
            scene_work["id"],
            {"expected_version": blueprint["work"]["version"], "title": "第一章"},
        )
        scene = service.create_scene(
            scene_work["id"],
            chapter["chapter_id"],
            {
                "expected_version": chapter["work"]["version"],
                "title": "走廊的提示灯",
                "location": "学校走廊",
                "goal": "确认提示灯熄灭的原因",
            },
        )
        candidate = service.generate_scene_candidate(
            scene_work["id"],
            scene["scene_id"],
            {"expected_version": scene["work"]["version"]},
        )
        rejected = service.reject_proposal(
            scene_work["id"],
            candidate["proposal_id"],
            {"expected_version": candidate["work"]["version"], "note": "固定为 Browser 恢复夹具"},
        )
        card = service.save_character_card(
            scene_work["id"],
            {
                "expected_version": rejected["work"]["version"],
                "card_id": "character-aris",
                "name": "爱丽丝",
                "source_refs": ["Browser 恢复夹具"],
                "voice_anchors": ["先确认眼前的情况。"],
                "trust_status": "confirmed",
            },
        )
        configured = service.configure_scene_context(
            scene_work["id"],
            scene["scene_id"],
            {
                "expected_version": card["work"]["version"],
                "character_card_ids": ["character-aris"],
                "world_item_ids": [],
                "reference_file_ids": [],
            },
        )
        service.provider = FailingProvider(**FAILURES["provider_timeout"])
        try:
            service.run_scene_agent(
                scene_work["id"],
                scene["scene_id"],
                {"expected_version": configured["work"]["version"], "instruction": "记录本场超时恢复边界。"},
            )
        except DomainError as error:
            if error.code != "agent_failed":
                raise
        else:
            raise RuntimeError("scene failure fixture did not create a failed AgentRun")
        works["scene_provider_timeout"] = scene_work["id"]
        scene_refs = {
            "scene_provider_timeout": {
                "work_id": scene_work["id"],
                "scene_id": scene["scene_id"],
            }
        }
        service.provider = FakeWritingProvider()
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
                    "url": f"http://127.0.0.1:{server.server_port}/?section=works&work_id={works['provider_timeout']}",
                    "work_id": works["provider_timeout"],
                    "urls": {
                        failure_kind: f"http://127.0.0.1:{server.server_port}/?section=works&work_id={work_id}"
                        for failure_kind, work_id in works.items()
                    },
                    "scene_urls": {
                        failure_kind: f"http://127.0.0.1:{server.server_port}/?section=writing&stage=draft&work_id={ref['work_id']}&scene_id={ref['scene_id']}"
                        for failure_kind, ref in scene_refs.items()
                    },
                    "provider": "fake",
                    "can_call_model": False,
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
