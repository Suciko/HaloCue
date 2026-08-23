"""Resolve immutable application resources and writable HaloCue user state."""

from __future__ import annotations

import json
import os
import shutil
import sys
import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class RuntimeLayout:
    resource_root: Path
    user_data_root: Path
    out_root: Path
    config_path: Path
    database_path: Path
    resource_index_path: Path
    model_profiles_path: Path
    llm_config_path: Path
    frozen: bool


_PREPARED_FROZEN_LAYOUTS: set[tuple[str, str]] = set()


def _merge_seed_value(existing, seed):
    """Add missing packaged catalogue data without replacing user data."""
    if existing in (None, "", [], {}):
        return copy.deepcopy(seed)
    if isinstance(existing, dict) and isinstance(seed, dict):
        merged = copy.deepcopy(existing)
        for key, value in seed.items():
            if key not in merged:
                merged[key] = copy.deepcopy(value)
            else:
                merged[key] = _merge_seed_value(merged[key], value)
        return merged
    if isinstance(existing, list) and isinstance(seed, list):
        # Resource rows are keyed by identifier/face id.  Preserve the old
        # row when it exists, then append rows introduced by the new package.
        key_name = "identifier" if any(
            isinstance(item, dict) and "identifier" in item for item in [*existing, *seed]
        ) else "id" if any(
            isinstance(item, dict) and "id" in item for item in [*existing, *seed]
        ) else None
        if key_name:
            positions = {
                str(item.get(key_name)): index
                for index, item in enumerate(existing)
                if isinstance(item, dict) and item.get(key_name) not in (None, "")
            }
            merged = copy.deepcopy(existing)
            for item in seed:
                if not isinstance(item, dict) or item.get(key_name) in (None, ""):
                    if item not in merged:
                        merged.append(copy.deepcopy(item))
                    continue
                key = str(item[key_name])
                if key in positions:
                    index = positions[key]
                    merged[index] = _merge_seed_value(merged[index], item)
                else:
                    positions[key] = len(merged)
                    merged.append(copy.deepcopy(item))
            return merged
        merged = copy.deepcopy(existing)
        for item in seed:
            if item not in merged:
                merged.append(copy.deepcopy(item))
        return merged
    return existing


def _merge_resource_index(existing: dict, seed: dict) -> dict:
    """Upgrade a stale per-user index while retaining custom additions."""
    merged = _merge_seed_value(existing, seed)
    if not isinstance(merged, dict):
        merged = copy.deepcopy(seed)
    # Build paths must never leak into a user's writable state.
    merged["_source"] = ""
    return merged


def _file_signature(path: Path) -> dict[str, int] | None:
    """Return a cheap package-file signature used to avoid repeat startup I/O."""
    try:
        stat = path.stat()
    except OSError:
        return None
    return {"size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}


def _read_seed_stamp(path: Path) -> dict[str, int] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _write_seed_stamp(path: Path, signature: dict[str, int]) -> None:
    try:
        path.write_text(
            json.dumps(signature, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
    except OSError:
        # The index itself remains usable if the optional acceleration marker
        # cannot be written (for example, a read-only portable directory).
        return


def resolve_runtime_layout(
    *,
    module_file: str | os.PathLike = __file__,
    executable: str | os.PathLike | None = None,
    environ: Mapping[str, str] | None = None,
    frozen_root: str | os.PathLike | None = None,
) -> RuntimeLayout:
    env = os.environ if environ is None else environ
    frozen = frozen_root is not None or bool(getattr(sys, "frozen", False))
    if frozen_root is not None:
        resources = Path(frozen_root).resolve()
    elif frozen:
        resources = Path(getattr(sys, "_MEIPASS")).resolve()
    else:
        resources = Path(module_file).resolve().parent

    explicit_state = str(env.get("HALOCUE_USER_DATA_DIR") or "").strip()
    if explicit_state:
        state = Path(explicit_state).expanduser().resolve()
    elif frozen:
        local = str(env.get("LOCALAPPDATA") or "").strip()
        if local:
            state = (Path(local) / "HaloCue").resolve()
        else:
            state = (Path.home() / "AppData" / "Local" / "HaloCue").resolve()
    else:
        state = resources

    return RuntimeLayout(
        resource_root=resources,
        user_data_root=state,
        out_root=(state / "out").resolve(),
        config_path=(state / "aa_config.json").resolve(),
        database_path=(state / "aa_assets.db").resolve(),
        resource_index_path=(state / "aa_resources.json").resolve(),
        model_profiles_path=(state / "llm_profiles.json").resolve(),
        llm_config_path=(state / "llm.json").resolve(),
        frozen=frozen,
    )


def prepare_user_state(layout: RuntimeLayout) -> None:
    layout_key = (
        str(layout.resource_root),
        str(layout.user_data_root),
    )
    if layout.frozen and layout_key in _PREPARED_FROZEN_LAYOUTS:
        return
    layout.user_data_root.mkdir(parents=True, exist_ok=True)
    layout.out_root.mkdir(parents=True, exist_ok=True)

    seed_db = layout.resource_root / "aa_assets.db"
    if not layout.database_path.exists() and seed_db.is_file():
        shutil.copy2(seed_db, layout.database_path)

    seed_index = layout.resource_root / "aa_resources.json"
    if seed_index.is_file():
        seed_signature = _file_signature(seed_index)
        stamp_path = layout.user_data_root / ".aa_resources_seed.json"
        # The packaged catalogue is immutable. Once this exact seed has been
        # merged, do not parse and rewrite ~36 MB on every desktop launch.
        stamp_current = (
            layout.frozen
            and seed_signature is not None
            and layout.resource_index_path.is_file()
            and _read_seed_stamp(stamp_path) == seed_signature
        )
        if not stamp_current:
            try:
                seed_data = json.loads(seed_index.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                seed_data = None
            if isinstance(seed_data, dict):
                if layout.resource_index_path.is_file():
                    try:
                        current_data = json.loads(
                            layout.resource_index_path.read_text(encoding="utf-8")
                        )
                    except (OSError, ValueError, TypeError):
                        current_data = {}
                    merged_data = _merge_resource_index(
                        current_data if isinstance(current_data, dict) else {}, seed_data
                    )
                else:
                    merged_data = _merge_resource_index({}, seed_data)
                try:
                    current_text = layout.resource_index_path.read_text(encoding="utf-8")
                except OSError:
                    current_text = ""
                merged_text = json.dumps(merged_data, ensure_ascii=False, indent=1)
                if current_text != merged_text:
                    layout.resource_index_path.write_text(
                        merged_text,
                        encoding="utf-8",
                    )
                if layout.frozen and seed_signature is not None:
                    _write_seed_stamp(stamp_path, seed_signature)

    seed_config = layout.resource_root / "aa_config.seed.json"
    if not seed_config.is_file():
        return
    try:
        defaults = json.loads(seed_config.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return
    if not isinstance(defaults, dict):
        return

    raw_overlays = defaults.get("asset_databases")
    packaged_overlays = []
    for value in raw_overlays if isinstance(raw_overlays, list) else []:
        relative = Path(str(value))
        if relative.is_absolute() or ".." in relative.parts:
            continue
        source = layout.resource_root / relative
        target = layout.user_data_root / relative
        if not source.is_file():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        source_signature = _file_signature(source)
        target_signature = _file_signature(target)
        if source_signature is not None and target_signature == source_signature:
            packaged_overlays.append(relative.as_posix())
            continue
        shutil.copy2(source, target)
        packaged_overlays.append(relative.as_posix())

    try:
        current = json.loads(layout.config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        current = {}
    if not isinstance(current, dict):
        current = {}
    existing = current.get("asset_databases")
    if isinstance(existing, (str, os.PathLike)):
        existing = [str(existing)]
    if not isinstance(existing, list):
        existing = []
    combined = []
    seen = set()
    for value in [*packaged_overlays, *existing]:
        text = str(value).strip()
        if not text or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        combined.append(text)
    current.update({
        "pipeline": str(defaults.get("pipeline") or "0.95"),
        "prompt_revision": str(defaults.get("prompt_revision") or ""),
        "database_policy": "read_only_overlay",
        "asset_databases": combined,
    })
    layout.config_path.write_text(
        json.dumps(current, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if layout.frozen:
        _PREPARED_FROZEN_LAYOUTS.add(layout_key)


LAYOUT = resolve_runtime_layout()
