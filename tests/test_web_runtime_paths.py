from pathlib import Path
import sys

import annotate
import webui
from runtime_paths import resolve_runtime_layout


def _tree_bytes(root: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_deprecated_run_build_routes_annotation_state_to_user_root(
    tmp_path, monkeypatch
):
    resource_root = tmp_path / "program"
    resource_root.mkdir()
    (resource_root / "resource.txt").write_text("immutable", encoding="utf-8")
    layout = resolve_runtime_layout(
        module_file=resource_root / "runtime_paths.py",
        environ={"HALOCUE_USER_DATA_DIR": str(tmp_path / "state")},
    )
    script = tmp_path / "story.txt"
    script.write_text("旁白: 开始\n", encoding="utf-8")
    aa_data = tmp_path / "aa-data"
    (aa_data / "projects").mkdir(parents=True)
    captured = {}

    def prepare_index(_source, _project, output, **_kwargs):
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text("{}", encoding="utf-8")

    def annotate_script(options, provider_instance=None):
        del provider_instance
        captured.update(options)
        Path(options["out"]).write_text(
            script.read_text(encoding="utf-8"), encoding="utf-8"
        )
        return {}

    monkeypatch.setattr(webui, "RUNTIME_LAYOUT", layout)
    monkeypatch.setitem(webui.CFG, "aa_data", str(aa_data))
    monkeypatch.setattr(webui, "INDEX", str(tmp_path / "index.json"))
    monkeypatch.setattr(webui, "db", lambda: object())
    monkeypatch.setattr(webui, "attach_registered_variants", lambda *_a, **_k: None)
    monkeypatch.setattr(webui, "prepare_project_index", prepare_index)
    monkeypatch.setattr(webui, "annotation_provider", lambda *_a: object())
    monkeypatch.setattr(webui, "pause_for_backgrounds", lambda *_a: False)
    monkeypatch.setattr(webui, "_compile_saved_context", lambda *_a: None)
    monkeypatch.setattr(annotate, "annotate_script", annotate_script)
    before = _tree_bytes(resource_root)

    webui.run_build(
        {
            "script": str(script),
            "project": "Deprecated build",
            "mapping": {},
            "annotate": True,
        }
    )

    assert captured["checkpoint_dir"] == str(
        layout.output_root / "annotation-checkpoints"
    )
    assert _tree_bytes(resource_root) == before


def test_compile_context_passes_output_root_without_mutating_script_resources(
    tmp_path, monkeypatch
):
    resource_root = tmp_path / "program"
    resource_root.mkdir()
    layout = resolve_runtime_layout(
        module_file=resource_root / "runtime_paths.py",
        environ={"HALOCUE_USER_DATA_DIR": str(tmp_path / "state")},
    )
    captured = {}

    def main():
        captured["here"] = webui.S2A.HERE
        captured["argv"] = list(sys.argv)

    monkeypatch.setattr(webui, "RUNTIME_LAYOUT", layout)
    monkeypatch.setattr(webui.S2A, "HERE", str(resource_root))
    monkeypatch.setattr(webui.S2A, "main", main)

    webui._compile_saved_context(
        {
            "src": tmp_path / "story.txt",
            "project": "Demo",
            "cpath": tmp_path / "cast.json",
            "index_path": tmp_path / "index.json",
            "aa_data": tmp_path / "aa-data",
            "install": False,
        }
    )

    assert captured["here"] == str(resource_root)
    output_flag = captured["argv"].index("--output-root")
    assert captured["argv"][output_flag + 1] == str(layout.output_root)
