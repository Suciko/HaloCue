"""A work response cannot mix SQL reads from different committed versions."""

from halocue_writing.service import WritingService


def test_work_response_keeps_one_read_snapshot_during_concurrent_commit(tmp_path, monkeypatch):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "一致的作品快照", "world_seed": "blank"})
    work = service.save_brief(
        work["id"],
        {
            "expected_version": work["version"],
            "idea": "两名学生讨论归还借阅卡。",
            "intent_only": True,
        },
    )["work"]
    work = service.generate_blueprint(work["id"], {"expected_version": work["version"]})["work"]
    connect = service.repo.connect
    with connect() as connection:
        connection.execute("PRAGMA journal_mode=WAL")
    committed = False

    class CommitBetweenReads:
        def __init__(self):
            self.connection = connect()

        def __enter__(self):
            self.connection.__enter__()
            return self

        def __exit__(self, *args):
            try:
                return self.connection.__exit__(*args)
            finally:
                self.connection.close()

        def execute(self, sql, *args):
            nonlocal committed
            if not committed and "SELECT * FROM volumes WHERE" in sql:
                committed = True
                service.save_character_card(
                    work["id"],
                    {
                        "expected_version": work["version"],
                        "name": "学生甲",
                        "source_type": "custom",
                        "trust_status": "confirmed",
                        "source_refs": ["用户设定"],
                    },
                )
            return self.connection.execute(sql, *args)

        def __getattr__(self, name):
            return getattr(self.connection, name)

    monkeypatch.setattr(service.repo, "connect", CommitBetweenReads)
    response = service.get_work(work["id"])
    assert committed
    assert response["version"] == work["version"]
    assert response["harness"]["work_version"] == response["version"]
    assert not any(item["kind"] == "character_card" for item in response["artifacts"])
    latest = service.get_work(work["id"])
    assert latest["version"] == work["version"] + 1
    assert any(item["kind"] == "character_card" for item in latest["artifacts"])
    service.close()
