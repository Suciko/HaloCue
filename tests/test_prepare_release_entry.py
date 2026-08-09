from __future__ import annotations

import subprocess
from pathlib import Path

import prepare_release
from release_tools.manifest import is_public_source_path


HERE = Path(__file__).resolve().parents[1]


def _tracked_source(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    files = {
        "README.md": "# HaloCue\n",
        "LICENSE": "MIT\n",
        "launcher.py": "# public launcher\n",
        "aa_install_discovery.py": "# public discovery\n",
        "official_preview_index.py": "# public previews\n",
        "启动程序.cmd": "@echo off\r\n",
        "检查运行环境.cmd": "@echo off\r\n",
        "使用说明-从这里开始.md": "# HaloCue\n",
        "requirements.txt": "UnityPy>=1.25.2,<2\n",
    }
    for relative, content in files.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="")
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    subprocess.run(["git", "-C", str(source), "add", "--all"], check=True)
    return source


def test_release_entry_exports_current_indexed_public_layout(tmp_path, monkeypatch):
    source = _tracked_source(tmp_path)
    release = tmp_path / "build" / "HaloCue"
    monkeypatch.setattr(prepare_release, "HERE", source)

    assert prepare_release.main(["-o", str(release)]) == 0
    assert (release / "PUBLIC_MANIFEST.json").is_file()
    assert (release / "launcher.py").is_file()
    assert (release / "启动程序.cmd").is_file()
    assert (release / "检查运行环境.cmd").is_file()
    assert (release / "使用说明-从这里开始.md").is_file()
    assert (release / "aa_install_discovery.py").is_file()
    assert (release / "official_preview_index.py").is_file()
    assert "UnityPy>=1.25.2" in (release / "requirements.txt").read_text(
        encoding="utf-8"
    )


def test_public_manifest_and_dependency_file_cover_discovery_runtime():
    assert is_public_source_path("aa_install_discovery.py")
    assert is_public_source_path("official_preview_index.py")
    assert "UnityPy>=1.25.2" in (HERE / "requirements.txt").read_text(
        encoding="utf-8"
    )
