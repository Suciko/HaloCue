import json

import bundled_preview_seed


def _manifest(records):
    return {
        "schema_version": 1,
        "status": "ready",
        "fingerprint": "test",
        "records": records,
        "failures": [],
    }


def test_seed_repairs_missing_bundled_file_without_replacing_custom_records(tmp_path):
    seed = tmp_path / "seed"
    destination = tmp_path / "destination"
    bundled_file = seed / "avatars" / "official.webp"
    bundled_file.parent.mkdir(parents=True)
    bundled_file.write_bytes(b"official-preview")
    bundled_record = {
        "kind": "avatar",
        "key": "Student_Portrait_Test",
        "normalized_key": "student_portrait_test",
        "path": "avatars/official.webp",
        "source_fingerprint": "bundled",
    }
    (seed / "manifest.json").write_text(
        json.dumps(_manifest([bundled_record])), encoding="utf-8"
    )

    destination.mkdir()
    custom_record = {
        "kind": "avatar",
        "key": "custom",
        "normalized_key": "custom",
        "path": "avatars/custom.png",
        "source_fingerprint": "user",
    }
    stale_bundled_record = {**bundled_record, "path": "avatars/old.webp"}
    old_file = destination / "avatars" / "old.webp"
    old_file.parent.mkdir()
    old_file.write_bytes(b"old-preview")
    (destination / "manifest.json").write_text(
        json.dumps(_manifest([custom_record, stale_bundled_record])), encoding="utf-8"
    )

    copied = bundled_preview_seed.seed_bundled_previews(seed, destination)
    result = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))

    assert copied == 1
    assert (destination / "avatars" / "official.webp").read_bytes() == b"official-preview"
    assert custom_record in result["records"]
    repaired = next(
        row for row in result["records"]
        if row["normalized_key"] == "student_portrait_test"
    )
    assert repaired["path"] == "avatars/official.webp"
