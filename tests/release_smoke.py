"""Shared fixtures and assertions for the packaged HaloCue release smoke."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SyntheticAAWorkspace:
    root: Path
    data: Path
    alternate_data: Path
    install_root: Path
    executable: Path
    catalog: Path
    source_script: Path
    fake_home: Path


def _make_data_tree(path: Path) -> Path:
    for name in ("projects", "saves", "overrides", "settings"):
        (path / name).mkdir(parents=True, exist_ok=True)
    return path


def create_synthetic_aa_workspace(base: Path) -> SyntheticAAWorkspace:
    """Create a recognisable but entirely synthetic AzureArchive layout."""
    root = base / "另一台电脑 验收场景" / "很长的 HaloCue 发布包验证路径"
    data = _make_data_tree(root / "外部 AA 存储" / "data")
    alternate_data = _make_data_tree(root / "用户另选 工作区" / "data")
    fake_home = root / "Windows 用户 Profile"
    install_root = root / "AzureArchive 假安装"
    executable = install_root / "App" / "AzureArchive.exe"
    unity_data = executable.parent / "AzureArchive_Data"
    catalog = unity_data / "StreamingAssets" / "aa" / "catalog.json"
    catalog.parent.mkdir(parents=True, exist_ok=True)
    executable.write_bytes(b"synthetic AzureArchive executable placeholder\n")
    (unity_data / "app.info").write_text(
        "foxxlight\nAzureArchive\n", encoding="utf-8"
    )
    catalog.write_text(
        json.dumps({"synthetic": True}, ensure_ascii=False), encoding="utf-8"
    )
    source_script = root / "输入 剧本" / "最小剧情.txt"
    source_script.parent.mkdir(parents=True, exist_ok=True)
    source_script.write_text("旁白: HaloCue 发布验收。\n", encoding="utf-8")
    settings = data / "settings" / "user_settings.json"
    settings.write_text(
        json.dumps({"workspacePath": str(data)}, ensure_ascii=False),
        encoding="utf-8",
    )
    local_low_settings = (
        fake_home
        / "AppData"
        / "LocalLow"
        / "foxxlight"
        / "AzureArchive"
        / "data"
        / "settings"
        / "user_settings.json"
    )
    local_low_settings.parent.mkdir(parents=True, exist_ok=True)
    local_low_settings.write_text(settings.read_text(encoding="utf-8"), encoding="utf-8")
    return SyntheticAAWorkspace(
        root=root,
        data=data,
        alternate_data=alternate_data,
        install_root=install_root,
        executable=executable,
        catalog=catalog,
        source_script=source_script,
        fake_home=fake_home,
    )


def tree_digests(root: Path) -> dict[str, str]:
    """Return a stable byte-level snapshot of every file below *root*."""
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"), key=lambda item: str(item).casefold())
        if path.is_file()
    }


def python_free_path() -> str:
    """Keep only Windows directories needed to start a native packaged EXE."""
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    return os.pathsep.join(
        str(path)
        for path in (system_root / "System32", system_root)
        if path.is_dir()
    )
