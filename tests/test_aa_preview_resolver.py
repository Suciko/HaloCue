from pathlib import Path

from PIL import Image

from aa_preview_resolver import (
    AAPreviewResolver,
    apply_local_preview_uris,
    avatar_key_from_spine,
)


def _manifest(root: Path) -> None:
    image = root / "backgrounds" / "bg.webp"
    image.parent.mkdir(parents=True)
    Image.new("RGB", (4, 4), "navy").save(image, "WEBP")
    avatar = root / "avatars" / "avatar.png"
    avatar.parent.mkdir(parents=True)
    Image.new("RGBA", (4, 4), "white").save(avatar, "PNG")
    (root / "manifest.json").write_text(
        '{"schema_version":1,"status":"ready","fingerprint":"x",'
        '"records":[{"kind":"background","key":"BG_School",'
        '"normalized_key":"bg_school","path":"backgrounds/bg.webp",'
        '"source_fingerprint":"x"},{"kind":"avatar",'
        '"key":"Student_Portrait_Hoshino","normalized_key":'
        '"student_portrait_hoshino","path":"avatars/avatar.png",'
        '"source_fingerprint":"x"}],"failures":[]}',
        encoding="utf-8",
    )


def test_avatar_key_matches_aa_spine_convention():
    assert avatar_key_from_spine("CharacterSpine_hoshino") == "Student_Portrait_hoshino"
    assert avatar_key_from_spine(r"characters\CharacterSpine_shiroko") == "Student_Portrait_shiroko"
    assert avatar_key_from_spine("custom-character") == ""


def test_resolver_adds_api_uris_without_exposing_filesystem_paths(tmp_path):
    root = tmp_path / "index"
    _manifest(root)
    resolver = AAPreviewResolver(root)
    descriptor = {
        "background": {"logical_key": "BG_School"},
        "actors": [{"avatar_key": "Student_Portrait_Hoshino"}],
    }

    result = apply_local_preview_uris(
        descriptor,
        resolver,
        uri_for=lambda kind, key: f"/api/resources/preview?kind={kind}&key={key}",
    )

    assert result["background"]["preview_uri"].startswith("/api/resources/preview?")
    assert result["actors"][0]["preview_source"] == "aa-local-index"
    assert str(tmp_path) not in str(result)
