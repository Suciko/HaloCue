"""Grounding and revision-safety contracts for source-bound adaptation candidates."""

import base64
import json

import pytest

from halocue_writing.errors import DomainError
from halocue_writing.providers import FakeWritingProvider
from halocue_writing.service import WritingService


def prepared(tmp_path, text="第一章 起点\n老师在门口停下。\n窗里的灯仍亮着。", max_calls=12):
    service = WritingService(tmp_path / "writing")
    work = service.create_work({"title": "Synthetic adaptation"})
    payload = {"filename": "novel.txt", "content_base64": base64.b64encode(text.encode()).decode()}
    preview = service.sources.preview(work["id"], payload)
    source = service.sources.apply(
        work["id"], {**payload, "preview_digest": preview["preview_digest"]}
    )["source"]
    plan = service.adaptations.create(
        work["id"], {"source_version_id": source["id"], "max_calls": max_calls}
    )
    service.adaptations.approve_plan(plan["id"], {"plan_digest": plan["plan_digest"]})
    return service, work, source, plan


def valid_reply(chapter, text="旁白: 老师停在门口。"):
    paragraph = chapter["paragraphs"][0]
    return {
        "schema_version": "adaptation-chapter/1.0",
        "text": text,
        "source_refs": [{"paragraph_id": paragraph["id"], "quote": paragraph["text"]}],
        "deviations": [],
        "open_threads": [],
    }


class ReplyProvider(FakeWritingProvider):
    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    def generate_scene(self, context):
        self.calls += 1
        return self.reply


@pytest.mark.parametrize(
    "invalid",
    [
        "not-json",
        "not-object",
        "wrong-version",
        "missing-references",
        "unknown-paragraph",
        "wrong-quote",
        "empty-text",
        "nonstring-text",
        "bad-ref-type",
        "bad-open-threads",
    ],
)
def test_invalid_adaptation_never_becomes_a_source_grounded_proposal(tmp_path, invalid):
    service, work, source, plan = prepared(tmp_path)
    chapter = source["chapters"][0]
    reply = valid_reply(chapter)
    if invalid == "not-json":
        raw = "A plain ungrounded model answer"
    elif invalid == "not-object":
        raw = json.dumps([reply])
    else:
        if invalid == "wrong-version":
            reply["schema_version"] = "adaptation-chapter/99"
        elif invalid == "missing-references":
            reply.pop("source_refs")
        elif invalid == "unknown-paragraph":
            reply["source_refs"][0]["paragraph_id"] = "paragraph-nonexistent"
        elif invalid == "wrong-quote":
            reply["source_refs"][0]["quote"] = "从未出现在原文中的事实"
        elif invalid == "empty-text":
            reply["text"] = "  "
        elif invalid == "nonstring-text":
            reply["text"] = {"not": "text"}
        elif invalid == "bad-ref-type":
            reply["source_refs"] = ["paragraph"]
        elif invalid == "bad-open-threads":
            reply["open_threads"] = "not-a-list"
        raw = json.dumps(reply)
    service.provider = ReplyProvider(raw)
    with pytest.raises(DomainError) as rejected:
        service.adaptations.generate_chapter_candidate(plan["id"], chapter["id"])
    assert rejected.value.code == "provider_output_invalid"
    assert service.adaptations.get(plan["id"])["chapters"][0]["status"] == "planned"
    assert not [
        p for p in service.get_work(work["id"])["proposals"] if p["kind"] == "adaptation_chapter"
    ]


def test_valid_adaptation_retains_verified_quote_and_requires_explicit_acceptance(tmp_path):
    service, work, source, plan = prepared(tmp_path)
    chapter = source["chapters"][0]
    reply = valid_reply(chapter)
    service.provider = ReplyProvider(json.dumps(reply))
    generated = service.adaptations.generate_chapter_candidate(plan["id"], chapter["id"])
    assert generated["candidate"]["source_refs"] == reply["source_refs"]
    assert generated["candidate"]["formal"] is False
    assert service.get_work(work["id"])["version"] == work["version"]
    accepted = service.accept_proposal(
        work["id"], generated["proposal_id"], {"expected_version": work["version"]}
    )
    assert accepted["revision_id"]


def test_long_chapter_analysis_retains_every_window_and_source_span(tmp_path):
    text = "第一章 起点\n" + "老师在门口等待。" * 160
    service, work, source, plan = prepared(tmp_path, text)
    chapter = source["chapters"][0]
    result = service.adaptations.run(plan["id"], {"window_characters": 256})
    analyzed = result["chapters"][0]["candidate"]
    expected_text = "".join(item["text"] for item in chapter["paragraphs"])
    observed_text = "".join(item["text"] for item in analyzed["coverage"])
    assert observed_text == expected_text
    assert len(analyzed["windows"]) > 1
    assert result["chapters"][0]["dependency"]["analysis"] == analyzed


@pytest.mark.parametrize("accept", [False, True])
def test_analysis_rerun_does_not_overwrite_candidate_or_accepted_manuscript(tmp_path, accept):
    service, work, source, plan = prepared(tmp_path)
    service.provider = ReplyProvider(json.dumps(valid_reply(source["chapters"][0])))
    generated = service.adaptations.generate_chapter_candidate(
        plan["id"], source["chapters"][0]["id"]
    )
    if accept:
        service.accept_proposal(
            work["id"], generated["proposal_id"], {"expected_version": work["version"]}
        )
    before = service.adaptations.get(plan["id"])["chapters"][0]
    service.adaptations.run(plan["id"], {"window_characters": 256})
    after = service.adaptations.get(plan["id"])["chapters"][0]
    assert after["status"] == before["status"]
    assert after["candidate"] == before["candidate"]
    assert after["dependency"]["analysis"]["source_only"] is True


def test_older_candidate_cannot_replace_a_newer_accepted_manuscript(tmp_path):
    service, work, source, plan = prepared(tmp_path)
    chapter = source["chapters"][0]
    service.provider = ReplyProvider(json.dumps(valid_reply(chapter, "旁白: 候选一。")))
    older = service.adaptations.generate_chapter_candidate(plan["id"], chapter["id"])
    service.provider = ReplyProvider(json.dumps(valid_reply(chapter, "旁白: 候选二。")))
    newer = service.adaptations.generate_chapter_candidate(plan["id"], chapter["id"])
    accepted = service.accept_proposal(
        work["id"], newer["proposal_id"], {"expected_version": work["version"]}
    )
    with pytest.raises(DomainError) as rejected:
        service.accept_proposal(
            work["id"], older["proposal_id"], {"expected_version": accepted["work"]["version"]}
        )
    assert rejected.value.code == "proposal_superseded"
    current = service.adaptations.get(plan["id"])["chapters"][0]["candidate"]
    assert current["text"] == "旁白: 候选二。"
    assert current["revision_id"] == accepted["revision_id"]


def test_candidate_can_explicitly_revise_its_captured_current_manuscript(tmp_path):
    service, work, source, plan = prepared(tmp_path)
    chapter = source["chapters"][0]
    service.provider = ReplyProvider(json.dumps(valid_reply(chapter)))
    first = service.adaptations.generate_chapter_candidate(plan["id"], chapter["id"])
    accepted = service.accept_proposal(
        work["id"], first["proposal_id"], {"expected_version": work["version"]}
    )
    second = service.adaptations.generate_chapter_candidate(plan["id"], chapter["id"])
    proposal = next(
        p for p in service.get_work(work["id"])["proposals"] if p["id"] == second["proposal_id"]
    )
    assert proposal["base_revision_id"] == accepted["revision_id"]
    accepted_again = service.accept_proposal(
        work["id"], second["proposal_id"], {"expected_version": accepted["work"]["version"]}
    )
    assert accepted_again["revision_id"] != accepted["revision_id"]


def test_failed_provider_attempt_does_not_refund_adaptation_call_limit(tmp_path):
    service, work, source, plan = prepared(tmp_path, max_calls=1)

    class FailingProvider(ReplyProvider):
        def generate_scene(self, context):
            self.calls += 1
            raise RuntimeError("synthetic completed-or-unknown transport failure")

    provider = FailingProvider("")
    service.provider = provider
    chapter_id = source["chapters"][0]["id"]
    with pytest.raises(RuntimeError):
        service.adaptations.generate_chapter_candidate(plan["id"], chapter_id)
    with pytest.raises(DomainError) as exhausted:
        service.adaptations.generate_chapter_candidate(plan["id"], chapter_id)
    assert exhausted.value.code == "adaptation_budget_exhausted"
    assert provider.calls == 1


@pytest.mark.parametrize("broken", ["source_refs", "source_version_id", "source_chapter_id"])
def test_acceptance_revalidates_legacy_semantically_invalid_but_checksummed_candidate(
    tmp_path, broken
):
    from halocue_writing.repository import canonical_json

    service, work, source, plan = prepared(tmp_path)
    service.provider = ReplyProvider(json.dumps(valid_reply(source["chapters"][0])))
    generated = service.adaptations.generate_chapter_candidate(
        plan["id"], source["chapters"][0]["id"]
    )
    # Model an old valid-hash proposal made by the pre-validation implementation.
    with service.repo.transaction() as connection:
        proposal = connection.execute(
            "SELECT * FROM proposals WHERE id=?", (generated["proposal_id"],)
        ).fetchone()
        candidate = json.loads(service.repo.read_text(proposal["candidate_uri"]))
        if broken == "source_refs":
            candidate["source_refs"][0]["paragraph_id"] = "legacy-invented-paragraph"
        else:
            candidate.pop(broken)
        _, digest = service.repo.atomic_write_text(
            proposal["candidate_uri"], canonical_json(candidate) + "\n"
        )
        connection.execute(
            "UPDATE proposals SET candidate_hash=? WHERE id=?", (digest, proposal["id"])
        )
    with pytest.raises(DomainError) as rejected:
        service.accept_proposal(
            work["id"], generated["proposal_id"], {"expected_version": work["version"]}
        )
    assert rejected.value.code == "proposal_candidate_invalid"
    assert not [
        a for a in service.get_work(work["id"])["artifacts"] if a["kind"] == "adaptation_manuscript"
    ]


@pytest.mark.parametrize("change", ["source", "target"])
def test_late_adaptation_result_cannot_overwrite_changed_inputs(tmp_path, change):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    service, work, source, plan = prepared(tmp_path)
    chapter = source["chapters"][0]
    service.provider = ReplyProvider(json.dumps(valid_reply(chapter, "旁白: 待采纳版本。")))
    existing = service.adaptations.generate_chapter_candidate(plan["id"], chapter["id"])
    started, finish = threading.Event(), threading.Event()

    class SlowReply(ReplyProvider):
        def generate_scene(self, context):
            started.set()
            assert finish.wait(10)
            return super().generate_scene(context)

    service.provider = SlowReply(json.dumps(valid_reply(chapter, "旁白: 晚到版本。")))
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(
            service.adaptations.generate_chapter_candidate, plan["id"], chapter["id"]
        )
        try:
            assert started.wait(3)
            if change == "source":
                new = {
                    "filename": "new.txt",
                    "content_base64": base64.b64encode("第二章\n新的故事。".encode()).decode(),
                    "base_version_id": source["id"],
                }
                preview = service.sources.preview(work["id"], new)
                service.sources.apply(
                    work["id"], {**new, "preview_digest": preview["preview_digest"]}
                )
            else:
                service.accept_proposal(
                    work["id"], existing["proposal_id"], {"expected_version": work["version"]}
                )
            before = service.adaptations.get(plan["id"])["chapters"][0]["candidate"]
        finally:
            finish.set()
        with pytest.raises(DomainError) as rejected:
            pending.result(timeout=10)
        assert rejected.value.code == "adaptation_inputs_changed"
    after = service.adaptations.get(plan["id"])["chapters"][0]["candidate"]
    assert before == after


def test_stale_source_plan_is_rejected_before_provider_dispatch(tmp_path):
    service, work, source, plan = prepared(tmp_path)
    provider = ReplyProvider(json.dumps(valid_reply(source["chapters"][0])))
    service.provider = provider
    new = {
        "filename": "new.txt",
        "content_base64": base64.b64encode("第二章\n新的故事。".encode()).decode(),
        "base_version_id": source["id"],
    }
    preview = service.sources.preview(work["id"], new)
    service.sources.apply(work["id"], {**new, "preview_digest": preview["preview_digest"]})
    with pytest.raises(DomainError) as rejected:
        service.adaptations.generate_chapter_candidate(plan["id"], source["chapters"][0]["id"])
    assert rejected.value.code == "adaptation_inputs_changed"
    assert provider.calls == 0
    assert service.adaptations.get(plan["id"])["budget"]["reserved_calls"] == 0


@pytest.mark.parametrize("limit", [0, -1, True, 1.5, "invalid"])
def test_invalid_call_limit_is_rejected_as_domain_error(tmp_path, limit):
    with pytest.raises(DomainError) as rejected:
        prepared(tmp_path, max_calls=limit)
    assert rejected.value.code == "invalid_adaptation_budget"


def test_http_candidate_validation_reports_contract_failure_without_acceptance(tmp_path):
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer
    from pathlib import Path
    from halocue_writing.app import make_handler

    service, work, source, plan = prepared(tmp_path)
    service.provider = ReplyProvider("not structured output")
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), make_handler(service, Path(__file__).resolve().parents[1] / "web")
    )
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/api/v1/works/{work['id']}/adaptations/{plan['id']}/chapters/{source['chapters'][0]['id']}/candidate:generate"
        request = urllib.request.Request(
            url, data=b"{}", headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.status == 202
            queued = json.loads(response.read())["data"]
        import time
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            run = service.get_agent_run(work["id"], queued["agent_run_id"])
            if run["status"] == "failed":
                break
            time.sleep(0.01)
        assert run["status"] == "failed"
        assert run["failure"]["code"] == "provider_output_invalid"
        assert not service.get_work(work["id"])["proposals"]
        assert service.adaptations.get(plan["id"])["chapters"][0]["status"] == "planned"
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)
        service.close()


@pytest.mark.parametrize("nonfinite", [float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize("legacy", [False, True])
def test_nested_nonfinite_values_are_rejected_at_generation_and_acceptance(
    tmp_path, nonfinite, legacy
):
    from halocue_writing.repository import canonical_json

    service, work, source, plan = prepared(tmp_path)
    reply = valid_reply(source["chapters"][0])
    if not legacy:
        reply["deviations"] = [{"evidence": {"scores": [nonfinite]}}]
        service.provider = ReplyProvider(json.dumps(reply))
        with pytest.raises(DomainError) as rejected:
            service.adaptations.generate_chapter_candidate(plan["id"], source["chapters"][0]["id"])
        assert rejected.value.code == "provider_output_invalid"
        assert service.get_work(work["id"])["proposals"] == []
    else:
        service.provider = ReplyProvider(json.dumps(reply))
        generated = service.adaptations.generate_chapter_candidate(
            plan["id"], source["chapters"][0]["id"]
        )
        with service.repo.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM proposals WHERE id=?", (generated["proposal_id"],)
            ).fetchone()
            candidate = json.loads(service.repo.read_text(row["candidate_uri"]))
            candidate["open_threads"] = [{"evidence": {"scores": [nonfinite]}}]
            _, digest = service.repo.atomic_write_text(
                row["candidate_uri"], canonical_json(candidate) + "\n"
            )
            connection.execute(
                "UPDATE proposals SET candidate_hash=? WHERE id=?", (digest, row["id"])
            )
        with pytest.raises(DomainError) as rejected:
            service.accept_proposal(
                work["id"], generated["proposal_id"], {"expected_version": work["version"]}
            )
        assert rejected.value.code == "proposal_candidate_invalid"
    assert not [
        a for a in service.get_work(work["id"])["artifacts"] if a["kind"] == "adaptation_manuscript"
    ]
    service.close()
