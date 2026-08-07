import contextlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import asset_catalog
import assetdb
import spine_face_labeler
import webui
from history_assets import HistoryAssetBrowser
from story_workspace import StoryContext


def _insert_asset(
    con, *, kind, key, name, digest, scope, source="history_import", metadata=None,
    install_path=None, registered_at="",
):
    payload = {**({"catalog_source": source} if source is not None else {}), **(metadata or {})}
    con.execute(
        """
        INSERT INTO asset_install
          (kind,aa_key,display_name,source_path,sha256,scope,install_path,status,
           metadata_json,registered_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            kind, str(key), name, rf"C:\private\source\{name}", digest,
            scope, str(install_path or rf"C:\private\installed\{name}"), "registered",
            json.dumps(payload, ensure_ascii=False),
            registered_at,
        ),
    )
    con.commit()


def library_fixture(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    asset_catalog.migrate(con)
    first = tmp_path / "aa-data" / "projects" / "系列A-第一章"
    second = tmp_path / "aa-data" / "projects" / "系列A-第二章"
    first_preview = first / "bgs" / "rain.png"
    second_preview = second / "bgs" / "rain.png"
    first_preview.parent.mkdir(parents=True)
    second_preview.parent.mkdir(parents=True)
    first_preview.write_bytes(b"first-rain")
    second_preview.write_bytes(b"second-rain")
    _insert_asset(
        con, kind="background", key="rain_roof", name="雨夜天台", digest="digest-001",
        scope=str(first), metadata={"width": 1920, "height": 1080}, install_path=first_preview,
    )
    _insert_asset(
        con, kind="background", key="rain_roof", name="雨夜天台", digest="digest-001",
        scope=str(second), install_path=second_preview,
    )
    current = StoryContext(
        story_token="story-current", project="系列A-第二章", project_dir=second,
        save_dir=tmp_path / "aa-data" / "saves" / "系列A-第二章", source_path=None,
        latest_draft_token=None, bgm_default={},
    )
    return con, current, HistoryAssetBrowser(aa_data=tmp_path / "aa-data")


def mixed_source_library_fixture(tmp_path):
    con, current, browser = library_fixture(tmp_path)
    scope = str(current.project_dir)
    _insert_asset(con, kind="sound", key="official", name="官方音效", digest="official", scope=scope, source="observed")
    _insert_asset(con, kind="sound", key="verified", name="验证音效", digest="verified", scope=scope, source="verified")
    _insert_asset(con, kind="bgm", key="theme", name="主题曲", digest="theme", scope=scope)
    return con, current, browser


def test_library_groups_custom_copies_and_marks_current_story(tmp_path):
    """Dropping tokenized copy state or current-scope matching would break the workbench contract."""
    con, current, browser = library_fixture(tmp_path)

    payload = browser.list_library(con, current_context=current)
    rain = payload["backgrounds"][0]

    assert rain["name"] == "雨夜天台"
    assert rain["registered_in_current"] is True
    assert rain["copy_count"] == 2
    assert all(copy["copy_token"].startswith("copy-") for copy in rain["copies"])
    assert "scope" not in repr(payload)
    assert str(tmp_path) not in repr(payload)


def test_library_aggregates_first_import_and_latest_used_chapter(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    asset_catalog.migrate(con)
    first = tmp_path / "projects" / "Chapter A"
    second = tmp_path / "projects" / "Chapter B"
    first_preview = first / "bgs" / "rain.png"
    second_preview = second / "bgs" / "rain.png"
    first_preview.parent.mkdir(parents=True)
    second_preview.parent.mkdir(parents=True)
    first_preview.write_bytes(b"rain")
    second_preview.write_bytes(b"rain")
    _insert_asset(
        con, kind="background", key="rain", name="Rain", digest="same-digest",
        scope=str(first), install_path=first_preview,
        registered_at="2026-08-01T02:00:00Z",
    )
    _insert_asset(
        con, kind="background", key="rain", name="Rain", digest="same-digest",
        scope=str(second), install_path=second_preview,
        registered_at="2026-08-07T05:30:00Z",
    )
    current = StoryContext(
        story_token="story-b", project="Chapter B", project_dir=second,
        save_dir=tmp_path / "saves" / "Chapter B", source_path=None,
        latest_draft_token=None, bgm_default={},
    )

    item = HistoryAssetBrowser(aa_data=tmp_path).list_library(
        con, current_context=current
    )["backgrounds"][0]

    assert item["imported_at"] == "2026-08-01T02:00:00Z"
    assert item["last_used_at"] == "2026-08-07T05:30:00Z"
    assert item["last_used_chapter"] == "Chapter B"
    assert {
        copy["chapter"]: copy["registered_at"] for copy in item["copies"]
    } == {
        "Chapter A": "2026-08-01T02:00:00Z",
        "Chapter B": "2026-08-07T05:30:00Z",
    }


def test_library_legacy_copy_times_are_publicly_unknown(tmp_path):
    con, current, browser = library_fixture(tmp_path)

    item = browser.list_library(con, current_context=current)["backgrounds"][0]

    assert item["imported_at"] == ""
    assert item["last_used_at"] == ""
    assert item["last_used_chapter"] == ""
    assert all(copy["registered_at"] == "" for copy in item["copies"])


def test_library_rejects_invalid_or_timezone_free_registration_times(tmp_path):
    assert asset_catalog._safe_iso_timestamp("not-a-date") == ""
    assert asset_catalog._safe_iso_timestamp("2026-08-07T05:30:00") == ""
    assert asset_catalog._safe_iso_timestamp("2026-08-07T13:30:00+08:00") == (
        "2026-08-07T05:30:00Z"
    )


def test_library_excludes_observed_verified_and_bgm_rows(tmp_path):
    """Treating observed/verified catalog records as reusable custom assets leaks built-ins into the library."""
    con, current, browser = mixed_source_library_fixture(tmp_path)

    payload = browser.list_library(con, current_context=current)

    assert payload["counts"] == {
        "characters": 0, "backgrounds": 1, "sounds": 0, "bgms": 0,
    }


def test_library_accepts_legacy_registered_rows_without_a_catalog_source(tmp_path):
    """Dropping legacy source-less registrations would empty upgraded material libraries."""
    con, current, browser = library_fixture(tmp_path)
    scope = str(current.project_dir)
    _insert_asset(
        con, kind="background", key="legacy", name="Legacy custom background",
        digest="legacy-digest", scope=scope, source=None,
    )
    for index, source in enumerate(("builtin", "database", "library")):
        _insert_asset(
            con, kind="background", key=f"excluded-{index}", name=f"排除-{index}",
            digest=f"excluded-{index}", scope=scope, source=source,
        )

    payload = browser.list_library(con, current_context=current)

    assert {row["aa_key"] for row in payload["backgrounds"]} == {"rain_roof", "legacy"}
    assert all(
        copy["copy_token"].startswith("copy-")
        for row in payload["backgrounds"]
        for copy in row["copies"]
    )
    assert all("excluded" not in repr(row) for row in payload["backgrounds"])


def test_upserted_custom_candidate_is_explicitly_marked_for_library(tmp_path):
    """Writing a new registered import without a source would make it indistinguishable from legacy catalog data."""
    con = assetdb.connect(tmp_path / "assets.db")
    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    asset_catalog.upsert_candidate(
        con, asset_catalog.AssetCandidate("background", source, "new", "new", "new-digest"),
        scope=str(tmp_path / "project"), status="registered", install_path=str(source),
    )

    row = con.execute("SELECT metadata_json FROM asset_install WHERE aa_key='new'").fetchone()

    assert json.loads(row["metadata_json"])["catalog_source"] == "custom"


def test_registered_asset_gets_server_time_and_upsert_preserves_it(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    candidate = asset_catalog.AssetCandidate(
        "background", source, "new", "new", "new-digest"
    )

    asset_catalog.upsert_candidate(
        con, candidate, scope=str(tmp_path / "project"), status="registered",
        install_path=str(source),
    )
    initial = con.execute(
        "SELECT registered_at FROM asset_install WHERE aa_key='new'"
    ).fetchone()["registered_at"]

    assert initial.endswith("Z")
    asset_catalog.upsert_candidate(
        con, candidate, scope=str(tmp_path / "project"), status="registered",
        install_path=str(source),
    )
    assert con.execute(
        "SELECT registered_at FROM asset_install WHERE aa_key='new'"
    ).fetchone()["registered_at"] == initial


def test_legacy_registered_asset_keeps_unknown_time_after_migration(tmp_path):
    con = assetdb.connect(tmp_path / "legacy.db")
    con.executescript(
        """
        CREATE TABLE asset_install (
            kind TEXT NOT NULL,
            aa_key TEXT NOT NULL,
            display_name TEXT,
            source_path TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            scope TEXT NOT NULL,
            install_path TEXT,
            status TEXT NOT NULL,
            error TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            PRIMARY KEY (kind, aa_key, scope)
        );
        INSERT INTO meta(key,value) VALUES('asset_schema_version','1')
        ON CONFLICT(key) DO UPDATE SET value=excluded.value;
        """
    )
    con.execute(
        """
        INSERT INTO asset_install
          (kind,aa_key,display_name,source_path,sha256,scope,install_path,status,metadata_json)
        VALUES ('background','legacy','Legacy','source.png','digest','Old Chapter',
                'installed.png','registered','{"catalog_source":"custom"}')
        """
    )
    con.commit()

    asset_catalog.migrate(con)

    assert con.execute(
        "SELECT registered_at FROM asset_install WHERE aa_key='legacy'"
    ).fetchone()["registered_at"] == ""


def test_status_transition_to_registered_sets_server_time(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    source = tmp_path / "source.wav"
    source.write_bytes(b"sound")
    candidate = asset_catalog.AssetCandidate(
        "sound", source, "door", "door", "door-digest"
    )
    scope = str(tmp_path / "project")
    asset_catalog.upsert_candidate(
        con, candidate, scope=scope, status="validated", install_path=str(source)
    )

    asset_catalog.set_asset_status(
        con, kind="sound", aa_key="door", scope=scope, status="registered"
    )

    assert con.execute(
        "SELECT registered_at FROM asset_install WHERE aa_key='door'"
    ).fetchone()["registered_at"].endswith("Z")


@contextlib.contextmanager
def _server(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "DB", str(tmp_path / "assets.db"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), webui.H)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def _post(base, path, payload):
    request = Request(
        base + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request) as response:
            return response.status, json.loads(response.read())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _patch(base, path, payload):
    request = Request(
        base + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="PATCH",
    )
    try:
        with urlopen(request) as response:
            return response.status, json.loads(response.read())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_library_groups_custom_copies_by_content_without_exposing_paths(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    asset_catalog.migrate(con)
    first = str(tmp_path / "projects" / "系列A-第一章")
    second = str(tmp_path / "projects" / "系列A-第二章")
    _insert_asset(
        con, kind="background", key="101", name="雨夜天台", digest="a" * 64,
        scope=first,
        metadata={
            "width": 1920, "height": 1080,
            "labels": {"place": "天台", "usage": str(tmp_path / "private-label")},
        },
    )
    _insert_asset(
        con, kind="background", key="101", name="雨夜天台", digest="a" * 64,
        scope=second,
    )
    _insert_asset(
        con, kind="sound", key="SE_Official", name="内置门铃", digest="b" * 64,
        scope=first, source="verified",
    )

    result = asset_catalog.list_library_assets(con)

    assert result["counts"] == {
        "characters": 0, "backgrounds": 1, "sounds": 0, "bgms": 0,
    }
    assert result["backgrounds"][0]["chapters"] == ["系列A-第一章", "系列A-第二章"]
    assert result["backgrounds"][0]["copy_count"] == 2
    assert result["backgrounds"][0]["details"] == {
        "resolution": "1920×1080", "labels": {"place": "天台"},
        "label_status": "not_labeled", "label_error": "", "labels_updated_at": "",
    }
    encoded = json.dumps(result, ensure_ascii=False)
    assert str(tmp_path) not in encoded
    assert "private" not in encoded.casefold()
    assert not {"source_path", "install_path", "scope"} & set(result["backgrounds"][0])


def test_library_profile_persists_series_classification_and_requires_series_name(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    asset_catalog.migrate(con)
    _insert_asset(
        con, kind="character", key="kei-date", name="凯伊约会服",
        digest="c" * 64, scope=str(tmp_path / "projects" / "约会篇-第一章"),
        metadata={"expression_status": "known", "faces": [{"id": "00"}]},
    )

    with pytest.raises(ValueError, match="系列名称"):
        asset_catalog.update_library_profile(
            con, kind="character", aa_key="kei-date", sha256="c" * 64,
            asset_role="series_shared", series_name="",
        )

    saved = asset_catalog.update_library_profile(
        con, kind="character", aa_key="kei-date", sha256="c" * 64,
        asset_role="series_shared", series_name="  凯伊约会篇  ",
    )
    result = asset_catalog.list_library_assets(con)

    assert saved["series_name"] == "凯伊约会篇"
    assert result["characters"][0]["asset_role"] == "series_shared"
    assert result["characters"][0]["series_name"] == "凯伊约会篇"
    assert result["characters"][0]["details"]["face_count"] == 1


def test_character_library_counts_files_semantic_faces_and_saved_labels(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    asset_catalog.migrate(con)
    _insert_asset(
        con,
        kind="character",
        key="kei-date",
        name="凯伊约会服",
        digest="9" * 64,
        scope=str(tmp_path / "projects" / "约会篇"),
        metadata={
            "files": {"skel": "a.skel", "atlas": "a.atlas", "texture": "a.png", "avatar": "avatar.png"},
            "faces": [],
            "semantic_face_count": 44,
            "expression_status": "known",
            "spine_signature": "sig-date",
            "outfit_key": "date",
        },
    )
    con.execute(
        """
        INSERT INTO face_visual_label
          (ident,spine_signature,outfit_key,face_id,model,primary_emotion,secondary_json)
        VALUES ('kei-date','sig-date','date','00','vision-model','平静','[]')
        """
    )
    con.commit()

    details = asset_catalog.list_library_assets(con)["characters"][0]["details"]

    assert details["file_count"] == 4
    assert details["face_count"] == 44
    assert details["labeled_count"] == 1
    assert details["expression_status"] == "known"


def test_library_api_includes_visual_label_summary_without_inventing_face_count(
    tmp_path, monkeypatch,
):
    con = assetdb.connect(tmp_path / "assets.db")
    asset_catalog.migrate(con)
    _insert_asset(
        con,
        kind="character",
        key="hero-id",
        name="Custom hero",
        digest="6" * 64,
        scope=str(tmp_path / "projects" / "chapter-one"),
        metadata={"spine_signature": "sig-hero", "outfit_key": "school"},
    )
    _insert_asset(
        con,
        kind="character",
        key="known-unlabeled",
        name="Known unlabeled hero",
        digest="5" * 64,
        scope=str(tmp_path / "projects" / "chapter-two"),
        metadata={
            "files": {
                "skel": "hero.skel",
                "atlas": "hero.atlas",
                "texture": "hero.png",
                "avatar": "avatar.png",
            },
            "semantic_face_count": 44,
            "expression_status": "known",
            "spine_signature": "sig-unlabeled",
            "outfit_key": "default",
        },
    )
    con.executemany(
        """
        INSERT INTO face_visual_label
          (ident,spine_signature,outfit_key,face_id,model,primary_emotion,
           secondary_json,updated_at)
        VALUES ('hero-id','sig-hero','school','00',?,?,'[]',?)
        """,
        [
            ("vision-a", "calm", "2026-08-03 12:00:00"),
            ("vision-b", "focused", "2026-08-03 13:00:00"),
        ],
    )
    con.commit()
    con.close()

    with _server(tmp_path, monkeypatch) as base:
        with urlopen(base + "/api/assets/library") as response:
            payload = json.loads(response.read())

    characters = {str(item["aa_key"]): item for item in payload["characters"]}
    unknown = characters["hero-id"]["details"]
    unlabeled = characters["known-unlabeled"]["details"]

    assert unknown["face_count"] is None
    assert unknown["labeled_count"] == 1
    assert unknown["labels_updated_at"] == "2026-08-03 13:00:00"
    assert unlabeled == {
        "expression_status": "known",
        "expression_mode": "opaque_custom",
        "file_count": 4,
        "face_count": 44,
        "labeled_count": 0,
        "labels_updated_at": "",
    }
    assert str(tmp_path) not in json.dumps(payload, ensure_ascii=False)


def test_face_label_payload_is_path_safe_and_supports_versioned_edits(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    asset_catalog.migrate(con)
    installed = tmp_path / "projects" / "date" / "characters" / "kei-date"
    installed.mkdir(parents=True)
    head = tmp_path / "cache" / "heads" / "00.png"
    head.parent.mkdir(parents=True)
    head.write_bytes(b"png-preview")
    _insert_asset(
        con,
        kind="character",
        key="kei-date",
        name="凯伊约会服",
        digest="8" * 64,
        scope=str(tmp_path / "projects" / "date"),
        install_path=installed,
        metadata={"spine_signature": "sig-date", "outfit_key": "date"},
    )
    spine_face_labeler.persist_visual_face_labels(
        con,
        ident="kei-date",
        spine_signature="sig-date",
        outfit_key="date",
        model="vision-model",
        labels=[{
            "face_id": "00", "primary_emotion": "平静", "secondary_emotions": [],
            "valence": "neutral", "arousal": "low", "eyes": "自然睁眼",
            "brows": "自然", "mouth": "闭嘴", "blush": False, "tears": False,
            "confidence": 0.92, "description_cn": "平静地注视前方", "head_path": str(head),
        }],
    )

    payload = webui.face_labels_payload(con, aa_key="kei-date", sha256="8" * 64)
    face = payload["faces"][0]

    assert face["face_id"] == "00"
    assert face["effective"]["primary_emotion"] == "平静"
    assert face["preview_url"].startswith("/api/assets/faces/preview?")
    assert f"v={face['version']}" in face["preview_url"]
    assert "head_path" not in json.dumps(payload, ensure_ascii=False)

    saved = webui.update_face_label_payload(
        con,
        aa_key="kei-date",
        sha256="8" * 64,
        face_id="00",
        patch={"primary_emotion": "认真"},
        expected_version=face["version"],
    )
    assert saved["face"]["effective"]["primary_emotion"] == "认真"
    assert saved["saved_count"] == 1
    assert saved["saved_at"]


def test_face_label_http_routes_read_and_patch_saved_records(tmp_path, monkeypatch):
    con = assetdb.connect(tmp_path / "assets.db")
    asset_catalog.migrate(con)
    installed = tmp_path / "projects" / "date" / "characters" / "kei-date"
    installed.mkdir(parents=True)
    head = tmp_path / "00.png"
    head.write_bytes(b"preview")
    _insert_asset(
        con, kind="character", key="kei-date", name="凯伊约会服",
        digest="7" * 64, scope=str(tmp_path / "projects" / "date"),
        install_path=installed,
        metadata={"spine_signature": "sig-date", "outfit_key": "date"},
    )
    spine_face_labeler.persist_visual_face_labels(
        con, ident="kei-date", spine_signature="sig-date", outfit_key="date",
        model="vision-model", labels=[{
            "face_id": "00", "primary_emotion": "平静", "secondary_emotions": [],
            "valence": "neutral", "arousal": "low", "eyes": "睁眼", "brows": "自然",
            "mouth": "闭嘴", "blush": False, "tears": False, "confidence": 0.9,
            "description_cn": "平静", "head_path": str(head),
        }],
    )
    con.close()

    query = "?aa_key=kei-date&sha256=" + "7" * 64
    with _server(tmp_path, monkeypatch) as base:
        with urlopen(base + "/api/assets/faces/labels" + query) as response:
            listed = json.loads(response.read())
        version = listed["faces"][0]["version"]
        status, saved = _patch(
            base,
            "/api/assets/faces/labels/00",
            {"aa_key": "kei-date", "sha256": "7" * 64,
             "version": version, "patch": {"primary_emotion": "认真"}},
        )

    assert status == 200
    assert saved["face"]["effective"]["primary_emotion"] == "认真"


def test_library_profile_rejects_builtin_registered_rows(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    asset_catalog.migrate(con)
    _insert_asset(
        con, kind="background", key="99", name="官方教室", digest="d" * 64,
        scope=str(tmp_path / "projects" / "第一章"), source="observed",
    )

    with pytest.raises(KeyError):
        asset_catalog.update_library_profile(
            con, kind="background", aa_key="99", sha256="d" * 64,
            asset_role="chapter_only", series_name="",
        )


def test_character_face_analysis_target_uses_only_installed_custom_copy(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    asset_catalog.migrate(con)
    installed = tmp_path / "projects" / "第一章" / "characters" / "hero-id"
    installed.mkdir(parents=True)
    _insert_asset(
        con, kind="character", key="hero-id", name="主角骨骼",
        digest="1" * 64, scope=str(tmp_path / "projects" / "第一章"),
        metadata={"spine_signature": "sig-1", "outfit_key": "school"},
    )
    con.execute(
        "UPDATE asset_install SET install_path=? WHERE kind='character' AND aa_key='hero-id'",
        (str(installed),),
    )
    con.commit()

    target = asset_catalog.library_character_analysis_target(
        con, aa_key="hero-id", sha256="1" * 64
    )

    assert target == {
        "source": str(installed), "ident": "hero-id", "name": "主角骨骼",
        "spine_signature": "sig-1", "outfit_key": "school",
    }


def test_concurrent_face_preview_resolution_skips_completed_migration(
    tmp_path, monkeypatch,
):
    database = tmp_path / "assets.db"
    con = assetdb.connect(database)
    asset_catalog.migrate(con)
    installed = tmp_path / "projects" / "第一章" / "characters" / "hero-id"
    installed.mkdir(parents=True)
    _insert_asset(
        con,
        kind="character",
        key="hero-id",
        name="主角骨骼",
        digest="2" * 64,
        scope=str(tmp_path / "projects" / "第一章"),
        install_path=installed,
        metadata={"spine_signature": "sig-2", "outfit_key": "school"},
    )
    con.close()
    migration_calls = 0
    visual_migration_calls = 0
    calls_lock = threading.Lock()
    original = assetdb.migrate_face_evidence
    original_visual = assetdb.migrate_visual_face_labels

    def counted_migration(connection):
        nonlocal migration_calls
        with calls_lock:
            migration_calls += 1
        return original(connection)

    def counted_visual_migration(connection):
        nonlocal visual_migration_calls
        with calls_lock:
            visual_migration_calls += 1
        return original_visual(connection)

    monkeypatch.setattr(assetdb, "migrate_face_evidence", counted_migration)
    monkeypatch.setattr(
        assetdb, "migrate_visual_face_labels", counted_visual_migration
    )

    def resolve_target(_index):
        connection = assetdb.connect(database)
        try:
            return asset_catalog.library_character_analysis_target(
                connection, aa_key="hero-id", sha256="2" * 64
            )
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(resolve_target, range(16)))

    assert all(result["source"] == str(installed) for result in results)
    assert migration_calls == 0
    assert visual_migration_calls == 0


def test_library_api_lists_and_updates_safe_profiles(tmp_path, monkeypatch):
    con = assetdb.connect(tmp_path / "assets.db")
    asset_catalog.migrate(con)
    _insert_asset(
        con, kind="sound", key="敲门", name="敲门", digest="e" * 64,
        scope=str(tmp_path / "projects" / "第二章"),
        metadata={"duration": 1.25, "codec": "pcm_s16le"},
    )
    con.close()

    with _server(tmp_path, monkeypatch) as base:
        with urlopen(base + "/api/assets/library") as response:
            listed = json.loads(response.read())
        status, saved = _post(base, "/api/assets/library/profile", {
            "kind": "sound", "aa_key": "敲门", "sha256": "e" * 64,
            "asset_role": "series_shared", "series_name": "校园篇",
        })

    assert listed["counts"]["sounds"] == 1
    assert str(tmp_path) not in json.dumps(listed, ensure_ascii=False)
    assert status == 200
    assert saved == {
        "ok": True, "kind": "sound", "aa_key": "敲门",
        "sha256": "e" * 64, "asset_role": "series_shared",
        "series_name": "校园篇",
    }


def test_library_api_rejects_shared_profile_without_series_name(tmp_path, monkeypatch):
    con = assetdb.connect(tmp_path / "assets.db")
    asset_catalog.migrate(con)
    _insert_asset(
        con, kind="sound", key="敲门", name="敲门", digest="f" * 64,
        scope=str(tmp_path / "projects" / "第二章"),
    )
    con.close()

    with _server(tmp_path, monkeypatch) as base:
        status, body = _post(base, "/api/assets/library/profile", {
            "kind": "sound", "aa_key": "敲门", "sha256": "f" * 64,
            "asset_role": "series_shared", "series_name": "",
        })

    assert status == 400
    assert body["code"] == "invalid_library_profile"
    assert "系列名称" in body["e"]


def test_face_job_snapshot_never_exposes_server_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(webui, "FACE_JOB", {
        "running": False, "done": True, "ok": True, "phase": "complete",
        "message": "已完成", "current": 3, "total": 3, "log": ["渲染完成"],
        "contact_sheet": str(tmp_path / "cache" / "sheet.jpg"),
        "ident": "hero-id", "outfit_key": "school", "error": None,
        "result": {
            "rendered_count": 3, "refreshed_preview_count": 3,
            "render_cache": str(tmp_path / "cache"),
            "contact_sheet": str(tmp_path / "cache" / "sheet.jpg"),
            "vision_status": "labeled", "labeled_count": 3,
            "saved_count": 3, "failed_count": 1, "completed_at": "2026-08-03T15:00:00+00:00",
            "failures": [{
                "face_id": "04",
                "error": f"vision failed at {tmp_path / 'private' / '04.png'}",
                "head_path": str(tmp_path / "private" / "04.png"),
            }],
            "status": "partial", "actual_workers": 4,
            "retried_faces": ["03"], "fallback_workers": 1,
            "calibration": [{
                "face_id": "03", "status": "needs_manual_calibration",
                "attachment": "eyes", "slot": "Eyes",
                "reason": "missing_region_geometry:height",
                "path": str(tmp_path / "private" / "eyes.png"),
            }],
            "semantic_faces": [{
                "face_id": "03", "primary_emotion": "惊讶",
                "semantic_labels": ["惊讶", "意外"],
                "head_path": str(tmp_path / "private" / "03.png"),
            }],
        },
    })

    snapshot = webui.face_job_snapshot()

    assert "contact_sheet_available" not in snapshot
    assert snapshot["result"]["saved_count"] == 3
    assert snapshot["result"]["refreshed_preview_count"] == 3
    assert snapshot["result"]["completed_at"] == "2026-08-03T15:00:00+00:00"
    assert snapshot["result"]["status"] == "partial"
    assert snapshot["result"]["actual_workers"] == 4
    assert snapshot["result"]["retried_faces"] == ["03"]
    assert snapshot["result"]["fallback_workers"] == 1
    assert snapshot["result"]["failures"][0]["face_id"] == "04"
    assert "vision failed" in snapshot["result"]["failures"][0]["error"]
    assert "head_path" not in snapshot["result"]["failures"][0]
    assert snapshot["result"]["calibration"] == [{
        "face_id": "03", "status": "needs_manual_calibration",
        "attachment": "eyes", "slot": "Eyes",
        "reason": "missing_region_geometry:height",
    }]
    assert snapshot["result"]["semantic_faces"] == [{
        "face_id": "03", "primary_emotion": "惊讶",
        "semantic_labels": ["惊讶", "意外"],
    }]
    encoded = json.dumps(snapshot, ensure_ascii=False)
    assert str(tmp_path) not in encoded
    assert "render_cache" not in encoded


def test_face_job_exception_uses_failed_terminal_phase(monkeypatch):
    class Connection:
        def close(self):
            pass

    monkeypatch.setattr(webui, "FACE_JOB", {
        "running": True, "done": False, "ok": False, "phase": "rendering",
        "message": "", "current": 0, "total": 1, "log": [],
        "contact_sheet": None, "result": None, "error": None,
    })
    monkeypatch.setattr(webui, "db", lambda: Connection())
    monkeypatch.setattr(webui, "_optional_vision_provider", lambda: (None, None))
    monkeypatch.setattr(
        webui.spine_face_analysis,
        "analyze_character_faces",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("render crashed")),
    )

    webui.run_face_job({
        "source": "source", "ident": "hero", "spine_cli": "Spine.com",
    })

    snapshot = webui.face_job_snapshot()
    assert snapshot["done"] is True
    assert snapshot["ok"] is False
    assert snapshot["phase"] == "failed"


def test_face_job_missing_key_message_describes_the_current_task(monkeypatch):
    class Connection:
        def close(self):
            pass

    monkeypatch.setattr(webui, "FACE_JOB", {
        "running": True, "done": False, "ok": False, "phase": "queued",
        "message": "", "current": 0, "total": None, "log": [],
        "contact_sheet": None, "result": None, "error": None,
    })
    monkeypatch.setattr(webui, "db", lambda: Connection())
    monkeypatch.setattr(
        webui,
        "_optional_vision_provider",
        lambda: (None, "所选模型配置尚未设置 API Key"),
    )
    monkeypatch.setattr(
        webui.spine_face_analysis,
        "analyze_character_faces",
        lambda *args, **kwargs: {
            "ok": True, "status": "complete", "rendered_count": 2,
            "vision_status": "skipped_missing_key",
        },
    )

    webui.run_face_job({
        "source": "source", "ident": "hero", "spine_cli": "Spine.com",
    })

    snapshot = webui.face_job_snapshot()
    assert snapshot["ok"] is True
    assert any(
        message == (
            "当前任务未读取到模型密钥；保存配置后请重新开始任务。"
            "本次仍会完成渲染和语义命名解析"
        )
        for message in snapshot["log"]
    )
