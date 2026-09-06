"""SourceCatalog's immutable input files must survive a writing backup."""

import base64
import io
import json
import zipfile

import pytest

from halocue_writing.errors import DomainError

from halocue_writing.service import WritingService


def add_source(service, work_id, text, **options):
    payload = {
        "filename": "synthetic.txt",
        "content_base64": base64.b64encode(text.encode("utf-8")).decode("ascii"),
        **options,
    }
    preview = service.sources.preview(work_id, payload)
    return service.sources.apply(work_id, {**payload, "preview_digest": preview["preview_digest"]})[
        "source"
    ]


def test_source_backup_restores_original_and_normalized_files_for_all_versions(tmp_path):
    source = WritingService(tmp_path / "source")
    work = source.create_work({"title": "Synthetic source history"})
    first = add_source(source, work["id"], "第一章 起点\n老师：第一段。")
    second = add_source(
        source, work["id"], "第二章 继续\n老师：下一段。", base_version_id=first["id"]
    )
    expected_files = {
        item[field]: (source.repo.data_dir / item[field]).read_bytes()
        for item in (first, second)
        for field in ("original_uri", "normalized_uri")
    }
    _, content, summary = source.export_writing_backup()
    target = WritingService(tmp_path / "target")
    restored = target.restore_writing_backup(
        {
            "content_base64": base64.b64encode(content).decode("ascii"),
            "expected_backup_hash": summary["backup_hash"],
            "replace_all_works": True,
        }
    )

    assert restored["restored"] is True
    assert target.sources.get(work["id"])["id"] == second["id"]
    for item in (first, second):
        assert target.sources.get(work["id"], item["id"])["chapters"] == item["chapters"]
    for uri, data in expected_files.items():
        destination = target.repo.data_dir / uri
        assert destination.is_file(), f"Backup omitted {uri}"
        assert destination.read_bytes() == data


@pytest.mark.parametrize("field", ["original_uri", "normalized_uri"])
def test_source_backup_rejects_manifest_consistent_but_incomplete_old_archive(tmp_path, field):
    service = WritingService(tmp_path / "source")
    work = service.create_work({"title": "Missing source input"})
    version = add_source(service, work["id"], "老师：这是合成来源。")
    _, complete, _ = service.export_writing_backup()
    omitted = "data/" + version[field]
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(complete)) as original:
        manifest = json.loads(original.read("manifest.json"))
        manifest["files"] = [item for item in manifest["files"] if item["path"] != omitted]
        manifest["file_count"] = len(manifest["files"])
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for entry in original.infolist():
                if entry.filename not in {omitted, "manifest.json"}:
                    archive.writestr(entry, original.read(entry.filename))
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))

    with pytest.raises(DomainError) as captured:
        service.inspect_writing_backup(
            {"content_base64": base64.b64encode(output.getvalue()).decode("ascii")}
        )

    assert captured.value.code == "backup_reference_missing"
    assert version[field] in captured.value.message


def test_export_refuses_to_claim_completeness_when_source_file_is_missing(tmp_path):
    service = WritingService(tmp_path / "writing")
    work = service.create_work({"title": "Damaged source input"})
    version = add_source(service, work["id"], "老师：这是合成来源。")
    missing = service.repo.data_dir / version["normalized_uri"]
    missing.unlink()

    with pytest.raises(DomainError) as captured:
        service.export_writing_backup()

    assert captured.value.code == "backup_reference_missing"


def test_backup_without_source_catalog_table_remains_restorable(tmp_path):
    legacy = WritingService(tmp_path / "legacy")
    work = legacy.create_work({"title": "Pre-source-catalog backup"})
    # Model the older format with no source catalog schema, not a corrupt
    # modern backup that references files it failed to include.
    with legacy.repo.transaction() as connection:
        connection.execute("DROP TABLE work_sources")
        connection.execute("DROP TABLE source_versions")
    _, content, summary = legacy.export_writing_backup()
    restored = WritingService(tmp_path / "restored")
    result = restored.restore_writing_backup(
        {
            "content_base64": base64.b64encode(content).decode("ascii"),
            "expected_backup_hash": summary["backup_hash"],
            "replace_all_works": True,
        }
    )

    assert result["restored"] is True
    assert restored.get_work(work["id"])["title"] == "Pre-source-catalog backup"
    assert restored.sources.get(work["id"]) is None
