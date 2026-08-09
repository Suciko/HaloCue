from pathlib import Path

from tools.inspect_expression_capabilities import inspection_report


def test_inspection_report_exports_semantic_face_combinations(monkeypatch, tmp_path):
    source = tmp_path / "semantic.skel"
    source.write_bytes(b"stub")
    class Candidate:
        aa_key = "626652156"
        source_path = tmp_path
        metadata = {"files": {"skel": str(source)}}

    class Result:
        ok = True
        issues = ()
        candidate = Candidate()

    monkeypatch.setattr(
        "tools.inspect_expression_capabilities.extract_semantic_face_combinations",
        lambda _: {"03": {"face_id": "03", "labels": ["surprise"], "parts": [], "raw_parts": [], "special": False}},
    )

    report = inspection_report(Result())

    assert report["semantic_face_combinations"]["03"]["labels"] == ["surprise"]
    assert report["auto_annotated_face_ids"] == ["03"]
