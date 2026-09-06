"""Disposable Proposal decision fixture for Codex in-app Browser acceptance."""

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
from halocue_writing.providers import FakeWritingProvider
from halocue_writing.service import WritingService


def revision_count(work: dict) -> int:
    return sum(len(artifact.get("revisions", [])) for artifact in work.get("artifacts", []))


def build_pending_character_proposal(
    service: WritingService, *, title: str
) -> dict[str, object]:
    work = service.create_work(
        {
            "title": title,
            "idea": "白露在雨夜发现旧档案室仍有一盏提示灯亮着。",
        }
    )
    thread = work["conversation_threads"][0]
    discussed = service.post_conversation_message(
        work["id"],
        thread["id"],
        {
            "expected_thread_version": thread["version"],
            "text": "请创建一个叫《白露》的自定义角色卡，她负责核对档案，但不要直接修改正式资料。",
        },
    )
    thread = discussed["work"]["conversation_threads"][0]
    proposed = service.propose_conversation_knowledge(
        work["id"],
        thread["id"],
        {
            "expected_version": discussed["work"]["version"],
            "expected_thread_version": thread["version"],
            "kind": "character_card",
        },
    )
    return {
        "work_id": work["id"],
        "proposal_id": proposed["proposal_id"],
        "initial_revision_count": revision_count(proposed["work"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(
        prefix="halocue-iab-proposal-decision-", ignore_cleanup_errors=True
    ) as data_dir:
        service = WritingService(Path(data_dir))
        service.provider = FakeWritingProvider()
        service.start()
        fixtures = {
            "accept": build_pending_character_proposal(
                service, title="人物卡 Proposal · 采纳验收"
            ),
            "reject": build_pending_character_proposal(
                service, title="人物卡 Proposal · 退回验收"
            ),
        }
        server = ThreadingHTTPServer(
            ("127.0.0.1", args.port), make_handler(service, PROJECT_ROOT / "web")
        )

        def stop_server(*_args: object) -> None:
            threading.Thread(target=server.shutdown, daemon=True).start()

        signal.signal(signal.SIGINT, stop_server)
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, stop_server)

        base_url = f"http://127.0.0.1:{server.server_port}"
        for fixture in fixtures.values():
            fixture["url"] = (
                f"{base_url}/?section=works&work_id={fixture['work_id']}"
            )
            fixture["api_url"] = (
                f"{base_url}/api/v1/works/{fixture['work_id']}"
            )
        print(
            json.dumps(
                {
                    "base_url": base_url,
                    "data_dir": data_dir,
                    "fixtures": fixtures,
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
