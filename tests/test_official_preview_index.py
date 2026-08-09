import json
from pathlib import Path

from PIL import Image

from official_catalog import CatalogBundleLocation
from official_preview_index import (
    BundleImage,
    OfficialPreviewIndex,
)


def _catalog_and_cache(tmp_path):
    catalog = tmp_path / "catalog.json"
    catalog.write_text('{"version":1}', encoding="utf-8")
    cache = tmp_path / "cache"
    cache.mkdir()
    return catalog, cache


def _location(cache, internal_id, bundle_name):
    data = cache / bundle_name / "content" / "__data"
    data.parent.mkdir(parents=True, exist_ok=True)
    data.write_bytes(b"UnityFS" + bundle_name.encode("ascii"))
    return CatalogBundleLocation(
        internal_id=internal_id,
        bundle_name=bundle_name,
        content_hash="content",
        data_path=data,
    )


def _install_locations(monkeypatch, backgrounds, avatars):
    import official_preview_index

    def locations(_catalog, _cache, *, internal_predicate):
        selected = [
            row
            for row in (*backgrounds, *avatars)
            if internal_predicate(row.internal_id)
        ]
        return tuple(selected)

    monkeypatch.setattr(
        official_preview_index,
        "catalog_bundle_locations",
        locations,
    )


def _fixtures(tmp_path, monkeypatch):
    catalog, cache = _catalog_and_cache(tmp_path)
    backgrounds = (
        _location(
            cache,
            "{URL}/defaultlocalgroup_assets_uis/03_scenario/"
            "01_background/bg_classroom.jpg.bundle",
            "bg-classroom",
        ),
        _location(
            cache,
            "{URL}/defaultlocalgroup_assets_uis/03_scenario/"
            "01_background/bg_hall.png.bundle",
            "bg-hall",
        ),
    )
    avatars = (
        _location(
            cache,
            "{URL}/avatars_assets_all.bundle",
            "avatars",
        ),
    )
    _install_locations(monkeypatch, backgrounds, avatars)
    return catalog, cache, backgrounds, avatars


def test_index_state_is_not_built_before_manifest_exists(tmp_path):
    catalog, cache = _catalog_and_cache(tmp_path)
    store = OfficialPreviewIndex(tmp_path / "previews")

    state = store.state(catalog, cache)

    assert state.status == "not_built"
    assert state.backgrounds == 0
    assert state.avatars == 0


def test_build_extracts_fixed_size_backgrounds_and_avatars(
    tmp_path,
    monkeypatch,
):
    catalog, cache, backgrounds, avatars = _fixtures(
        tmp_path, monkeypatch
    )
    images = {
        backgrounds[0].data_path: [
            BundleImage("BG_Classroom", Image.new("RGB", (640, 240), "red"))
        ],
        backgrounds[1].data_path: [
            BundleImage("BG_Hall", Image.new("RGB", (100, 300), "blue"))
        ],
        avatars[0].data_path: [
            BundleImage(
                "Student_Portrait_Hifumi",
                Image.new("RGBA", (80, 120), "green"),
            ),
            BundleImage(
                "Student_Portrait_Hifumi",
                Image.new("RGBA", (80, 120), "blue"),
                asset_type="Sprite",
            ),
            BundleImage("Unrelated", Image.new("RGBA", (10, 10), "black")),
        ],
    }
    store = OfficialPreviewIndex(tmp_path / "previews")

    state = store.build(
        catalog,
        cache,
        bundle_loader=lambda path: images[path],
    )

    assert state.status == "ready"
    assert state.backgrounds == 2
    assert state.avatars == 1
    assert Image.open(
        store.resolve("background", "BG_Classroom")
    ).size == (320, 180)
    assert Image.open(
        store.resolve("avatar", "Student_Portrait_Hifumi")
    ).size == (160, 160)


def test_resolve_rejects_unknown_kind_and_traversal_keys(
    tmp_path,
    monkeypatch,
):
    catalog, cache, backgrounds, avatars = _fixtures(
        tmp_path, monkeypatch
    )
    images = {
        backgrounds[0].data_path: [
            BundleImage("BG_Classroom", Image.new("RGB", (20, 20)))
        ],
        backgrounds[1].data_path: [
            BundleImage("BG_Hall", Image.new("RGB", (20, 20)))
        ],
        avatars[0].data_path: [
            BundleImage(
                "Student_Portrait_Hifumi", Image.new("RGBA", (20, 20))
            )
        ],
    }
    store = OfficialPreviewIndex(tmp_path / "previews")
    store.build(catalog, cache, bundle_loader=lambda path: images[path])

    assert store.resolve("background", "BG_Classroom").is_file()
    assert store.resolve("background", "../../secret") is None
    assert store.resolve("avatar", "missing") is None
    assert store.resolve("sound", "BG_Classroom") is None


def test_resolve_reuses_manifest_parse_until_manifest_changes(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "previews"
    root.mkdir()
    output = root / "one.webp"
    Image.new("RGB", (20, 20)).save(output)
    manifest = {
        "schema_version": 1,
        "status": "ready",
        "fingerprint": "one",
        "counts": {"backgrounds": 1, "avatars": 0, "failed": 0},
        "records": [{
            "kind": "background",
            "key": "BG_One",
            "normalized_key": "bg_one",
            "path": "one.webp",
            "source_fingerprint": "one",
        }],
        "failures": [],
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    store = OfficialPreviewIndex(root)
    reads = 0
    original = Path.read_text

    def counted_read(path, *args, **kwargs):
        nonlocal reads
        if path == manifest_path:
            reads += 1
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counted_read)

    assert store.resolve("background", "BG_One") == output
    assert store.resolve("background", "BG_One") == output
    assert reads == 1


def test_failed_bundle_produces_partial_and_preserves_successes(
    tmp_path,
    monkeypatch,
):
    catalog, cache, backgrounds, avatars = _fixtures(
        tmp_path, monkeypatch
    )

    def loader(path):
        if path == backgrounds[1].data_path:
            raise ValueError("damaged bundle")
        if path == avatars[0].data_path:
            return [
                BundleImage(
                    "Student_Portrait_Hifumi",
                    Image.new("RGBA", (20, 20)),
                )
            ]
        return [BundleImage("BG_Classroom", Image.new("RGB", (20, 20)))]

    store = OfficialPreviewIndex(tmp_path / "previews")
    state = store.build(catalog, cache, bundle_loader=loader)

    assert state.status == "partial"
    assert state.backgrounds == 1
    assert state.avatars == 1
    assert state.failed == 1
    assert store.resolve("background", "BG_Classroom").is_file()
    manifest = json.loads(
        (store.root / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["schema_version"] == 1
    assert manifest["counts"] == {
        "backgrounds": 1,
        "avatars": 1,
        "failed": 1,
    }
    assert manifest["failures"]


def test_second_build_reuses_unchanged_source_bundles(
    tmp_path,
    monkeypatch,
):
    catalog, cache, backgrounds, avatars = _fixtures(
        tmp_path, monkeypatch
    )
    calls = []

    def loader(path):
        calls.append(path)
        if path == avatars[0].data_path:
            return [
                BundleImage(
                    "Student_Portrait_Hifumi",
                    Image.new("RGBA", (20, 20)),
                )
            ]
        name = "BG_Classroom" if path == backgrounds[0].data_path else "BG_Hall"
        return [BundleImage(name, Image.new("RGB", (20, 20)))]

    store = OfficialPreviewIndex(tmp_path / "previews")
    first = store.build(catalog, cache, bundle_loader=loader)
    calls.clear()
    second = store.build(catalog, cache, bundle_loader=loader)

    assert first.status == second.status == "ready"
    assert calls == []


def test_interrupted_first_build_resumes_from_atomic_manifest(
    tmp_path,
    monkeypatch,
):
    catalog, cache, backgrounds, avatars = _fixtures(
        tmp_path, monkeypatch
    )
    first_calls = []

    def interrupted_loader(path):
        first_calls.append(path)
        if path == backgrounds[1].data_path:
            raise KeyboardInterrupt()
        return [BundleImage("BG_Classroom", Image.new("RGB", (20, 20)))]

    store = OfficialPreviewIndex(tmp_path / "previews")
    try:
        store.build(catalog, cache, bundle_loader=interrupted_loader)
    except KeyboardInterrupt:
        pass
    manifest = json.loads(
        (store.root / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["status"] == "building"
    assert [row["key"] for row in manifest["records"]] == [
        "bg_classroom"
    ]
    assert store.state(catalog, cache).status == "building"

    resumed_calls = []

    def resumed_loader(path):
        resumed_calls.append(path)
        if path == avatars[0].data_path:
            return [
                BundleImage(
                    "Student_Portrait_Hifumi",
                    Image.new("RGBA", (20, 20)),
                )
            ]
        return [BundleImage("BG_Hall", Image.new("RGB", (20, 20)))]

    state = store.build(catalog, cache, bundle_loader=resumed_loader)

    assert state.status == "ready"
    assert backgrounds[0].data_path not in resumed_calls
    assert resumed_calls == [backgrounds[1].data_path, avatars[0].data_path]


def test_state_is_stale_when_catalog_fingerprint_changes(
    tmp_path,
    monkeypatch,
):
    catalog, cache, backgrounds, avatars = _fixtures(
        tmp_path, monkeypatch
    )

    def loader(path):
        if path == avatars[0].data_path:
            return [
                BundleImage(
                    "Student_Portrait_Hifumi",
                    Image.new("RGBA", (20, 20)),
                )
            ]
        return [BundleImage(Path(path).parent.parent.name, Image.new("RGB", (20, 20)))]

    store = OfficialPreviewIndex(tmp_path / "previews")
    store.build(catalog, cache, bundle_loader=loader)
    catalog.write_text('{"version":2}', encoding="utf-8")

    state = store.state(catalog, cache)

    assert state.status == "stale"
    assert state.backgrounds == 2
    assert state.avatars == 1
