"""Synthetic SQL-level regressions for idle polling and atomic lease claims."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from halocue_writing.repository import Repository
from halocue_writing.workspace_access import WorkspaceRecoveryRequired


def traced_connections(repo, monkeypatch):
    statements = []
    original = repo.connect

    def connect():
        connection = original()
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(repo, "connect", connect)
    return statements


@pytest.mark.parametrize("state", ["empty", "future", "cancelled", "running"])
def test_ineligible_queue_probe_never_starts_writer_transaction(tmp_path, monkeypatch, state):
    repo = Repository(tmp_path)
    if state != "empty":
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        job = repo.enqueue_agent_work(
            operation="synthetic", available_at=future if state == "future" else None
        )["job"]
        if state == "cancelled":
            repo.cancel_agent_work(job_id=job["id"])
        if state == "running":
            repo.claim_agent_work(lease_owner="already-running")
    statements = traced_connections(repo, monkeypatch)
    assert repo.claim_agent_work(lease_owner="idle") == {"claimed": False, "job": None}
    assert any("SELECT" in statement.upper() for statement in statements)
    assert not any(
        statement.upper().startswith(("BEGIN", "UPDATE", "INSERT", "DELETE"))
        for statement in statements
    )


def test_idle_probe_can_read_while_another_connection_holds_reserved_writer_lock(
    tmp_path, monkeypatch
):
    repo = Repository(tmp_path)
    original = repo.connect

    def connect():
        connection = original()
        connection.execute("PRAGMA busy_timeout=50")
        return connection

    monkeypatch.setattr(repo, "connect", connect)
    writer = sqlite3.connect(repo.db_path)
    try:
        writer.execute("BEGIN IMMEDIATE")
        assert repo.claim_agent_work(lease_owner="idle") == {"claimed": False, "job": None}
    finally:
        writer.rollback()
        writer.close()


def test_ready_claim_rechecks_under_writer_transaction(tmp_path, monkeypatch):
    repo = Repository(tmp_path)
    expected = repo.enqueue_agent_work(operation="synthetic")["job"]
    statements = traced_connections(repo, monkeypatch)
    claimed = repo.claim_agent_work(lease_owner="worker")
    assert claimed["claimed"] is True
    assert claimed["job"]["id"] == expected["id"]
    assert claimed["job"]["lease_owner"] == "worker"
    queries = [
        index
        for index, statement in enumerate(statements)
        if "SELECT ID FROM AGENT_DISPATCH_JOBS" in statement.upper()
    ]
    begin = next(
        index for index, statement in enumerate(statements) if statement == "BEGIN IMMEDIATE"
    )
    assert len(queries) == 2
    assert queries[0] < begin < queries[1]


def test_cancel_after_probe_is_rechecked_without_reviving_job(tmp_path, monkeypatch):
    repo = Repository(tmp_path)
    other = Repository(tmp_path)
    expected = repo.enqueue_agent_work(operation="synthetic")["job"]
    original_transaction = repo.transaction
    original_connect = repo.connect
    opened = []

    def connect():
        connection = original_connect()
        opened.append(connection)
        return connection

    @contextmanager
    def transaction():
        # The probe must be closed, not upgraded or kept as a stale read snapshot.
        assert opened
        for connection in opened:
            with pytest.raises(sqlite3.ProgrammingError):
                connection.execute("SELECT 1")
        other.cancel_agent_work(job_id=expected["id"])
        with original_transaction() as connection:
            yield connection

    monkeypatch.setattr(repo, "connect", connect)
    monkeypatch.setattr(repo, "transaction", transaction)
    assert repo.claim_agent_work(lease_owner="loser") == {"claimed": False, "job": None}


def test_two_claimers_still_award_only_one_lease(tmp_path, monkeypatch):
    first = Repository(tmp_path)
    second = Repository(tmp_path)
    expected = first.enqueue_agent_work(operation="synthetic")["job"]
    barrier = threading.Barrier(2)

    def synchronize_claims(repo):
        original = repo.transaction

        @contextmanager
        def transaction():
            # Both workers must pass the positive read probe before either can
            # acquire the write lock; exercise the stale-positive loser path.
            barrier.wait(timeout=5)
            with original() as connection:
                yield connection

        monkeypatch.setattr(repo, "transaction", transaction)

    for repo in (first, second):
        synchronize_claims(repo)

    def claim(pair):
        repo, owner = pair
        return repo.claim_agent_work(lease_owner=owner)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, [(first, "first"), (second, "second")]))
    winners = [result["job"] for result in results if result["claimed"]]
    assert len(winners) == 1
    assert winners[0]["id"] == expected["id"]
    assert winners[0]["lease_owner"] in {"first", "second"}


def test_idle_read_respects_incomplete_restore_marker(tmp_path):
    repo = Repository(tmp_path)
    repo.data_access.recovery_marker.write_text("{}", encoding="utf-8")
    with pytest.raises(WorkspaceRecoveryRequired):
        repo.claim_agent_work(lease_owner="idle")
