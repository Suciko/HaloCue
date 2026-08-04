"""Read-only discovery of an AzureArchive installation and workspace."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class UnityIdentity:
    vendor: str
    product: str


@dataclass(frozen=True)
class DiscoveryIssue:
    code: str
    message: str
    path: Path | None = None


@dataclass(frozen=True)
class PathCandidate:
    path: Path
    source: str
    valid: bool


@dataclass(frozen=True)
class AADiscoveryResult:
    executable: Path | None
    install_root: Path | None
    identity: UnityIdentity | None
    local_low_root: Path | None
    data: Path | None
    projects: Path | None
    saves: Path | None
    overrides: Path | None
    settings: Path | None
    resource_cache: Path | None
    catalog: Path | None
    recent_project_files: tuple[Path, ...]
    data_candidates: tuple[PathCandidate, ...]
    requires_selection: bool
    source: str | None
    issues: tuple[DiscoveryIssue, ...]


def _resolved(value: str | os.PathLike | None) -> Path | None:
    if value is None:
        return None
    try:
        path = Path(value).expanduser()
        return path.resolve()
    except (OSError, TypeError, ValueError):
        return None


def normalize_aa_data_path(value: str | os.PathLike | None) -> Path | None:
    """Accept an AA ``data`` directory or the workspace containing it."""
    candidate = _resolved(value)
    if candidate is None:
        return None
    for data in (candidate, candidate / "data"):
        if data.is_dir() and (data / "projects").is_dir():
            return data.resolve()
    return None


def read_unity_identity(value: str | os.PathLike | None) -> UnityIdentity | None:
    """Read the vendor and product pair from an AA Unity ``app.info`` file."""
    executable = _resolved(value)
    if executable is None:
        return None
    app_info = executable.parent / "AzureArchive_Data" / "app.info"
    try:
        raw = app_info.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return None
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(lines) < 2:
        return None
    return UnityIdentity(vendor=lines[0], product=lines[1])


def resolve_aa_executable(value: str | os.PathLike | None) -> Path | None:
    """Return a verified AzureArchive executable from a file or known directory."""
    candidate = _resolved(value)
    if candidate is None:
        return None
    choices = (
        (candidate,)
        if candidate.is_file()
        else (candidate / "AzureArchive.exe", candidate / "App" / "AzureArchive.exe")
    )
    for executable in choices:
        if (
            executable.is_file()
            and executable.name.casefold() == "azurearchive.exe"
            and read_unity_identity(executable) is not None
        ):
            return executable.resolve()
    return None


def _local_low_root(identity: UnityIdentity | None, home: str | os.PathLike | None) -> Path | None:
    if identity is None:
        return None
    base = _resolved(home) if home is not None else Path.home().resolve()
    if base is None:
        return None
    return base / "AppData" / "LocalLow" / identity.vendor / identity.product


def _read_json_object(path: Path | None, issues: list[DiscoveryIssue], code: str) -> dict:
    if path is None or not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        issues.append(DiscoveryIssue(code, "Unable to read JSON configuration.", path))
        return {}
    if not isinstance(value, dict):
        issues.append(DiscoveryIssue(code, "JSON configuration must be an object.", path))
        return {}
    return value


def _string_value(mapping: Mapping, key: str) -> str | None:
    value = mapping.get(key)
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _read_recent_project_files(settings: Mapping) -> tuple[Path, ...]:
    visited = settings.get("visitedFiles")
    if not isinstance(visited, list):
        return ()
    result: list[Path] = []
    seen: set[str] = set()
    for value in visited:
        if not isinstance(value, (str, os.PathLike)):
            continue
        path = _resolved(value)
        if path is None or not path.is_file() or path.suffix.casefold() not in {".aap", ".aas"}:
            continue
        key = os.path.normcase(str(path))
        if key not in seen:
            seen.add(key)
            result.append(path)
    return tuple(result)


def _candidate(value: str | os.PathLike | None, source: str) -> PathCandidate | None:
    raw = _resolved(value)
    if raw is None:
        return None
    data = normalize_aa_data_path(raw)
    return PathCandidate(path=data or raw, source=source, valid=data is not None)


def _workspace_candidates(
    settings: Mapping,
    local_low: Path | None,
    saved_data: str | os.PathLike | None,
    environ: Mapping[str, str],
) -> tuple[PathCandidate | None, PathCandidate | None, tuple[PathCandidate, ...]]:
    workspace = _string_value(settings, "workspacePath")
    authoritative = _candidate(workspace, "user_settings.workspacePath")
    local = _candidate(local_low / "data" if local_low else None, "LocalLow data")
    legacy = tuple(
        candidate
        for candidate in (
            _candidate(saved_data, "aa_config.json.aa_data"),
            _candidate(environ.get("AA_DATA"), "environment.AA_DATA"),
        )
        if candidate is not None
    )
    return authoritative, local, legacy


def _install_root(executable: Path | None) -> Path | None:
    if executable is None:
        return None
    return executable.parent.parent if executable.parent.name.casefold() == "app" else executable.parent


def _catalog_path(executable: Path | None) -> Path | None:
    if executable is None:
        return None
    catalog = executable.parent / "AzureArchive_Data" / "StreamingAssets" / "aa" / "catalog.json"
    return catalog.resolve() if catalog.is_file() else None


def _resource_cache(data: Path, settings: Mapping, issues: list[DiscoveryIssue]) -> Path | None:
    configured = _string_value(settings, "cachePath")
    if configured is not None:
        path = _resolved(configured)
        if path is not None and path.is_dir():
            return path
        issues.append(DiscoveryIssue("resource_cache_missing", "Configured resource cache is unavailable.", path))
        return None
    sibling = data.parent.parent / "资源文件"
    return sibling.resolve() if sibling.is_dir() else None


def _result_for_data(
    data: Path,
    *,
    source: str,
    executable: Path | None = None,
    identity: UnityIdentity | None = None,
    local_low: Path | None = None,
    configuration: Mapping | None = None,
    issues: list[DiscoveryIssue] | None = None,
    data_candidates: tuple[PathCandidate, ...] | None = None,
) -> AADiscoveryResult:
    issues = issues if issues is not None else []
    settings_json = configuration or {}
    optional_paths: dict[str, Path | None] = {}
    for name in ("projects", "saves", "overrides", "settings"):
        path = data / name
        optional_paths[name] = path.resolve() if path.is_dir() else None
        if name != "projects" and optional_paths[name] is None:
            issues.append(DiscoveryIssue("optional_directory_missing", f"Optional {name} directory is missing.", path))
    candidate = PathCandidate(data, source, True)
    return AADiscoveryResult(
        executable=executable,
        install_root=_install_root(executable),
        identity=identity,
        local_low_root=local_low,
        data=data,
        projects=optional_paths["projects"],
        saves=optional_paths["saves"],
        overrides=optional_paths["overrides"],
        settings=optional_paths["settings"],
        resource_cache=_resource_cache(data, settings_json, issues),
        catalog=_catalog_path(executable),
        recent_project_files=_read_recent_project_files(settings_json),
        data_candidates=data_candidates or (candidate,),
        requires_selection=False,
        source=source,
        issues=tuple(issues),
    )


def _empty_result(
    *,
    executable: Path | None,
    identity: UnityIdentity | None,
    local_low: Path | None,
    candidates: tuple[PathCandidate, ...],
    requires_selection: bool,
    issues: list[DiscoveryIssue],
) -> AADiscoveryResult:
    return AADiscoveryResult(
        executable=executable,
        install_root=_install_root(executable),
        identity=identity,
        local_low_root=local_low,
        data=None,
        projects=None,
        saves=None,
        overrides=None,
        settings=None,
        resource_cache=None,
        catalog=_catalog_path(executable),
        recent_project_files=(),
        data_candidates=candidates,
        requires_selection=requires_selection,
        source=None,
        issues=tuple(issues),
    )


def _unique_valid(candidates: tuple[PathCandidate, ...]) -> tuple[PathCandidate, ...]:
    unique: list[PathCandidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate.valid:
            continue
        key = os.path.normcase(str(candidate.path))
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return tuple(unique)


def discover_aa(
    selection: str | os.PathLike | None = None,
    *,
    config_path: str | os.PathLike | None = None,
    home: str | os.PathLike | None = None,
    environ: Mapping[str, str] | None = None,
) -> AADiscoveryResult:
    """Discover AA paths without creating or modifying any filesystem entries."""
    issues: list[DiscoveryIssue] = []
    explicit_data = normalize_aa_data_path(selection)
    if explicit_data is not None:
        return _result_for_data(explicit_data, source="explicit data")

    config_file = _resolved(config_path) if config_path is not None else Path(__file__).with_name("aa_config.json")
    config = _read_json_object(config_file, issues, "config_invalid")
    saved_executable = _string_value(config, "aa_executable")
    saved_data = _string_value(config, "aa_data")
    environment = environ if environ is not None else os.environ

    executable = resolve_aa_executable(selection or saved_executable)
    identity = read_unity_identity(executable) if executable else None
    local_low = _local_low_root(identity, home)
    settings_path = local_low / "data" / "settings" / "user_settings.json" if local_low else None
    settings = _read_json_object(settings_path, issues, "settings_invalid")
    authoritative, local, legacy = _workspace_candidates(settings, local_low, saved_data, environment)

    if authoritative is not None and authoritative.valid:
        return _result_for_data(
            authoritative.path,
            source=authoritative.source,
            executable=executable,
            identity=identity,
            local_low=local_low,
            configuration=settings,
            issues=issues,
            data_candidates=(authoritative,),
        )
    if authoritative is not None:
        issues.append(DiscoveryIssue("workspace_invalid", "Configured workspace does not contain projects.", authoritative.path))

    if local is not None and local.valid:
        return _result_for_data(
            local.path,
            source=local.source,
            executable=executable,
            identity=identity,
            local_low=local_low,
            configuration=settings,
            issues=issues,
            data_candidates=(local,),
        )

    valid_legacy = _unique_valid(legacy)
    if len(valid_legacy) == 1:
        selected = valid_legacy[0]
        return _result_for_data(
            selected.path,
            source=selected.source,
            executable=executable,
            identity=identity,
            local_low=local_low,
            configuration=settings,
            issues=issues,
            data_candidates=valid_legacy,
        )
    if len(valid_legacy) > 1:
        issues.append(DiscoveryIssue("workspace_selection_required", "Multiple valid AA workspaces require selection."))
        return _empty_result(
            executable=executable,
            identity=identity,
            local_low=local_low,
            candidates=valid_legacy,
            requires_selection=True,
            issues=issues,
        )

    if executable is None:
        issues.append(DiscoveryIssue("executable_not_found", "AzureArchive executable was not recognized."))
    issues.append(DiscoveryIssue("workspace_not_found", "No valid AA workspace was found."))
    return _empty_result(
        executable=executable,
        identity=identity,
        local_low=local_low,
        candidates=(),
        requires_selection=False,
        issues=issues,
    )
