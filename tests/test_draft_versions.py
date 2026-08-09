# -*- coding: utf-8 -*-
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pytest
from draft_store import DraftStore, RevisionConflictError


@pytest.fixture
def temp_draft_dir(tmp_path):
    store_dir = tmp_path / "drafts"
    return DraftStore(base_dir=str(store_dir))


def test_cas_version_conflict(temp_draft_dir):
    store = temp_draft_dir
    token = "cas-token-1"
    sample_text = "## 场景1\n凯伊: 第一句\n"

    draft = store.create_draft(token=token, text=sample_text)
    assert draft["session"]["draft_version"] == 1
    assert draft["session"]["content_revision"] == 1

    # 传入错误的 expected_draft_version (例如 999) 应该抛出 RevisionConflictError
    with pytest.raises(RevisionConflictError):
        store.update_card_review(
            token=token,
            card_id=draft["identities"][1]["card_id"],
            review_state="approved",
            expected_draft_version=999,
        )


def test_review_only_change_increments_only_draft_version(temp_draft_dir):
    store = temp_draft_dir
    token = "cas-token-2"
    sample_text = "## 场景1\n凯伊: 第一句\n"

    draft = store.create_draft(token=token, text=sample_text)
    card_id = draft["identities"][1]["card_id"]

    # 纯审查更新 (approved)
    res = store.update_card_review(
        token=token,
        card_id=card_id,
        review_state="approved",
        expected_draft_version=1,
    )
    # draft_version 变为 2，content_revision 保持 1
    assert res["session"]["draft_version"] == 2
    assert res["session"]["content_revision"] == 1


def test_content_change_increments_both_versions(temp_draft_dir):
    store = temp_draft_dir
    token = "cas-token-3"
    sample_text = "## 场景1\n凯伊: 第一句\n"

    draft = store.create_draft(token=token, text=sample_text)

    # 内容改动
    res = store.update_draft_content(
        token=token,
        new_text="## 场景1\n凯伊: 修改后的第一句！\n",
        expected_draft_version=1,
        is_content_change=True,
    )
    # draft_version 变为 2，content_revision 变为 2
    assert res["session"]["draft_version"] == 2
    assert res["session"]["content_revision"] == 2


def test_concurrent_same_version_writes_yield_one_success_and_one_cas_conflict(temp_draft_dir):
    """Removing the per-draft critical section lets equal-version writers race."""
    store = temp_draft_dir
    token = "cas-concurrent"
    draft = store.create_draft(token=token, text="## 场景1\n凯伊: 原文\n")
    card_id = draft["identities"][1]["card_id"]
    start = threading.Barrier(3)
    outcomes = []
    outcomes_lock = threading.Lock()

    def update():
        start.wait(timeout=3)
        try:
            store.update_card_review(
                token=token,
                card_id=card_id,
                review_state="approved",
                expected_draft_version=1,
            )
            outcome = "success"
        except Exception as exc:
            outcome = type(exc)
        with outcomes_lock:
            outcomes.append(outcome)

    workers = [threading.Thread(target=update) for _ in range(2)]
    for worker in workers:
        worker.start()
    start.wait(timeout=3)
    for worker in workers:
        worker.join(timeout=3)

    assert outcomes.count("success") == 1
    assert outcomes.count(RevisionConflictError) == 1
