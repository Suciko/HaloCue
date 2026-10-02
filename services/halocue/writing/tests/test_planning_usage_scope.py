"""Planning calls must keep actual request receipts even if output is rejected."""
import json

import pytest

from halocue_writing.errors import DomainError
from halocue_writing.providers import LLMWritingProvider
from halocue_writing.service import WritingService
from test_physical_request_ledger import Response


@pytest.mark.parametrize("workflow", ["blueprint.generate", "chapter.plan"])
@pytest.mark.parametrize("rejected", [False, True])
def test_planning_scope_records_physical_usage_and_terminal_state(tmp_path, monkeypatch, workflow, rejected):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "synthetic planning"})
    provider = LLMWritingProvider({"provider": "openai", "model": "synthetic", "api_key": "SECRET-KEY"})
    monkeypatch.setattr(
        "halocue_writing.providers.urllib.request.urlopen",
        lambda *args, **kwargs: Response({
            "choices": [{"message": {"content": "{}"}, "finish_reason": "length" if rejected else "stop"}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3},
        }),
    )
    def call():
        with service._planning_usage_scope(work["id"], "work", work["id"], workflow, provider, {"synthetic": True}):
            provider._call_llm("synthetic", "synthetic")
    if rejected:
        with pytest.raises(DomainError):
            call()
    else:
        call()
    run = service.get_work(work["id"])["agent_runs"][-1]
    assert run["status"] == ("failed" if rejected else "completed")
    receipts = service.request_ledger.for_run(work["id"], run["id"])
    assert receipts["summary"]["physical_request_count"] == 1
    assert receipts["summary"]["totals"]["input_tokens"] == 12
    assert receipts["summary"]["totals"]["output_tokens"] == 3
    assert "SECRET-KEY" not in json.dumps(receipts)
    assert service.agent_usage(work["id"])["physical_request_count"] == 1
    service.close()
