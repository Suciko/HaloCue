# -*- coding: utf-8 -*-
"""
AA 剧本编译器 - 安装管理器 (install_manager.py)
实现 Build Bundle 校验、AA 退出拦截 423、delta 合并与 project_install_record.json 安装记录
"""

import datetime
import json
import os
import shutil
import tempfile
from pathlib import Path, PureWindowsPath
from typing import Any, Callable, Dict, Optional

import aapaths
from aa_project_assets import (
    assert_aa_closed,
    resolve_project_target,
    validate_windows_path_component,
)
from aa_registry import (
    MANIFEST_LISTS,
    AssetRegistrationError,
    load_manifest,
    write_manifest_atomic,
)
from build_bundle import calc_file_sha256
from draft_store import DraftStore
from script2aap import install_transaction

HERE = Path(__file__).resolve().parent


class AARunningError(RuntimeError):
    """AA 客户端运行中拦截异常 (HTTP 423 code: aa_running)"""
    pass


class AACorruptBundleError(ValueError):
    """Bundle 损坏或校验失败异常 (HTTP 400 code: corrupted_bundle)"""
    pass


class AAInstallTargetExistsError(FileExistsError):
    """A renamed installation would overwrite an existing AA project."""


def compose_install_project_name(category: str, story_name: str) -> str:
    """Compose one AA project component from an optional one-level category."""
    category = str(category or "").strip()
    story_name = str(story_name or "").strip()
    if category and "-" in category:
        raise ValueError("分类只能是一级分类，不能包含连字符")
    if not story_name:
        raise ValueError("剧情名称不能为空")
    normalized_story = validate_windows_path_component(story_name, label="story name")
    if not category:
        return normalized_story
    normalized_category = validate_windows_path_component(category, label="category")
    return validate_windows_path_component(
        f"{normalized_category}-{normalized_story}", label="project name"
    )


def _manifest_path_key(value: Any) -> str:
    return str(PureWindowsPath(str(value).replace("/", "\\"))).casefold()


def _safe_manifest_relative(value: Any, folder: str) -> Optional[PureWindowsPath]:
    relative = PureWindowsPath(str(value).replace("/", "\\"))
    if (
        relative.is_absolute()
        or relative.drive
        or relative.root
        or ".." in relative.parts
        or len(relative.parts) < 2
        or relative.parts[0].casefold() != folder.casefold()
    ):
        return None
    return relative


def _merge_install_manifests(*manifests: Dict[str, Any]) -> Dict[str, Any]:
    merged = {key: [] for key in MANIFEST_LISTS}
    characters: Dict[str, Dict[str, Any]] = {}
    path_keys = {key: set() for key in MANIFEST_LISTS if key != "CharacterOverrides"}
    for manifest in manifests:
        for row in manifest.get("CharacterOverrides", []):
            identifier = str(row.get("Identifier") or "")
            if not identifier:
                continue
            current = characters.get(identifier)
            if current is None:
                characters[identifier] = dict(row)
                continue
            if not current.get("SpinePortraitPath") and row.get("SpinePortraitPath"):
                for key in (
                    "CharacterReference",
                    "OriginalIdentifier",
                    "SpinePortraitPath",
                    "SmallPortraitPath",
                ):
                    current[key] = row.get(key)
            if row.get("Name"):
                current["Name"] = row["Name"]
            if row.get("Nickname"):
                current["Nickname"] = row["Nickname"]
        for key in path_keys:
            for value in manifest.get(key, []):
                normalized = _manifest_path_key(value)
                if normalized not in path_keys[key]:
                    merged[key].append(str(value))
                    path_keys[key].add(normalized)
    merged["CharacterOverrides"] = list(characters.values())
    return merged


def _append_manifest_path(manifest: Dict[str, Any], key: str, value: str) -> None:
    normalized = _manifest_path_key(value)
    if all(_manifest_path_key(current) != normalized for current in manifest[key]):
        manifest[key].append(value)


def _copy_asset_file(source: Path, destination: Path) -> None:
    if destination.is_file():
        if calc_file_sha256(source) != calc_file_sha256(destination):
            raise AACorruptBundleError(
                f"AA asset conflict: {source} and {destination} differ"
            )
        return
    if destination.exists():
        raise AACorruptBundleError(f"AA asset target is not a file: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _copy_asset_tree(source: Path, *destinations: Path) -> None:
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        for destination in destinations:
            _copy_asset_file(path, destination / relative)


def _tree_signature(root: Path) -> tuple:
    return tuple(
        (path.relative_to(root).as_posix().casefold(), calc_file_sha256(path))
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )


def _aap_asset_references(path: Path) -> tuple[set[str], set[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AACorruptBundleError(f"Bundle AAP is invalid: {path}") from exc
    backgrounds: set[str] = set()
    characters: set[str] = set()
    for node in payload.get("nodes", {}).get("$values", []):
        for script in node.get("Scripts", {}).get("$values", []):
            friendly = str(script.get("bgFriendlyName") or "").strip()
            if friendly:
                backgrounds.add(friendly)
            for character in script.get("characters", {}).get("$values", []):
                identifier = str(character.get("name") or "").strip()
                if identifier:
                    characters.add(identifier)
    return backgrounds, characters


def _bundle_resource_index(project_dir: Path) -> Dict[str, Any]:
    index_path = project_dir / "aa_resources.json"
    try:
        return json.loads(index_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}


def _bundle_character_ids(project_dir: Path) -> set[str]:
    index = _bundle_resource_index(project_dir)
    return {
        str(row.get("identifier") or "")
        for row in index.get("characters", [])
        if row.get("identifier") and str(row.get("spine") or "").strip()
    }


def _bundle_custom_backgrounds(project_dir: Path) -> set[str]:
    labels = _bundle_resource_index(project_dir).get("bg_label", {})
    return set(labels) if isinstance(labels, dict) else set()


def _find_character_source(
    projects_dir: Path,
    identifier: str,
    *,
    expected_signature: Optional[tuple] = None,
) -> Optional[tuple[Dict[str, Any], Path]]:
    candidates = []
    for manifest_path in sorted(projects_dir.glob("*/manifest.json")):
        project_dir = manifest_path.parent
        try:
            manifest = load_manifest(project_dir)
        except AssetRegistrationError:
            continue
        for row in manifest["CharacterOverrides"]:
            if str(row.get("Identifier") or "") != identifier:
                continue
            spine = str(row.get("SpinePortraitPath") or "")
            if not spine:
                continue
            relative = _safe_manifest_relative(spine, "characters")
            if (
                relative is None
                or len(relative.parts) < 3
                or relative.parts[1] != identifier
            ):
                continue
            asset_dir = project_dir.joinpath(relative.parts[0], relative.parts[1])
            base = project_dir.joinpath(*relative.parts)
            required = [Path(str(base) + suffix) for suffix in (".skel", ".atlas", ".png")]
            avatar = str(row.get("SmallPortraitPath") or "")
            if avatar:
                avatar_relative = _safe_manifest_relative(avatar, "characters")
                if avatar_relative is None or avatar_relative.parts[1] != identifier:
                    continue
                required.append(project_dir.joinpath(*avatar_relative.parts))
            if asset_dir.is_dir() and all(path.is_file() for path in required):
                candidates.append((dict(row), asset_dir, _tree_signature(asset_dir)))
    if not candidates:
        return None
    if expected_signature is not None:
        candidates = [
            candidate for candidate in candidates if candidate[2] == expected_signature
        ]
        if not candidates:
            return None
    signatures = {candidate[2] for candidate in candidates}
    if len(signatures) != 1:
        raise AACorruptBundleError(
            f"AA contains conflicting asset copies for character {identifier}"
        )
    row, asset_dir, _ = candidates[0]
    return row, asset_dir


def _find_simple_asset_source(
    projects_dir: Path, *, folder: str, manifest_key: str, stem: str
) -> Optional[Path]:
    candidates = []
    for manifest_path in sorted(projects_dir.glob("*/manifest.json")):
        project_dir = manifest_path.parent
        try:
            manifest = load_manifest(project_dir)
        except AssetRegistrationError:
            continue
        for value in manifest[manifest_key]:
            relative = _safe_manifest_relative(value, folder)
            if (
                relative is None
                or len(relative.parts) != 2
                or relative.stem.casefold() != stem.casefold()
            ):
                continue
            source = project_dir.joinpath(*relative.parts)
            if source.is_file():
                candidates.append(source)
    if not candidates:
        return None
    hashes = {calc_file_sha256(path) for path in candidates}
    if len(hashes) != 1:
        raise AACorruptBundleError(
            f"AA contains conflicting asset copies for background {stem}"
        )
    return candidates[0]


def _reconcile_simple_assets(
    manifest: Dict[str, Any], project_dir: Path, save_dir: Path
) -> None:
    specs = (
        ("bgs", "BgOverrides", {".png", ".jpg", ".jpeg", ".webp"}),
        ("sounds", "SoundOverrides", {".ogg", ".wav", ".mp3"}),
        ("bgms", "BgmOverrides", {".ogg", ".wav", ".mp3"}),
    )
    for folder, key, suffixes in specs:
        sources: Dict[str, Path] = {}
        for root in (project_dir, save_dir):
            directory = root / folder
            if not directory.is_dir():
                continue
            for path in sorted(directory.iterdir()):
                if path.is_file() and path.suffix.casefold() in suffixes:
                    known = sources.get(path.name.casefold())
                    if known and calc_file_sha256(known) != calc_file_sha256(path):
                        raise AACorruptBundleError(
                            f"AA project/save asset conflict: {known} and {path} differ"
                        )
                    sources[path.name.casefold()] = path
        kept = []
        for value in manifest[key]:
            relative = _safe_manifest_relative(value, folder)
            if (
                relative is not None
                and len(relative.parts) == 2
                and relative.name.casefold() in sources
            ):
                kept.append(str(value))
        manifest[key] = kept
        for source in sources.values():
            for root in (project_dir, save_dir):
                _copy_asset_file(source, root / folder / source.name)
            _append_manifest_path(
                manifest, key, str(PureWindowsPath(folder, source.name))
            )


def _reconcile_voice_assets(
    manifest: Dict[str, Any], project_dir: Path, save_dir: Path
) -> None:
    kept = []
    for value in manifest["VoiceOverrides"]:
        relative = _safe_manifest_relative(value, "voices")
        if relative is None:
            continue
        paths = [root.joinpath(*relative.parts) for root in (project_dir, save_dir)]
        sources = [path for path in paths if path.is_file()]
        if not sources:
            continue
        if len(sources) == 2 and calc_file_sha256(sources[0]) != calc_file_sha256(
            sources[1]
        ):
            raise AACorruptBundleError(
                f"AA project/save voice conflict: {sources[0]} and {sources[1]} differ"
            )
        for path in paths:
            _copy_asset_file(sources[0], path)
        kept.append(str(value))
    manifest["VoiceOverrides"] = kept


def _repair_install_assets(
    *,
    projects_dir: Path,
    project_dir: Path,
    save_dir: Path,
    bundle_project_dir: Path,
    aap_path: Path,
    manifest: Dict[str, Any],
) -> Dict[str, Any]:
    referenced_backgrounds, referenced_characters = _aap_asset_references(aap_path)
    _reconcile_simple_assets(manifest, project_dir, save_dir)
    _reconcile_voice_assets(manifest, project_dir, save_dir)

    registered_backgrounds = {
        PureWindowsPath(value).stem for value in manifest["BgOverrides"]
    }
    for stem in sorted(referenced_backgrounds - registered_backgrounds):
        source = _find_simple_asset_source(
            projects_dir, folder="bgs", manifest_key="BgOverrides", stem=stem
        )
        if source is None:
            continue
        for root in (project_dir, save_dir):
            _copy_asset_file(source, root / "bgs" / source.name)
        _append_manifest_path(
            manifest, "BgOverrides", str(PureWindowsPath("bgs", source.name))
        )
    registered_backgrounds = {
        PureWindowsPath(value).stem.casefold() for value in manifest["BgOverrides"]
    }
    unresolved_backgrounds = sorted(
        stem
        for stem in referenced_backgrounds & _bundle_custom_backgrounds(
            bundle_project_dir
        )
        if stem.casefold() not in registered_backgrounds
    )
    if unresolved_backgrounds:
        raise AACorruptBundleError(
            "AAP references custom backgrounds that are not installed in this project: "
            + ", ".join(unresolved_backgrounds)
        )

    by_identifier = {
        str(row.get("Identifier") or ""): row
        for row in manifest["CharacterOverrides"]
        if row.get("Identifier")
    }
    physical_identifiers = set()
    for root in (project_dir, save_dir):
        directory = root / "characters"
        if directory.is_dir():
            physical_identifiers.update(
                path.name for path in directory.iterdir() if path.is_dir()
            )
    official_identifiers = _bundle_character_ids(bundle_project_dir)
    for identifier in sorted(physical_identifiers | referenced_characters):
        if identifier in by_identifier or identifier in official_identifiers:
            continue
        existing_directories = [
            root / "characters" / identifier
            for root in (project_dir, save_dir)
            if (root / "characters" / identifier).is_dir()
        ]
        existing_signatures = {
            _tree_signature(directory) for directory in existing_directories
        }
        if len(existing_signatures) > 1:
            raise AACorruptBundleError(
                f"AA project/save character conflict: {identifier} differs"
            )
        expected_signature = next(iter(existing_signatures), None)
        source = _find_character_source(
            projects_dir,
            identifier,
            expected_signature=expected_signature,
        )
        if source is None:
            continue
        row, asset_dir = source
        _copy_asset_tree(
            asset_dir,
            project_dir / "characters" / identifier,
            save_dir / "characters" / identifier,
        )
        manifest["CharacterOverrides"].append(row)
        by_identifier[identifier] = row

    unresolved = sorted(
        identifier
        for identifier in referenced_characters
        if identifier not in by_identifier and identifier not in official_identifiers
    )
    if unresolved:
        raise AACorruptBundleError(
            "AAP references characters that are not installed in this project: "
            + ", ".join(unresolved)
        )
    return manifest


class InstallManager:
    def __init__(
        self,
        store: Optional[DraftStore] = None,
        aa_data_dir: Optional[str] = None,
        record_path: Optional[str] = None,
        running_probe: Optional[Callable[[], bool]] = None,
    ):
        self.store = store or DraftStore()
        self.aa_data_dir = aa_data_dir
        self.running_probe = running_probe
        if record_path:
            self.record_path = Path(record_path)
        else:
            self.record_path = HERE / "out" / "project_install_record.json"

    def find_bundle_dir(self, token: str, build_id: str) -> Path:
        draft_dir = self.store.get_draft_path(token)
        builds_root = draft_dir / "builds"
        if not builds_root.is_dir():
            raise AACorruptBundleError(f"Builds directory missing for token {token}")

        # 遍历 builds/<content_revision>/<build_id>
        for rev_dir in builds_root.iterdir():
            if rev_dir.is_dir() and rev_dir.name != ".tmp":
                candidate = rev_dir / build_id
                if candidate.is_dir():
                    return candidate

        raise AACorruptBundleError(f"Build ID {build_id} not found under draft {token}")

    def verify_bundle(self, bundle_dir: Path):
        complete_file = bundle_dir / "bundle.complete"
        if not complete_file.is_file():
            raise AACorruptBundleError(f"Bundle incomplete: {bundle_dir}")

        files_manifest_file = bundle_dir / "files.json"
        if not files_manifest_file.is_file():
            raise AACorruptBundleError(f"Bundle files.json missing: {bundle_dir}")

        files_list = json.loads(files_manifest_file.read_text(encoding="utf-8"))
        for item in files_list:
            rel_path = item["path"]
            expected_sha = item["sha256"]
            target_f = bundle_dir / rel_path

            if not target_f.is_file():
                raise AACorruptBundleError(f"Bundle file missing: {rel_path}")

            actual_sha = calc_file_sha256(target_f)
            if actual_sha != expected_sha:
                raise AACorruptBundleError(f"Bundle file hash mismatch for {rel_path}")

    def install_options(self, token: str, build_id: str) -> Dict[str, Any]:
        bundle_dir = self.find_bundle_dir(token, build_id)
        try:
            build_meta = json.loads(
                (bundle_dir / "build.json").read_text(encoding="utf-8")
            )
            source_project = validate_windows_path_component(
                build_meta["project"], label="source project name"
            )
        except (KeyError, OSError, json.JSONDecodeError, ValueError) as exc:
            raise AACorruptBundleError(f"Bundle build.json is invalid: {bundle_dir}") from exc

        aa_data = self.aa_data_dir
        if not aa_data:
            aa_data = aapaths.require(None)["data"]
        projects_dir = Path(aa_data) / "projects"
        categories = set()
        try:
            records = json.loads(self.record_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            records = {}
        if isinstance(records, dict):
            for record in records.values():
                if not isinstance(record, dict):
                    continue
                category = str(record.get("category") or "").strip()
                if category and "-" not in category:
                    try:
                        categories.add(
                            validate_windows_path_component(category, label="category")
                        )
                    except ValueError:
                        continue
        result = {
            "ok": True,
            "source_project": source_project,
            "default_category": "",
            "default_story_name": source_project,
            "categories": sorted(categories),
        }
        installed_project = source_project
        try:
            session = json.loads(
                (self.store.get_draft_path(token) / "session.json").read_text(
                    encoding="utf-8"
                )
            )
            if session.get("last_installed_build_id") == build_id:
                installed_project = validate_windows_path_component(
                    session.get("last_installed_project") or source_project,
                    label="installed project name",
                )
        except (OSError, json.JSONDecodeError, ValueError):
            installed_project = source_project
        installed_aap = projects_dir / f"{installed_project}.aap"
        if installed_aap.is_file():
            result["existing_install"] = {
                "project": installed_project,
                "aap_path": str(installed_aap),
                "project_dir": str(projects_dir / installed_project),
                "save_dir": str(Path(aa_data) / "saves" / installed_project),
            }
        return result

    @staticmethod
    def _write_renamed_aap(source: Path, destination: Path, project_name: str):
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AACorruptBundleError(f"Bundle AAP is invalid: {source}") from exc
        if not isinstance(payload, dict) or "ProjectName" not in payload:
            raise AACorruptBundleError(f"Bundle AAP has no ProjectName: {source}")
        payload["ProjectName"] = project_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=str(destination.parent)
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
                json.dump(payload, output, ensure_ascii=False, separators=(",", ":"))
            os.replace(temporary, destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    @staticmethod
    def _copy_story_assets(source: Path, destination: Path):
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)

    @staticmethod
    def _rename_install_metadata(project_dir: Path, project_name: str):
        delta_file = project_dir / "manifest_delta.json"
        if not delta_file.is_file():
            return
        try:
            delta = json.loads(delta_file.read_text(encoding="utf-8"))
            for item in delta.get("add", []):
                if isinstance(item, dict) and item.get("type") == "project":
                    item["name"] = project_name
            delta_file.write_text(
                json.dumps(delta, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except (OSError, json.JSONDecodeError, AttributeError) as exc:
            raise AACorruptBundleError(
                f"Bundle manifest_delta.json is invalid: {delta_file}"
            ) from exc

    def install_build(
        self,
        token: str,
        build_id: str,
        *,
        category: str = "",
        story_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        # 1. 查找 Bundle
        bundle_dir = self.find_bundle_dir(token, build_id)

        # 2. 校验 Bundle SHA256
        self.verify_bundle(bundle_dir)

        # 3. 验证 AA 客户端已关闭
        try:
            if self.running_probe is None:
                assert_aa_closed()
            else:
                assert_aa_closed(running_probe=self.running_probe)
        except RuntimeError as exc:
            raise AARunningError(str(exc)) from exc
        except Exception as exc:
            if type(exc).__name__ == "AARunningError":
                raise
            raise AARunningError(str(exc)) from exc

        # 4. 获取目标路径
        aa_data = self.aa_data_dir
        if not aa_data:
            P = aapaths.require(None)
            aa_data = P["data"]

        build_meta = json.loads((bundle_dir / "build.json").read_text(encoding="utf-8"))
        source_project = validate_windows_path_component(
            build_meta["project"], label="source project name"
        )
        category = str(category or "").strip()
        project_name = compose_install_project_name(
            category, source_project if story_name is None else story_name
        )

        projects_dir = Path(aa_data) / "projects"
        saves_dir = Path(aa_data) / "saves"
        projects_dir.mkdir(parents=True, exist_ok=True)
        saves_dir.mkdir(parents=True, exist_ok=True)

        aap_dest = projects_dir / f"{project_name}.aap"
        proj_res_dest = projects_dir / project_name
        save_res_dest = saves_dir / project_name
        if project_name != source_project and any(
            target.exists() for target in (aap_dest, proj_res_dest, save_res_dest)
        ):
            raise AAInstallTargetExistsError(
                f"AA 中已存在“{project_name}”，请更换分类或剧情名称"
            )

        # 5. 复制安装 AAP 与工程文件
        aap_source = bundle_dir / f"{source_project}.aap"
        proj_res_source = bundle_dir / "project"
        source_manifests = [
            load_manifest(projects_dir / source_project),
            load_manifest(saves_dir / source_project),
            load_manifest(proj_res_source),
        ]
        install_target = resolve_project_target(
            proj_res_dest, saves_root=saves_dir
        )
        with install_transaction(
            install_target, aap_path=aap_dest, running_probe=self.running_probe
        ):
            if aap_source.is_file():
                if project_name == source_project:
                    shutil.copy2(aap_source, aap_dest)
                else:
                    self._write_renamed_aap(aap_source, aap_dest, project_name)

            if project_name != source_project:
                self._copy_story_assets(projects_dir / source_project, proj_res_dest)
                self._copy_story_assets(saves_dir / source_project, save_res_dest)
            if proj_res_source.is_dir():
                shutil.copytree(proj_res_source, proj_res_dest, dirs_exist_ok=True)
                # 同时也复制到 saves 镜像
                shutil.copytree(proj_res_source, save_res_dest, dirs_exist_ok=True)
            merged_manifest = _repair_install_assets(
                projects_dir=projects_dir,
                project_dir=proj_res_dest,
                save_dir=save_res_dest,
                bundle_project_dir=proj_res_source,
                aap_path=aap_dest,
                manifest=_merge_install_manifests(*source_manifests),
            )
            write_manifest_atomic(proj_res_dest, merged_manifest)
            write_manifest_atomic(save_res_dest, merged_manifest)
            if project_name != source_project:
                self._rename_install_metadata(proj_res_dest, project_name)
                self._rename_install_metadata(save_res_dest, project_name)

        # 6. 记录项目级安装状态 project_install_record.json
        self.record_path.parent.mkdir(parents=True, exist_ok=True)
        records = {}
        if self.record_path.is_file():
            try:
                records = json.loads(self.record_path.read_text(encoding="utf-8"))
            except Exception:
                records = {}

        records[project_name] = {
            "project": project_name,
            "source_project": source_project,
            "category": category,
            "installed_build_id": build_id,
            "installed_at": datetime.datetime.now().isoformat(),
            "source_draft_token": token,
        }
        self.record_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

        # 7. 更新草稿会话中的安装记录
        draft_dir = self.store.get_draft_path(token)
        with self.store.draft_lock(token):
            session_file = draft_dir / "session.json"
            if session_file.is_file():
                sess = json.loads(session_file.read_text(encoding="utf-8"))
                sess["last_installed_build_id"] = build_id
                sess["last_installed_project"] = project_name
                sess["installed_at"] = datetime.datetime.now().isoformat()
                session_file.write_text(json.dumps(sess, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "ok": True,
            "project": project_name,
            "source_project": source_project,
            "installed_build_id": build_id,
            "aap_path": str(aap_dest),
            "project_dir": str(proj_res_dest),
            "save_dir": str(save_res_dest),
        }
