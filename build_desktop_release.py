"""Build and validate the HaloCue 0.9.2 Windows desktop release."""

from __future__ import annotations

import json
import argparse
import hashlib
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path


VERSION = "0.9.2"
RELEASE_BASENAME = f"HaloCue-{VERSION}-windows-x64"
PRIVATE_RELEASE_BASENAME = f"HaloCue-{VERSION}-private-windows-x64"
_ABSOLUTE_PATH = re.compile(
    r"(?i)(?:(?<![a-z])[a-z]:[\\/]|\\\\[a-z0-9._-]+[\\/]|/(?:users|home)/)"
)


def _sanitize_json_value(value):
    if isinstance(value, dict):
        return {key: _sanitize_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_json_value(item) for item in value]
    if isinstance(value, str) and _ABSOLUTE_PATH.search(value):
        return ""
    return value


def _contains_absolute_path(value) -> bool:
    if isinstance(value, dict):
        return any(_contains_absolute_path(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_absolute_path(item) for item in value)
    return isinstance(value, str) and bool(_ABSOLUTE_PATH.search(value))


def _sanitize_text(value: str) -> str:
    if not _ABSOLUTE_PATH.search(value):
        return value
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return ""
    return json.dumps(_sanitize_json_value(decoded), ensure_ascii=False)


def _table_names(con: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def prepare_release_seed(
    source_db: str | Path,
    source_index: str | Path,
    output_dir: str | Path,
) -> Path:
    """Create path-free runtime seeds without user projects or aliases."""
    source_db = Path(source_db).resolve()
    source_index = Path(source_index).resolve()
    destination = Path(output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    target_db = destination / "aa_assets.db"
    shutil.copy2(source_db, target_db)

    con = sqlite3.connect(target_db)
    try:
        tables = _table_names(con)
        for private_table in ("asset_install", "asset_library_profile", "name_alias"):
            if private_table in tables:
                con.execute(f'DELETE FROM "{private_table}"')
        for table in sorted(tables):
            columns = [
                str(row[1])
                for row in con.execute(f'PRAGMA table_info("{table}")')
                if str(row[2]).upper() in {"TEXT", ""}
            ]
            if not columns:
                continue
            selected = ", ".join(f'"{name}"' for name in columns)
            rows = list(con.execute(f'SELECT rowid, {selected} FROM "{table}"'))
            for row in rows:
                rowid, values = row[0], row[1:]
                updates = {
                    name: _sanitize_text(value)
                    for name, value in zip(columns, values)
                    if isinstance(value, str) and _ABSOLUTE_PATH.search(value)
                }
                for name, value in updates.items():
                    con.execute(
                        f'UPDATE "{table}" SET "{name}"=? WHERE rowid=?',
                        (value, rowid),
                    )
        con.commit()
        con.execute("VACUUM")
    finally:
        con.close()

    data = json.loads(source_index.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data["_source"] = ""
    (destination / "aa_resources.json").write_text(
        json.dumps(_sanitize_json_value(data), ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    return destination


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _scan_seed_database(path: Path) -> list[str]:
    findings = []
    con = sqlite3.connect(path)
    try:
        for table in sorted(_table_names(con)):
            text_columns = [
                str(row[1])
                for row in con.execute(f'PRAGMA table_info("{table}")')
                if str(row[2]).upper() in {"TEXT", ""}
            ]
            if not text_columns:
                continue
            selected = ", ".join(f'"{name}"' for name in text_columns)
            for row in con.execute(f'SELECT {selected} FROM "{table}"'):
                if any(
                    isinstance(value, str) and _ABSOLUTE_PATH.search(value)
                    for value in row
                ):
                    findings.append(f"aa_assets.db:{table}:absolute_path")
                    break
    finally:
        con.close()
    return findings


def scan_release_tree(root: str | Path) -> list[str]:
    root = Path(root).resolve()
    findings = []
    forbidden_names = {"aa_config.json", "llm.json", "llm_profiles.json"}
    forbidden_suffixes = {
        ".skel", ".atlas", ".aap", ".aas", ".wav", ".mp3", ".ogg",
    }
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if path.name.lower() in forbidden_names:
            findings.append(f"{relative}:private_config")
        if path.suffix.lower() in forbidden_suffixes:
            findings.append(f"{relative}:forbidden_asset")
        if path.name == "aa_assets.db":
            findings.extend(_scan_seed_database(path))
        elif path.suffix.lower() == ".json":
            text = path.read_text(encoding="utf-8", errors="replace")
            try:
                decoded = json.loads(text)
            except (TypeError, ValueError):
                decoded = text
            if _contains_absolute_path(decoded):
                findings.append(f"{relative}:absolute_path")
            if re.search(r"sk-(?:ant-)?[A-Za-z0-9_-]{20,}", text):
                findings.append(f"{relative}:secret")
        elif path.suffix.lower() in {".txt", ".md", ".html", ".js", ".css", ".py"}:
            text = path.read_text(encoding="utf-8", errors="replace")
            if _ABSOLUTE_PATH.search(text):
                findings.append(f"{relative}:absolute_path")
            if re.search(r"sk-(?:ant-)?[A-Za-z0-9_-]{20,}", text):
                findings.append(f"{relative}:secret")
    return findings


def _write_manifest(release_dir: Path) -> Path:
    manifest_path = release_dir / "build-manifest.json"
    records = []
    for path in sorted(release_dir.rglob("*")):
        if path.is_file() and path != manifest_path:
            records.append({
                "path": path.relative_to(release_dir).as_posix(),
                "size": path.stat().st_size,
                "sha256": _sha256(path),
            })
    manifest_path.write_text(
        json.dumps(
            {
                "product": "HaloCue",
                "version": VERSION,
                "platform": "windows-x64",
                "built_at": datetime.now(timezone.utc).isoformat(),
                "files": records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return manifest_path


def finalize_release(release_dir: str | Path) -> Path:
    release_dir = Path(release_dir).resolve()
    output_root = release_dir.parent
    findings = scan_release_tree(release_dir)
    if findings:
        raise RuntimeError("发布内容扫描失败：\n" + "\n".join(findings))
    _write_manifest(release_dir)

    zip_path = output_root / f"{release_dir.name}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(release_dir.rglob("*")):
            if path.is_file():
                archive.write(path, Path(release_dir.name) / path.relative_to(release_dir))
    (output_root / f"{release_dir.name}.sha256.txt").write_text(
        f"{_sha256(zip_path)}  {zip_path.name}\n",
        encoding="ascii",
    )
    return zip_path


def copy_private_spine_runtime(
    source_dir: str | Path,
    release_dir: str | Path,
) -> Path:
    """Copy only the Spine launcher/runtime needed by the private portable build."""
    source = Path(source_dir).resolve()
    release = Path(release_dir).resolve()
    required = ("Spine.com", "Spine.exe", "launcher", "Spine")
    missing = [name for name in required if not (source / name).exists()]
    if missing:
        raise FileNotFoundError(
            "Spine 运行目录不完整，缺少：" + "、".join(missing)
        )

    target = release / "tools" / "spine"
    target.mkdir(parents=True, exist_ok=False)
    for name in required:
        item = source / name
        destination = target / name
        if item.is_dir():
            shutil.copytree(item, destination)
        else:
            shutil.copy2(item, destination)
    license_file = source / "license.rtf"
    if license_file.is_file():
        shutil.copy2(license_file, target / license_file.name)

    completed = subprocess.run(
        [str(target / "Spine.com"), "--version"],
        cwd=target,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"包内 Spine.com 自检失败：{detail}")

    (release / "SPINE-NOTICE.txt").write_text(
        "Spine is separately licensed software from Esoteric Software LLC.\n"
        "It is included only in this private local build and is not covered by "
        "HaloCue's license. Do not redistribute this package without permission.\n",
        encoding="utf-8",
    )
    return target


def build_release(
    project_root: str | Path,
    *,
    python_executable: str | Path = sys.executable,
    output_parent: str | Path | None = None,
    private_spine_source: str | Path | None = None,
) -> tuple[Path, Path]:
    root = Path(project_root).resolve()
    build_root = root / "build" / "desktop-0.9.2"
    seed_dir = build_root / "seed"
    work_dir = build_root / "pyinstaller"
    dist_dir = build_root / "dist"
    if build_root.exists():
        shutil.rmtree(build_root)
    build_root.mkdir(parents=True)
    prepare_release_seed(
        root / "aa_assets.db",
        root / "aa_resources.json",
        seed_dir,
    )

    env = dict(os.environ)
    env["HALOCUE_BUILD_SEED_DIR"] = str(seed_dir)
    subprocess.run(
        [
            str(Path(python_executable).resolve()),
            "-m", "PyInstaller",
            "--noconfirm", "--clean",
            "--workpath", str(work_dir),
            "--distpath", str(dist_dir),
            str(root / "HaloCue.spec"),
        ],
        cwd=root,
        env=env,
        check=True,
    )

    output_root = (
        Path(output_parent).resolve()
        if output_parent is not None
        else (root.parent / "发布包").resolve()
    )
    output_root.mkdir(parents=True, exist_ok=True)
    release_name = (
        PRIVATE_RELEASE_BASENAME if private_spine_source else RELEASE_BASENAME
    )
    release_dir = output_root / release_name
    if release_dir.exists():
        shutil.rmtree(release_dir)
    shutil.copytree(dist_dir / "HaloCue", release_dir)
    for name in ("使用说明-从这里开始.md", "README.md"):
        source = root / name
        if source.is_file():
            shutil.copy2(source, release_dir / name)
    (release_dir / "版本.txt").write_text(
        f"HaloCue {VERSION}\nWindows 10/11 x64\n"
        + ("Private build with bundled Spine runtime\n" if private_spine_source else ""),
        encoding="utf-8",
    )

    if private_spine_source:
        copy_private_spine_runtime(private_spine_source, release_dir)

    zip_path = finalize_release(release_dir)
    return release_dir, zip_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="构建 HaloCue Windows 桌面便携包")
    parser.add_argument("--output-parent")
    parser.add_argument(
        "--private-spine-source",
        help="构建仅供私下分发的便携包，并从指定目录加入 Spine 运行环境",
    )
    args = parser.parse_args(argv)
    release_dir, zip_path = build_release(
        Path(__file__).resolve().parent,
        python_executable=sys.executable,
        output_parent=args.output_parent,
        private_spine_source=args.private_spine_source,
    )
    print(release_dir)
    print(zip_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
