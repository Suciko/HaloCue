from pathlib import Path

from PIL import Image

from asset_validation import validate_spine
from tools.inspect_expression_capabilities import inspection_report
from spine_semantic_faces import extract_semantic_face_combinations


def make_semantic_bundle(root: Path):
    root.mkdir(parents=True)
    (root / "Kei_Date_Outfit.skel").write_bytes(b"\x00spine\x003.8.76\x00")
    (root / "Kei_Date_Outfit.atlas").write_text(
        "Kei_Date_Outfit.png\n"
        "size:8,8\n"
        "圆睁高光眼（惊讶、好奇）\n"
        "  bounds:0,0,1,1\n",
        encoding="utf-8",
    )
    Image.new("RGBA", (8, 8)).save(root / "Kei_Date_Outfit.png")
    Image.new("RGBA", (4, 4)).save(root / "Kei_Date_Outfit-avatar.png")
    return root


def test_inspection_report_separates_face_ids_from_semantic_parts(tmp_path):
    result = validate_spine(make_semantic_bundle(tmp_path / "date"), identifier="626652156")

    report = inspection_report(result)

    assert report["expression_mode"] == "semantic_modular"
    assert report["verified_face_ids"] == []
    assert report["semantic_parts"][0]["kind"] == "eyes"
    assert "需要在 AA 中记录实际 faceId" in report["next_step"]
