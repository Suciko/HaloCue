from spine_face_browser import atlas_texture_files, bundle_files, detect_spine_version


def test_browser_bundle_resolves_version_and_all_atlas_pages(tmp_path):
    skeleton = tmp_path / "character.skel"
    atlas = tmp_path / "character.atlas"
    skeleton.write_bytes(b"hash\x00spine 4.2.33\x00payload")
    atlas.write_text(
        "page-a.png\nsize: 64,64\nformat: RGBA8888\n\npage-b.png\nsize: 32,32\nformat: RGBA8888\n",
        encoding="utf-8",
    )
    (tmp_path / "page-a.png").write_bytes(b"png")
    (tmp_path / "page-b.png").write_bytes(b"png")

    root, resolved_skeleton, resolved_atlas = bundle_files(tmp_path)

    assert root == tmp_path.resolve()
    assert resolved_skeleton == skeleton
    assert resolved_atlas == atlas
    assert detect_spine_version(skeleton) == "4.2.33"
    assert [name for name, _path in atlas_texture_files(root, atlas)] == [
        "page-a.png", "page-b.png",
    ]
