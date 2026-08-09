import io
import json

from PIL import Image

import asset_catalog
import assetdb
from asset_catalog import upsert_candidate
from asset_models import AssetCandidate
from background_labeler import label_background, normalize_background_labels


def _image(path, size=(48, 32), color=(40, 90, 160)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)


def _candidate(path, *, key="shared-bg", digest="same-digest"):
    return AssetCandidate(
        "background",
        path,
        path.stem,
        key,
        digest,
        metadata={"catalog_source": "custom", "width": 48, "height": 32},
    )


def test_normalize_background_labels_rejects_paths_and_bounds_semantics():
    labels = normalize_background_labels({
        "label": "  雨夜天台  ",
        "description": "C:\\Users\\private\\night.png",
        "place": "学校屋顶",
        "indoor_outdoor": "室外",
        "time": "夜晚",
        "weather": "小雨",
        "season": "",
        "mood": "安静",
        "tags": ["屋顶", "雨夜", "屋顶", "  城市灯光  ", "x" * 130],
        "ignored": "must not survive",
    })

    assert labels == {
        "label": "雨夜天台",
        "description": "",
        "place": "学校屋顶",
        "indoor_outdoor": "室外",
        "time": "夜晚",
        "weather": "小雨",
        "season": "",
        "mood": "安静",
        "tags": "屋顶, 雨夜, 城市灯光",
    }


def test_label_background_sends_a_bounded_jpeg_without_a_local_path(tmp_path):
    source = tmp_path / "private" / "large.png"
    _image(source, size=(2000, 1000))

    class Provider:
        def complete_json_vision(self, system, images, user, schema):
            self.system = system
            self.images = images
            self.user = user
            self.schema = schema
            return {
                "label": "商业街",
                "description": "带拱顶的步行商业街",
                "place": "商店街",
                "indoor_outdoor": "室内",
                "time": "白天",
                "weather": "",
                "season": "",
                "mood": "明亮热闹",
                "tags": ["店铺", "步行街"],
            }

    provider = Provider()
    labels = label_background(provider, source)

    assert labels["label"] == "商业街"
    assert str(tmp_path) not in provider.system + provider.user
    assert len(provider.images) == 1
    tag, blob = provider.images[0]
    assert tag == "background"
    with Image.open(io.BytesIO(blob)) as image:
        assert image.format == "JPEG"
        assert image.mode == "RGB"
        assert image.width <= 1280 and image.height <= 1280


def test_background_label_update_is_shared_by_identical_custom_copies(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    first = tmp_path / "chapter-a" / "bgs" / "shared.png"
    second = tmp_path / "chapter-b" / "bgs" / "shared.png"
    unrelated = tmp_path / "chapter-c" / "bgs" / "other.png"
    for path in (first, second, unrelated):
        _image(path)
    upsert_candidate(
        con, _candidate(first), scope=str(first.parents[1]), status="registered",
        install_path=str(first), display_name="随机文件名",
    )
    upsert_candidate(
        con, _candidate(second), scope=str(second.parents[1]), status="registered",
        install_path=str(second), display_name="随机文件名",
    )
    upsert_candidate(
        con, _candidate(unrelated, key="other", digest="other-digest"),
        scope=str(unrelated.parents[1]), status="registered",
        install_path=str(unrelated), display_name="其他背景",
    )

    target = asset_catalog.library_background_analysis_target(
        con, aa_key="shared-bg", sha256="same-digest"
    )
    updated = asset_catalog.update_background_labels(
        con,
        aa_key="shared-bg",
        sha256="same-digest",
        labels={"label": "雨夜天台", "place": "学校屋顶", "tags": ["雨夜", "屋顶"]},
        status="ready",
    )

    rows = con.execute(
        "SELECT aa_key,metadata_json FROM asset_install ORDER BY scope"
    ).fetchall()
    shared = [json.loads(row["metadata_json"]) for row in rows if row["aa_key"] == "shared-bg"]
    other = json.loads(next(row["metadata_json"] for row in rows if row["aa_key"] == "other"))
    library = asset_catalog.list_library_assets(con)
    con.close()

    assert target["source"] == str(first)
    assert target["aa_key"] == "shared-bg"
    assert updated["updated"] == 2
    assert all(item["labels"]["label"] == "雨夜天台" for item in shared)
    assert all(item["label_status"] == "ready" for item in shared)
    assert "labels" not in other
    item = next(row for row in library["backgrounds"] if row["aa_key"] == "shared-bg")
    assert item["details"]["labels"]["place"] == "学校屋顶"
    assert item["details"]["label_status"] == "ready"
