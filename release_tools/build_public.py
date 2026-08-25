"""Build and audit the standalone public HaloCue Windows bundle."""

from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import zipfile

from halocue_meta import PUBLIC_ARCHIVE_NAME
from release_tools.scanner import scan_tree


_SOURCE_MANIFEST = "PUBLIC_MANIFEST.json"
_BUILD_MANIFEST = "HaloCue-build-manifest.json"
_BUNDLE_NAME = "HaloCue"
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_PYINSTALLER_HIDDEN_IMPORTS = ("anthropic", "UnityPy")
_PYINSTALLER_EXCLUDES = (
    "archspec",
    "av",
    "bcrypt",
    "cryptography",
    "cv2",
    "hypothesis",
    "invoke",
    "matplotlib",
    "nacl",
    "numpy",
    "onnxruntime",
    "outcome",
    "pandas",
    "paramiko",
    "pkg_resources",
    "pluggy",
    "py",
    "pytest",
    "_pytest",
    "scipy",
    "setuptools",
    "sklearn",
    "sympy",
    "tkinter",
    "_tkinter",
    "torch",
    "torchvision",
    "transformers",
    "trio",
    "yt_dlp",
)
_PYINSTALLER_METADATA_DISTRIBUTIONS = (
    "annotated-types",
    "anthropic",
    "anyio",
    "astc-encoder-py",
    "attrs",
    "brotli",
    "certifi",
    "click",
    "defusedxml",
    "distro",
    "docstring_parser",
    "etcpak",
    "fsspec",
    "h11",
    "httpcore",
    "httpx",
    "idna",
    "jiter",
    "lz4",
    "MarkupSafe",
    "Pillow",
    "pydantic",
    "pydantic_core",
    "Pygments",
    "pywin32",
    "rich",
    "sniffio",
    "texture2ddecoder",
    "tqdm",
    "typing_extensions",
    "typing-inspection",
    "tzdata",
    "UnityPy",
    "zstandard",
)
_PUBLIC_RESOURCES = (
    "ui.html",
    "js",
    "css",
    "branding/halocue-icon.png",
    "branding/halocue-favicon.png",
    "branding/halocue.ico",
    "data/halocue_labels.db",
    "README.md",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
)


@dataclass(frozen=True)
class PublicBuildResult:
    bundle_dir: Path
    archive_path: Path
    archive_sha256: str
    manifest_path: Path


def pyinstaller_policy() -> dict[str, object]:
    """Return the frozen build's explicit, environment-independent policy."""

    return {
        "hidden_imports": _PYINSTALLER_HIDDEN_IMPORTS,
        "excludes": _PYINSTALLER_EXCLUDES,
        "metadata_recursive": False,
        "metadata_distributions": _PYINSTALLER_METADATA_DISTRIBUTIONS,
        "version_file_environment": "HALOCUE_VERSION_FILE",
    }


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _regular_files(root: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"unsafe link in release tree: {path.relative_to(root).as_posix()}")
        if path.is_file():
            files[path.relative_to(root).as_posix()] = path
    return dict(sorted(files.items()))


def _load_source_manifest(source_root: Path) -> None:
    manifest_path = source_root / _SOURCE_MANIFEST
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = payload["files"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("valid PUBLIC_MANIFEST.json is required") from exc
    if not isinstance(entries, list):
        raise ValueError("valid PUBLIC_MANIFEST.json is required")
    actual = _regular_files(source_root)
    actual.pop(_SOURCE_MANIFEST, None)
    expected_paths: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("valid PUBLIC_MANIFEST.json is required")
        relative = entry.get("path")
        if not isinstance(relative, str) or not relative:
            raise ValueError("valid PUBLIC_MANIFEST.json is required")
        normalized = PurePosixPath(relative).as_posix()
        if normalized != relative or relative.startswith("/") or ".." in PurePosixPath(relative).parts:
            raise ValueError("valid PUBLIC_MANIFEST.json is required")
        path = actual.get(relative)
        if path is None:
            raise ValueError("PUBLIC_MANIFEST.json does not match source export")
        data = path.read_bytes()
        if entry.get("size") != len(data) or entry.get("sha256") != _sha256(data):
            raise ValueError("PUBLIC_MANIFEST.json does not match source export")
        expected_paths.append(relative)
    if expected_paths != sorted(set(expected_paths)) or set(expected_paths) != set(actual):
        raise ValueError("PUBLIC_MANIFEST.json does not match source export")


def _require_clean_public_source(source_root: Path) -> None:
    if not source_root.is_dir():
        raise ValueError("public source directory does not exist")
    _load_source_manifest(source_root)
    missing = [relative for relative in _PUBLIC_RESOURCES if not (source_root / relative).exists()]
    if not (source_root / "HaloCue.spec").is_file():
        missing.append("HaloCue.spec")
    if missing:
        raise ValueError("public source is missing required files: " + ", ".join(missing))
    findings = scan_tree(source_root, mode="source")
    if findings:
        summary = ", ".join(
            f"{finding.code}:{finding.relative_path}" for finding in findings[:12]
        )
        raise ValueError(f"public source scan failed: {summary}")


def _contained_target(target: Path, parent: Path) -> Path:
    target = target.resolve()
    parent = parent.resolve()
    try:
        relative = target.relative_to(parent)
    except ValueError as exc:
        raise ValueError("build target must remain below output root") from exc
    if not relative.parts:
        raise ValueError("build target must remain below output root")
    return target


def _remove_generated(target: Path, output_root: Path) -> None:
    target = _contained_target(target, output_root)
    if target.is_dir() and not target.is_symlink():
        shutil.rmtree(target)
    elif target.exists() or target.is_symlink():
        target.unlink()


def _run_pyinstaller(
    source_root: Path,
    work_root: Path,
    python_executable: Path,
) -> None:
    version_path = _write_version_file(source_root, work_root)
    command = [
        str(python_executable),
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(work_root / "dist"),
        "--workpath",
        str(work_root / "work"),
        str(source_root / "HaloCue.spec"),
    ]
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "HALOCUE_VERSION_FILE": str(version_path),
        }
    )
    subprocess.run(command, cwd=work_root, env=environment, check=True)


def _source_constants(source_root: Path) -> dict[str, object]:
    tree = ast.parse(
        (source_root / "halocue_meta.py").read_text(encoding="utf-8"),
        filename="halocue_meta.py",
    )
    values: dict[str, object] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name):
            try:
                values[target.id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                continue
    return values


def _write_version_file(source_root: Path, work_root: Path) -> Path:
    metadata = _source_constants(source_root)
    product = metadata.get("PRODUCT_NAME")
    version = metadata.get("VERSION")
    match = re.fullmatch(r"(\d+)\.(\d+)(?:\.(\d+))?(?:-beta\.(\d+))?", str(version))
    if product != "HaloCue" or match is None:
        raise ValueError("halocue_meta.py has unsupported public version metadata")
    numeric = tuple(int(part or 0) for part in match.groups())
    version_path = work_root / "halocue-version.txt"
    version_path.write_text(
        "VSVersionInfo(\n"
        f"  ffi=FixedFileInfo(filevers={numeric!r}, prodvers={numeric!r}, "
        "mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),\n"
        "  kids=[StringFileInfo([StringTable('040904B0', [\n"
        "    StringStruct('CompanyName', 'Suciko'),\n"
        "    StringStruct('FileDescription', 'HaloCue'),\n"
        f"    StringStruct('FileVersion', '{version}'),\n"
        "    StringStruct('InternalName', 'HaloCue'),\n"
        "    StringStruct('LegalCopyright', 'Copyright (c) 2026 Suciko'),\n"
        "    StringStruct('OriginalFilename', 'HaloCue.exe'),\n"
        "    StringStruct('ProductName', 'HaloCue'),\n"
        f"    StringStruct('ProductVersion', '{version}')\n"
        "  ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])]\n"
        ")\n",
        encoding="utf-8",
        newline="\n",
    )
    return version_path


def _copy_public_resources(source_root: Path, bundle_dir: Path) -> None:
    for relative in _PUBLIC_RESOURCES:
        source = source_root / relative
        for destination in (bundle_dir / relative, bundle_dir / "_internal" / relative):
            if source.is_dir():
                shutil.copytree(source, destination, dirs_exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)


def _remove_environment_payloads(bundle_dir: Path) -> None:
    """Remove known PyInstaller host-environment extras before public scan."""

    internal = bundle_dir / "_internal"
    if not internal.is_dir():
        return
    for path in list(internal.rglob("*")):
        if path.is_file() and (
            path.suffix.casefold() == ".gif"
            or path.name.casefold() == "direct_url.json"
        ):
            path.unlink()
    for relative in ("_tcl_data", "_tk_data", "tcl8", "tcl86t.dll", "tk86t.dll"):
        candidate = internal / relative
        if candidate.is_dir() and not candidate.is_symlink():
            shutil.rmtree(candidate)
        elif candidate.exists() or candidate.is_symlink():
            candidate.unlink()
    for module in _PYINSTALLER_EXCLUDES:
        package = internal / module
        if package.is_dir() and not package.is_symlink():
            shutil.rmtree(package)
        elif package.exists() or package.is_symlink():
            package.unlink()
        distribution_prefixes = {
            module.casefold().replace("_", "-"),
            module.casefold().replace("-", "_"),
        }
        for candidate in list(internal.iterdir()):
            folded = candidate.name.casefold()
            if not any(
                folded.startswith(prefix + "-") and folded.endswith(".dist-info")
                for prefix in distribution_prefixes
            ):
                continue
            if candidate.is_dir() and not candidate.is_symlink():
                shutil.rmtree(candidate)
            else:
                candidate.unlink()


def _normalized_component(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value.strip().casefold())


def audit_third_party_notices(bundle_dir: Path) -> tuple[str, ...]:
    """Require notices for shipped distributions and native runtime libraries."""

    notice_path = bundle_dir / "THIRD_PARTY_NOTICES.md"
    notice = notice_path.read_text(encoding="utf-8")
    declared = {
        _normalized_component(token)
        for token in re.findall(r"`([^`]+)`", notice)
    }
    components: dict[str, str] = {}
    for metadata in bundle_dir.rglob("*.dist-info/METADATA"):
        match = re.search(
            r"(?mi)^Name:\s*([^\r\n]+)",
            metadata.read_text(encoding="utf-8", errors="replace"),
        )
        if match:
            name = match.group(1).strip()
            components[_normalized_component(name)] = name
    internal = bundle_dir / "_internal"
    native_components = (
        ("CPython", tuple(internal.glob("python*.dll"))),
        ("Microsoft Visual C++ Runtime", tuple(internal.glob("VCRUNTIME*.dll")) + tuple(internal.glob("MSVCP*.dll")) + tuple(internal.glob("ucrtbase.dll"))),
        ("OpenSSL", tuple(internal.glob("libcrypto*.dll")) + tuple(internal.glob("libssl*.dll"))),
        ("SQLite", tuple(internal.glob("sqlite3.dll"))),
        ("zlib", tuple(internal.glob("zlib.dll"))),
        ("bzip2", tuple(internal.glob("LIBBZ2.dll"))),
        ("XZ Utils", tuple(internal.glob("liblzma.dll"))),
        ("Expat", tuple(internal.glob("libexpat.dll"))),
        ("libffi", tuple(internal.glob("ffi.dll"))),
        ("mpdecimal", tuple(internal.glob("libmpdec*.dll"))),
        ("Zstandard", tuple(internal.glob("zstd.dll"))),
    )
    for name, matches in native_components:
        if matches:
            components[_normalized_component(name)] = name
    if (bundle_dir / "HaloCue.exe").is_file():
        components[_normalized_component("PyInstaller")] = "PyInstaller"
    missing = sorted(
        (name for key, name in components.items() if key not in declared),
        key=str.casefold,
    )
    if missing:
        raise ValueError("THIRD_PARTY_NOTICES.md missing shipped components: " + ", ".join(missing))
    return tuple(sorted(components.values(), key=str.casefold))


def _write_manifest(bundle_dir: Path, manifest_path: Path) -> None:
    entries = []
    for relative, path in _regular_files(bundle_dir).items():
        data = path.read_bytes()
        entries.append(
            {"path": relative, "size": len(data), "sha256": _sha256(data)}
        )
    manifest_path.write_text(
        json.dumps({"files": entries}, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_stable_zip(bundle_dir: Path, archive_path: Path) -> None:
    with zipfile.ZipFile(
        archive_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=True,
    ) as archive:
        for relative, path in _regular_files(bundle_dir).items():
            info = zipfile.ZipInfo(f"{_BUNDLE_NAME}/{relative}", _ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100755 if path.suffix.casefold() == ".exe" else 0o100644) << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def build_public_release(
    source_root: Path,
    output_root: Path,
    *,
    python_executable: Path,
) -> PublicBuildResult:
    """Build one deterministic public archive from an audited source export."""

    source_root = Path(source_root).resolve()
    output_root = Path(output_root).resolve()
    python_executable = Path(python_executable).resolve()
    if not python_executable.is_file():
        raise ValueError("python executable does not exist")
    _require_clean_public_source(source_root)
    output_root.mkdir(parents=True, exist_ok=True)
    work_root = _contained_target(output_root / "build" / "pyinstaller", output_root)
    bundle_dir = _contained_target(output_root / _BUNDLE_NAME, output_root)
    archive_path = _contained_target(output_root / PUBLIC_ARCHIVE_NAME, output_root)
    manifest_path = _contained_target(output_root / _BUILD_MANIFEST, output_root)
    checksum_path = archive_path.with_suffix(archive_path.suffix + ".sha256")
    for target in (work_root, bundle_dir, archive_path, manifest_path, checksum_path):
        _remove_generated(target, output_root)
    work_root.mkdir(parents=True)
    _run_pyinstaller(source_root, work_root, python_executable)
    _load_source_manifest(source_root)
    built_bundle = work_root / "dist" / _BUNDLE_NAME
    if not (built_bundle / "HaloCue.exe").is_file():
        raise ValueError("PyInstaller did not produce HaloCue/HaloCue.exe")
    shutil.move(str(built_bundle), str(bundle_dir))
    _copy_public_resources(source_root, bundle_dir)
    _remove_environment_payloads(bundle_dir)
    audit_third_party_notices(bundle_dir)
    findings = scan_tree(bundle_dir, mode="public")
    if findings:
        summary = ", ".join(
            f"{finding.code}:{finding.relative_path}" for finding in findings[:12]
        )
        raise ValueError(f"public bundle scan failed: {summary}")
    _write_manifest(bundle_dir, manifest_path)
    _write_stable_zip(bundle_dir, archive_path)
    archive_sha256 = _sha256(archive_path.read_bytes())
    checksum_path.write_text(
        f"{archive_sha256}  {archive_path.name}\n",
        encoding="ascii",
        newline="\n",
    )
    return PublicBuildResult(
        bundle_dir=bundle_dir,
        archive_path=archive_path,
        archive_sha256=archive_sha256,
        manifest_path=manifest_path,
    )


def finalize_existing_bundle(
    source_root: Path,
    bundle_dir: Path,
    output_root: Path,
) -> PublicBuildResult:
    """Finalize an already-built lean bundle without invoking PyInstaller."""

    source_root = Path(source_root).resolve()
    output_root = Path(output_root).resolve()
    bundle_dir = _contained_target(Path(bundle_dir), output_root)
    if bundle_dir.name != _BUNDLE_NAME or not bundle_dir.is_dir() or bundle_dir.is_symlink():
        raise ValueError("existing bundle must be the HaloCue directory below output root")
    _require_clean_public_source(source_root)
    required = ["HaloCue.exe", *_PUBLIC_RESOURCES]
    missing = [relative for relative in required if not (bundle_dir / relative).exists()]
    if missing:
        raise ValueError("existing bundle is missing required files: " + ", ".join(missing))
    source_notice = source_root / "THIRD_PARTY_NOTICES.md"
    shutil.copy2(source_notice, bundle_dir / "THIRD_PARTY_NOTICES.md")
    _load_source_manifest(source_root)
    audit_third_party_notices(bundle_dir)
    findings = scan_tree(bundle_dir, mode="public")
    if findings:
        summary = ", ".join(
            f"{finding.code}:{finding.relative_path}" for finding in findings[:12]
        )
        raise ValueError(f"public bundle scan failed: {summary}")
    archive_path = _contained_target(output_root / PUBLIC_ARCHIVE_NAME, output_root)
    manifest_path = _contained_target(output_root / _BUILD_MANIFEST, output_root)
    checksum_path = archive_path.with_suffix(archive_path.suffix + ".sha256")
    for target in (archive_path, manifest_path, checksum_path):
        _remove_generated(target, output_root)
    _write_manifest(bundle_dir, manifest_path)
    _write_stable_zip(bundle_dir, archive_path)
    archive_sha256 = _sha256(archive_path.read_bytes())
    checksum_path.write_text(
        f"{archive_sha256}  {archive_path.name}\n",
        encoding="ascii",
        newline="\n",
    )
    return PublicBuildResult(
        bundle_dir=bundle_dir,
        archive_path=archive_path,
        archive_sha256=archive_sha256,
        manifest_path=manifest_path,
    )
