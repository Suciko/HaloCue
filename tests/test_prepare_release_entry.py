import os
import subprocess
import sys
from pathlib import Path


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

    for entry_name in ("启动AA自动写剧本.cmd", "检查运行环境.cmd"):
        raw = (release / entry_name).read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf")
        assert b"\r\n" in raw
        assert b"\n" not in raw.replace(b"\r\n", b"")
