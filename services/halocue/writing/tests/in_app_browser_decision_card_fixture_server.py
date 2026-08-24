"""Disposable finite-choice fixture for Codex in-app Browser acceptance."""

from __future__ import annotations

import argparse
import json
import signal
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from halocue_writing.app import make_handler
from halocue_writing.errors import DomainError
from halocue_writing.providers import FakeWritingProvider
from halocue_writing.service import WritingService


class DecisionCardProvider(FakeWritingProvider):
    """Return one finite choice, then acknowledge the ordinary reply."""

    def __init__(self) -> None:
        super().__init__()
        self.discussion_count = 0

    def discuss_work(self, _messages: list[dict], _work_context: dict) -> dict:
        self.discussion_count += 1
        if self.discussion_count > 1:
            return {
                "text": "已记录你的选择，我们可以继续讨论细节。",
                "questions": [],
                "ready_for_proposal": False,
            }
        return {
            "text": "我们先选定推进方向。",
            "questions": [],
            "ready_for_proposal": False,
            "decision_card": {
                "kind": "choose",
                "title": "下一步先确定哪一项？",
                "options": [
                    {
                        "id": "direction_a",
                        "label": "先定人物关系",
                        "description": "先固定两人的关系变化。",
                    },
                    {
                        "id": "direction_b",
                        "label": "先定开场事件",
                        "description": "先固定第一幕发生的事件。",
                    },
                ],
                "submit_label": "提交选择",
                "allow_custom": True,
            },
        }


class DecisionFixtureService(WritingService):
    def __init__(self, data_dir: Path, *, fail_first_decision: bool = False):
        super().__init__(data_dir)
        self.fail_first_decision = fail_first_decision

    def enqueue_conversation_message(self, work_id: str, thread_id: str, payload: dict):
        if self.fail_first_decision and payload.get("decision_response"):
            self.fail_first_decision = False
            raise DomainError(
                "decision_fixture_failure",
                "这次选择没有保存，请重试。",
                status=503,
            )
        return super().enqueue_conversation_message(work_id, thread_id, payload)


def revision_count(work: dict) -> int:
    return sum(len(artifact.get("revisions", [])) for artifact in work.get("artifacts", []))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--fail-first-decision", action="store_true")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(
        prefix="halocue-iab-decision-", ignore_cleanup_errors=True
    ) as data_dir:
        service = DecisionFixtureService(
            Path(data_dir), fail_first_decision=args.fail_first_decision
        )
        service.provider = DecisionCardProvider()
        service.start()
        work = service.create_work(
            {
                "title": "普通决策卡验收",
                "idea": "两位学生在雨夜寻找失落的录音。",
            }
        )
        thread = work["conversation_threads"][0]
        assistant = thread["messages"][-1]
        server = ThreadingHTTPServer(
            ("127.0.0.1", args.port), make_handler(service, PROJECT_ROOT / "web")
        )

        def stop_server(*_args: object) -> None:
            threading.Thread(target=server.shutdown, daemon=True).start()

        signal.signal(signal.SIGINT, stop_server)
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, stop_server)

        print(
            json.dumps(
                {
                    "url": (
                        f"http://127.0.0.1:{server.server_port}/"
                        f"?section=works&work_id={work['id']}"
                    ),
                    "api_url": (
                        f"http://127.0.0.1:{server.server_port}"
                        f"/api/v1/works/{work['id']}"
                    ),
                    "data_dir": data_dir,
                    "work_id": work["id"],
                    "thread_id": thread["id"],
                    "decision_message_id": assistant["id"],
                    "initial_revision_count": revision_count(work),
                    "fail_first_decision": args.fail_first_decision,
                    "provider": "fake / local-rules",
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
