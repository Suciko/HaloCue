import struct
from pathlib import Path

from PIL import Image

from asset_validation import validate_spine
from spine_semantic_faces import extract_semantic_face_combinations


def _varint(value: int) -> bytes:
    output = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        output.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(output)


def _string(value: str | None) -> bytes:
    if value is None:
        return b"\x00"
    encoded = value.encode("utf-8")
    return _varint(len(encoded) + 1) + encoded


def _minimal_spine_38(*animation_names: str) -> bytes:
    data = bytearray()
    data.extend(_string("android-test"))
    data.extend(_string("3.8.99"))
    data.extend(struct.pack(">ffff", 0.0, 0.0, 1.0, 1.0))
    data.append(0)  # nonessential
    data.extend(_varint(0))  # shared strings
    data.extend(_varint(0))  # bones
    data.extend(_varint(0))  # slots
    data.extend(_varint(0))  # IK constraints
    data.extend(_varint(0))  # transform constraints
    data.extend(_varint(0))  # path constraints
    data.extend(_varint(0))  # default skin slots
    data.extend(_varint(0))  # additional skins
    data.extend(_varint(0))  # events
    data.extend(_varint(len(animation_names)))
    for name in animation_names:
        data.extend(_string(name))
        data.extend(b"\x00" * 8)  # Empty timeline groups.
    return bytes(data)


def _spine_bundle(root: Path) -> Path:
    root.mkdir()
    base = root / "AndroidCharacter"
    base.with_suffix(".skel").write_bytes(_minimal_spine_38("01", "42", "99"))
    base.with_suffix(".atlas").write_text(
        "AndroidCharacter.png\nsize:8,8\n",
        encoding="utf-8",
    )
    Image.new("RGBA", (8, 8)).save(base.with_suffix(".png"))
    Image.new("RGBA", (4, 4)).save(root / "AndroidCharacter-avatar.png")
    return base


def test_android_parser_extracts_numbered_semantic_faces(tmp_path):
    skeleton = _spine_bundle(tmp_path / "character").with_suffix(".skel")

    combinations = extract_semantic_face_combinations(skeleton)

    assert {"00", "01", "42", "99"}.issubset(combinations)
    assert combinations["42"]["source"] == "spine_binary_semantic"
    assert combinations["99"]["special"] is True


def test_spine_validation_publishes_binary_semantic_results(tmp_path):
    base = _spine_bundle(tmp_path / "character")

    result = validate_spine(base, identifier="626652156")

    assert result.ok
    assert result.candidate is not None
    metadata = result.candidate.metadata
    assert metadata["spine_version"].startswith("3.8")
    assert metadata["expression_status"] == "known"
    assert metadata["semantic_face_count"] == 4
    assert set(metadata["semantic_face_combinations"]) == {"00", "01", "42", "99"}
