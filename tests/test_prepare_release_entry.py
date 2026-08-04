import os
import subprocess
import sys
from pathlib import Path

import prepare_release


HERE = Path(__file__).resolve().parents[1]


def test_release_contains_beginner_entry_and_launcher(tmp_path):
    release = tmp_path / "release"

    result = subprocess.run(
        [
            sys.executable,
            str(HERE / "prepare_release.py"),
            "-o",
            str(release),
        ],
        cwd=HERE,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (release / "启动AA自动写剧本.cmd").is_file()
    assert (release / "检查运行环境.cmd").is_file()
    assert (release / "使用说明-从这里开始.md").is_file()
    assert (release / "aa" / "launcher.py").is_file()
    assert (release / "aa" / "启动程序.cmd").is_file()
    assert (release / "aa" / "检查运行环境.cmd").is_file()
    assert (release / "aa" / "aa_install_discovery.py").is_file()
    assert (release / "aa" / "official_preview_index.py").is_file()
    assert "UnityPy>=1.25.2" in (release / "requirements.txt").read_text(encoding="utf-8")

    release_files = [path for path in release.rglob("*") if path.is_file()]
    release_file_list = {path.relative_to(release).as_posix() for path in release_files}
    assert all("out/official-previews" not in name for name in release_file_list)
    assert all(not name.lower().endswith((".bundle", "__data")) for name in release_file_list)
    assert all(path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"} for path in release_files)
    assert all(path.name != "aa_config.json" for path in release_files)
    for path in release_files:
        if path.suffix.lower() == ".json":
            assert r"E:\AzureArchive" not in path.read_text(encoding="utf-8", errors="replace")

    for entry_name in ("启动AA自动写剧本.cmd", "检查运行环境.cmd"):
        raw = (release / entry_name).read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf")
        assert b"\r\n" in raw
        assert b"\n" not in raw.replace(b"\r\n", b"")


def test_release_manifest_includes_discovery_index_and_unitypy():
    assert "aa_install_discovery.py" in prepare_release.CODE
    assert "official_preview_index.py" in prepare_release.CODE
    assert "UnityPy>=1.25.2" in prepare_release.REQUIREMENTS
