from spine_face_inventory import discover_spine_inventory_candidates


def _bundle(root, stem, version="4.2.33"):
    folder = root / "characters" / stem
    folder.mkdir(parents=True)
    (folder / f"{stem}.skel").write_bytes(f"spine {version}".encode())
    (folder / f"{stem}.atlas").write_text(
        f"{stem}.png\nsize: 16,16\n", encoding="utf-8"
    )
    (folder / f"{stem}.png").write_bytes(b"png")
    return folder


def test_inventory_discovers_every_complete_bundle_across_source_roots(tmp_path):
    base = tmp_path / "base"
    extra = tmp_path / "extra"
    _bundle(base, "CharacterSpine_airi", "3.8.76")
    _bundle(extra, "CH0001_spr", "4.2.33")

    records, failures = discover_spine_inventory_candidates((
        ("official_base", base),
        ("extra_pack", extra),
    ))

    assert failures == ()
    assert {(row.source_kind, row.outfit_key, row.spine_version) for row in records} == {
        ("official_base", "CharacterSpine_airi", "3.8.76"),
        ("extra_pack", "CH0001_spr", "4.2.33"),
    }


def test_inventory_reports_incomplete_bundle_without_fabricating_record(tmp_path):
    root = tmp_path / "extra"
    folder = root / "characters" / "broken"
    folder.mkdir(parents=True)
    (folder / "broken.skel").write_bytes(b"spine 4.2.33")

    records, failures = discover_spine_inventory_candidates((("extra_pack", root),))

    assert records == ()
    assert failures[0]["reason"] == "invalid_spine_bundle"


def test_inventory_isolates_two_complete_bundles_sharing_one_directory(tmp_path):
    root = tmp_path / "extra"
    folder = root / "characters" / "shared"
    folder.mkdir(parents=True)
    for stem in ("first_spr", "second_spr"):
        (folder / f"{stem}.skel").write_bytes(b"spine 3.8.76")
        (folder / f"{stem}.atlas").write_text(
            f"{stem}.png\nsize: 16,16\n", encoding="utf-8"
        )
        (folder / f"{stem}.png").write_bytes(b"png")

    records, failures = discover_spine_inventory_candidates(
        (("extra_pack", root),),
        isolation_root=tmp_path / "isolated",
    )

    assert failures == ()
    assert {row.outfit_key for row in records} == {"first_spr", "second_spr"}
    assert all(row.evidence["isolated_source_dir"] for row in records)
