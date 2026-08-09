# -*- coding: utf-8 -*-
"""Register validated custom assets into AA project/save manifests."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import unicodedata
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Callable

from aa_project_assets import (
    AAProjectTarget,
    assert_aa_closed,
    destination_within,
    project_target_lock,
    resolve_safe_directory,
    validate_windows_path_component,
)
from asset_models import ValidationResult


MANIFEST_LISTS = ("CharacterOverrides", "VoiceOverrides", "PopupOverrides", "SoundOverrides", "BgOverrides", "BgmOverrides")


class AssetRegistrationError(RuntimeError):
    pass


class RegistrationConflictError(AssetRegistrationError):
    """A registered AA asset already owns the requested name or identifier."""


class AssetRemovalError(RuntimeError):
    """A registered asset copy could not be removed without partial state."""


@dataclass(frozen=True)
class RegistrationResult:
    kind: str
    aa_key: int | str
    install_paths: tuple[Path, ...]
    manifest_paths: tuple[Path, ...]
    changed: bool

    @property
    def install_path(self) -> Path:
        """Backward-compatible primary target for offline callers."""
        return self.install_paths[0]

    @property
    def manifest_path(self) -> Path:
        return self.manifest_paths[0]


@dataclass(frozen=True)
class RemovalResult:
    kind: str
    aa_key: str
    install_dirs: tuple[Path, ...]
    manifest_paths: tuple[Path, ...]
    changed: bool


def _empty_manifest() -> dict:
    return {key: [] for key in MANIFEST_LISTS}


def load_manifest(project_dir: str | Path) -> dict:
    path = Path(project_dir) / "manifest.json"
    if not path.is_file():
        return _empty_manifest()
    try:
        manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise AssetRegistrationError(f"无法读取 manifest：{exc}") from exc
    for key in MANIFEST_LISTS:
        manifest.setdefault(key, [])
        if not isinstance(manifest[key], list):
            raise AssetRegistrationError(f"manifest.{key} 必须是数组")
    return manifest


def write_manifest_atomic(project_dir: str | Path, manifest: dict) -> Path:
    project = Path(project_dir)
    project.mkdir(parents=True, exist_ok=True)
    target = project / "manifest.json"
    fd, temp_name = tempfile.mkstemp(prefix="manifest.", suffix=".tmp", dir=str(project))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as out:
            json.dump(manifest, out, ensure_ascii=False, indent=2)
            out.write("\n")
        json.loads(Path(temp_name).read_text(encoding="utf-8"))
        os.replace(temp_name, target)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
    return target


def _require_valid(result: ValidationResult):
    if not result.ok or result.candidate is None:
        details = "; ".join(issue.message for issue in result.issues)
        raise AssetRegistrationError(f"素材未通过验证：{details}")
    return result.candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _manifest_rel(*parts: str) -> str:
    return str(PureWindowsPath(*parts))


def _name_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _same_stem_conflict(paths: list[str], stem: str, expected_rel: str) -> str | None:
    wanted = _name_key(stem)
    for value in paths:
        current = PureWindowsPath(value)
        if _name_key(current.stem) == wanted and str(current) != expected_rel:
            return value
    return None


def _directories(target: AAProjectTarget | str | Path) -> tuple[Path, ...]:
    if isinstance(target, AAProjectTarget):
        return (target.project_dir, target.save_dir)
    try:
        return (resolve_safe_directory(target, label="registration target"),)
    except ValueError as exc:
        raise AssetRegistrationError(str(exc)) from exc


@contextmanager
def _registration_transaction(
    target: AAProjectTarget | str | Path,
    running_probe: Callable[[], bool] | None,
):
    directories = _directories(target)
    with project_target_lock(directories):
        if isinstance(target, AAProjectTarget):
            assert_aa_closed(running_probe=running_probe)
        yield directories


def _preflight_files(sources: list[Path], destinations: list[Path]) -> None:
    for source, destination in zip(sources, destinations):
        if destination.is_file() and _sha256(source) != _sha256(destination):
            raise RegistrationConflictError(f"目标存在同名但内容不同的文件：{destination}")
        if destination.exists() and not destination.is_file():
            raise AssetRegistrationError(f"目标不是文件：{destination}")


@contextmanager
def _staged_validation_result(result: ValidationResult):
    """Copy one validated source set, then validate the server-owned snapshot.

    Registration never reads the caller/history source after this point.  A
    source replacement while staging yields a hash mismatch and no AA write.
    """
    candidate = _require_valid(result)
    with tempfile.TemporaryDirectory(prefix="aa-asset-stage-") as temporary:
        stage = Path(temporary)
        if candidate.kind == "character":
            files = _character_files(candidate)
            if not files:
                raise AssetRegistrationError("character staging has no files")
            for relative, source in files:
                if not source.is_file():
                    raise AssetRegistrationError("validated source disappeared before staging")
                destination = stage / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            from asset_validation import validate_spine
            staged = validate_spine(stage / candidate.stem, identifier=str(candidate.aa_key))
        else:
            source = Path(candidate.source_path)
            if not source.is_file():
                raise AssetRegistrationError("validated source disappeared before staging")
            snapshot = stage / source.name
            shutil.copy2(source, snapshot)
            if candidate.kind == "background":
                from asset_validation import validate_background
                staged = validate_background(snapshot)
            elif candidate.kind == "sound":
                from asset_validation import validate_sound
                staged = validate_sound(snapshot)
            else:
                raise AssetRegistrationError(f"unsupported staged asset kind: {candidate.kind}")
        if not staged.ok or staged.candidate is None or staged.candidate.sha256 != candidate.sha256:
            raise AssetRegistrationError("validated source changed while staging")
        yield staged


def _copy_new_file_atomically(source: Path, destination: Path) -> None:
    """Copy only through a sibling temporary file; never overwrite an existing target."""
    if destination.exists():
        raise AssetRegistrationError(f"target appeared during registration: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=str(destination.parent)
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(source, temporary)
        if destination.exists():
            raise AssetRegistrationError(f"target appeared during registration: {destination}")
        os.replace(temporary, destination)
    except Exception:
        # The target did not exist at preflight and the pair lock excludes our writers.
        # Remove a fault-injected partial target as well as the sibling temporary file.
        try:
            destination.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _commit(
    directories: tuple[Path, ...], manifests: list[dict], files: list[tuple[Path, Path]],
    after_commit: Callable[[], None] | None = None,
) -> None:
    created: list[Path] = []
    originals = {directory / "manifest.json": (directory / "manifest.json").read_bytes() if (directory / "manifest.json").is_file() else None for directory in directories}
    written: list[Path] = []
    try:
        for source, destination in files:
            if not destination.exists():
                _copy_new_file_atomically(source, destination)
                created.append(destination)
        for source, destination in files:
            if not destination.is_file() or _sha256(source) != _sha256(destination):
                raise AssetRegistrationError("mirrored asset bytes no longer match the validated snapshot")
        for directory, manifest in zip(directories, manifests):
            path = write_manifest_atomic(directory, manifest)
            written.append(path)
        if after_commit is not None:
            after_commit()
    except Exception:
        for path in reversed(created):
            try:
                path.unlink()
            except OSError:
                pass
        for path in reversed(written):
            original = originals[path]
            try:
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(original)
            except OSError:
                pass
        raise


def _register_simple_unlocked(result: ValidationResult, directories: tuple[Path, ...], *, kind: str, folder: str, manifest_key: str, after_register: Callable[[RegistrationResult], None] | None = None) -> RegistrationResult:
    candidate = _require_valid(result)
    if candidate.kind != kind:
        raise AssetRegistrationError(f"验证结果不是{kind}")
    source = Path(candidate.source_path)
    try:
        filename = validate_windows_path_component(source.name, label="asset filename")
        rel = _manifest_rel(folder, filename)
        destinations = [destination_within(directory, folder, filename) for directory in directories]
    except ValueError as exc:
        raise AssetRegistrationError(str(exc)) from exc
    manifests = [load_manifest(directory) for directory in directories]
    for manifest in manifests:
        conflict = _same_stem_conflict(manifest[manifest_key], candidate.stem, rel)
        if conflict:
            raise RegistrationConflictError(f"素材存在同名冲突：{conflict} 与 {rel}")
    _preflight_files([source] * len(destinations), destinations)
    changed = any(not destination.exists() for destination in destinations)
    for manifest in manifests:
        if rel not in manifest[manifest_key]:
            manifest[manifest_key].append(rel)
            changed = True
    registration = RegistrationResult(kind, candidate.aa_key, tuple(destinations), tuple(directory / "manifest.json" for directory in directories), changed)
    _commit(
        directories, manifests, list(zip([source] * len(destinations), destinations)),
        after_commit=(lambda: after_register(registration)) if after_register else None,
    )
    return registration


def _register_simple(result: ValidationResult, target, *, kind: str, folder: str, manifest_key: str, running_probe=None, after_register=None) -> RegistrationResult:
    with _registration_transaction(target, running_probe) as directories:
        with _staged_validation_result(result) as staged:
            return _register_simple_unlocked(
                staged,
                directories,
                kind=kind,
                folder=folder,
                manifest_key=manifest_key,
                after_register=after_register,
            )


def register_background(result: ValidationResult, project_dir: AAProjectTarget | str | Path, *, running_probe: Callable[[], bool] | None = None, after_register=None) -> RegistrationResult:
    return _register_simple(result, project_dir, kind="background", folder="bgs", manifest_key="BgOverrides", running_probe=running_probe, after_register=after_register)


def register_sound(result: ValidationResult, project_dir: AAProjectTarget | str | Path, *, running_probe: Callable[[], bool] | None = None, after_register=None) -> RegistrationResult:
    return _register_simple(result, project_dir, kind="sound", folder="sounds", manifest_key="SoundOverrides", running_probe=running_probe, after_register=after_register)


def _character_files(candidate) -> list[tuple[Path, Path]]:
    metadata = candidate.metadata
    raw_files = metadata.get("all_files") or metadata.get("files") or {}
    source_root = Path(candidate.source_path)
    files: list[tuple[Path, Path]] = []
    for key, value in raw_files.items():
        source = Path(value)
        try:
            relative = source.resolve().relative_to(source_root.resolve())
        except ValueError as exc:
            raise AssetRegistrationError("character file escapes source bundle") from exc
        if not relative.parts or any(part in {".", ".."} for part in relative.parts):
            raise AssetRegistrationError("character file has invalid relative path")
        files.append((relative, source))
    return files


def _validate_character_identity(result: ValidationResult):
    """Reject unsafe character names before staging or resolving any target."""
    candidate = _require_valid(result)
    if candidate.kind != "character":
        raise AssetRegistrationError("验证结果不是人物骨骼")
    try:
        validate_windows_path_component(
            str(candidate.aa_key), label="character Identifier"
        )
        validate_windows_path_component(
            candidate.stem, label="character asset name"
        )
    except ValueError as exc:
        raise AssetRegistrationError(str(exc)) from exc
    return candidate


def _register_character_unlocked(result: ValidationResult, directories: tuple[Path, ...], *, display_name: str, nickname: str = "", after_register: Callable[[RegistrationResult], None] | None = None) -> RegistrationResult:
    candidate = _validate_character_identity(result)
    identifier = str(candidate.aa_key)
    manifests = [load_manifest(directory) for directory in directories]
    spine_rel = _manifest_rel("characters", identifier, candidate.stem)
    entry = {"Identifier": identifier, "Name": display_name, "Nickname": nickname, "CharacterReference": None, "OriginalIdentifier": None, "SpinePortraitPath": spine_rel, "SmallPortraitPath": _manifest_rel("characters", identifier, candidate.stem + "-avatar.png")}
    for manifest in manifests:
        existing = next((row for row in manifest["CharacterOverrides"] if str(row.get("Identifier")) == identifier), None)
        if existing and not existing.get("SpinePortraitPath"):
            existing.update(entry)
            continue
        if existing and any(existing.get(key) != entry[key] for key in ("Identifier", "Name", "Nickname", "SpinePortraitPath", "SmallPortraitPath")):
            raise RegistrationConflictError(f"Identifier {identifier!r} 已用于不同身份或内容")
    files = _character_files(candidate)
    try:
        destinations = [
            destination_within(directory, "characters", identifier, *relative.parts)
            for directory in directories
            for relative, _source in files
        ]
    except ValueError as exc:
        raise AssetRegistrationError(str(exc)) from exc
    source_list = [source for _relative, source in files] * len(directories)
    _preflight_files(source_list, destinations)
    changed = any(not destination.exists() for destination in destinations)
    for manifest in manifests:
        if not any(str(row.get("Identifier")) == identifier for row in manifest["CharacterOverrides"]):
            manifest["CharacterOverrides"].append(entry.copy())
            changed = True
    try:
        install_dirs = tuple(
            destination_within(directory, "characters", identifier)
            for directory in directories
        )
    except ValueError as exc:
        raise AssetRegistrationError(str(exc)) from exc
    registration = RegistrationResult("character", identifier, install_dirs, tuple(directory / "manifest.json" for directory in directories), changed)
    _commit(
        directories, manifests, list(zip(source_list, destinations)),
        after_commit=(lambda: after_register(registration)) if after_register else None,
    )
    return registration


def register_character(
    result: ValidationResult,
    project_dir: AAProjectTarget | str | Path,
    *,
    display_name: str,
    nickname: str = "",
    running_probe: Callable[[], bool] | None = None,
    after_register=None,
) -> RegistrationResult:
    # Validate the caller-provided identity before locks, staging, or target
    # resolution so a bypassed upstream validator cannot influence any path.
    _validate_character_identity(result)
    with _registration_transaction(project_dir, running_probe) as directories:
        with _staged_validation_result(result) as staged:
            return _register_character_unlocked(
                staged,
                directories,
                display_name=display_name,
                nickname=nickname,
                after_register=after_register,
            )


def register_character_unlocked(
    result: ValidationResult,
    target: AAProjectTarget | str | Path,
    *,
    display_name: str,
    nickname: str = "",
) -> RegistrationResult:
    """Register a character inside a caller-owned target transaction.

    The caller must already hold ``project_target_lock`` for ``target`` and have
    performed the AA running-state guard when the target is an AA project pair.
    This deliberately avoids recursively taking the cross-process file lock.
    """
    return _register_character_unlocked(
        result,
        _directories(target),
        display_name=display_name,
        nickname=nickname,
    )


_REMOVAL_LAYOUT = {
    "background": ("BgOverrides", "bgs"),
    "sound": ("SoundOverrides", "sounds"),
}


def _safe_manifest_destination(root: Path, value: str, folder: str) -> Path:
    path = PureWindowsPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or path.parts[0].casefold() != folder.casefold()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise AssetRemovalError("manifest 中的素材路径无效")
    try:
        return destination_within(root, *path.parts)
    except ValueError as exc:
        raise AssetRemovalError("manifest 中的素材路径越界") from exc


def _simple_removal_entry(
    root: Path, manifest: dict, *, kind: str, aa_key: str, expected_sha256: str
) -> tuple[str, Path]:
    manifest_key, folder = _REMOVAL_LAYOUT[kind]
    matches = [
        str(value)
        for value in manifest[manifest_key]
        if isinstance(value, str)
        and _name_key(PureWindowsPath(value).stem) == _name_key(aa_key)
    ]
    if len(matches) != 1:
        raise AssetRemovalError("素材登记不存在或存在歧义")
    relative = matches[0]
    destination = _safe_manifest_destination(root, relative, folder)
    if not destination.is_file():
        raise AssetRemovalError("已登记素材文件不存在")
    if kind == "background":
        from asset_validation import validate_background

        validation = validate_background(destination)
    else:
        from asset_validation import validate_sound

        validation = validate_sound(destination)
    if (
        not validation.ok
        or validation.candidate is None
        or validation.candidate.sha256 != expected_sha256
    ):
        raise AssetRemovalError("素材内容与删除确认时不一致")
    return relative, destination


def _character_removal_entry(
    root: Path, manifest: dict, *, aa_key: str, expected_sha256: str
) -> tuple[dict, Path]:
    matches = [
        row
        for row in manifest["CharacterOverrides"]
        if isinstance(row, dict) and str(row.get("Identifier")) == aa_key
    ]
    if len(matches) != 1:
        raise AssetRemovalError("角色素材登记不存在或存在歧义")
    entry = matches[0]
    base = _safe_manifest_destination(
        root, str(entry.get("SpinePortraitPath") or ""), "characters"
    )
    install_dir = destination_within(root, "characters", aa_key)
    try:
        base.relative_to(install_dir)
    except ValueError as exc:
        raise AssetRemovalError("角色素材登记目录无效") from exc
    from asset_validation import validate_spine

    validation = validate_spine(base, identifier=aa_key)
    if (
        not validation.ok
        or validation.candidate is None
        or validation.candidate.sha256 != expected_sha256
    ):
        raise AssetRemovalError("角色素材内容与删除确认时不一致")
    return entry, install_dir


def _restore_manifest(path: Path, original: bytes | None) -> None:
    if original is None:
        path.unlink(missing_ok=True)
        return
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".restore", dir=str(path.parent)
    )
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(original)
        os.replace(temporary_name, path)
    finally:
        try:
            Path(temporary_name).unlink(missing_ok=True)
        except OSError:
            pass


def remove_registered_asset(
    target: AAProjectTarget,
    *,
    kind: str,
    aa_key: str,
    expected_sha256: str,
    running_probe: Callable[[], bool] | None = None,
    after_remove: Callable[[RemovalResult], None] | None = None,
) -> RemovalResult:
    """Remove one project/save copy, restoring both mirrors on any failure."""
    if kind not in {*_REMOVAL_LAYOUT, "character"}:
        raise AssetRemovalError("不支持的素材类型")
    try:
        key = validate_windows_path_component(str(aa_key), label="asset key")
    except ValueError as exc:
        raise AssetRemovalError(str(exc)) from exc
    digest = str(expected_sha256 or "").strip()
    if not digest:
        raise AssetRemovalError("缺少素材内容摘要")
    directories = (target.project_dir, target.save_dir)
    manifest_paths = tuple(root / "manifest.json" for root in directories)
    originals: dict[Path, bytes | None] = {}
    staged: list[tuple[Path, Path]] = []
    staging_roots: list[Path] = []

    try:
        with project_target_lock(target):
            assert_aa_closed(running_probe=running_probe)
            manifests = [load_manifest(root) for root in directories]
            entries = []
            install_paths = []
            for root, manifest in zip(directories, manifests):
                if kind == "character":
                    entry, installed = _character_removal_entry(
                        root, manifest, aa_key=key, expected_sha256=digest
                    )
                else:
                    entry, installed = _simple_removal_entry(
                        root,
                        manifest,
                        kind=kind,
                        aa_key=key,
                        expected_sha256=digest,
                    )
                entries.append(entry)
                install_paths.append(installed)
            if entries[0] != entries[1]:
                raise AssetRemovalError("project/save 素材登记不一致")

            result = RemovalResult(
                kind=kind,
                aa_key=key,
                install_dirs=tuple(install_paths),
                manifest_paths=manifest_paths,
                changed=True,
            )
            originals = {
                path: path.read_bytes() if path.is_file() else None
                for path in manifest_paths
            }
            for root, installed in zip(directories, install_paths):
                stage_root = root / f".aa-remove-{uuid.uuid4().hex}"
                stage_root.mkdir(parents=True)
                staged_path = stage_root / installed.name
                os.replace(installed, staged_path)
                staging_roots.append(stage_root)
                staged.append((staged_path, installed))

            for manifest, entry in zip(manifests, entries):
                if kind == "character":
                    manifest["CharacterOverrides"] = [
                        row for row in manifest["CharacterOverrides"] if row != entry
                    ]
                else:
                    manifest_key = _REMOVAL_LAYOUT[kind][0]
                    manifest[manifest_key] = [
                        value for value in manifest[manifest_key] if value != entry
                    ]
            for root, manifest in zip(directories, manifests):
                write_manifest_atomic(root, manifest)
            if after_remove is not None:
                after_remove(result)
    except Exception as exc:
        for path, original in originals.items():
            try:
                _restore_manifest(path, original)
            except OSError:
                pass
        for staged_path, installed in reversed(staged):
            try:
                installed.parent.mkdir(parents=True, exist_ok=True)
                if staged_path.exists() and not installed.exists():
                    os.replace(staged_path, installed)
            except OSError:
                pass
        for stage_root in staging_roots:
            shutil.rmtree(stage_root, ignore_errors=True)
        if isinstance(exc, AssetRemovalError):
            raise
        raise AssetRemovalError(str(exc)) from exc

    for stage_root in staging_roots:
        shutil.rmtree(stage_root, ignore_errors=True)
    return result
