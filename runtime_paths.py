"""Resolve immutable packaged resources and per-user writable HaloCue state."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class RuntimeLayout:
    resource_root: Path
    user_data_root: Path
    config_path: Path
    legacy_config_path: Path
    database_path: Path
    database_seed_path: Path
    resource_index_path: Path
    model_profiles_path: Path
    output_root: Path
    thumbs_root: Path


def _resolved_path(value: str | os.PathLike) -> Path:
    return Path(value).expanduser().resolve()


def resolve_runtime_layout(
    *,
    module_file: str | os.PathLike = __file__,
    executable: str | os.PathLike | None = None,
    environ: Mapping[str, str] | None = None,
    frozen_root: str | os.PathLike | None = None,
) -> RuntimeLayout:
    """Return paths without creating any directories or files."""
    environment = os.environ if environ is None else environ
    process_is_frozen = bool(getattr(sys, "frozen", False))
    bundle_root = frozen_root
    if bundle_root is None and process_is_frozen:
        bundle_root = _resolved_path(executable or sys.executable).parent
    if bundle_root is None:
        bundle_root = getattr(sys, "_MEIPASS", None)
    resource_root = _resolved_path(
        bundle_root if bundle_root is not None else Path(module_file).parent
    )
    legacy_config_root = (
        _resolved_path(executable or sys.executable).parent
        if bundle_root is not None
        else resource_root
    )

    override = str(environment.get("HALOCUE_USER_DATA_DIR") or "").strip()
    if override:
        user_data_root = _resolved_path(override)
    else:
        local_app_data = str(environment.get("LOCALAPPDATA") or "").strip()
        if local_app_data:
            local_root = _resolved_path(local_app_data)
        else:
            local_root = Path.home().resolve() / "AppData" / "Local"
        user_data_root = local_root / "HaloCue"

    return RuntimeLayout(
        resource_root=resource_root,
        user_data_root=user_data_root,
        config_path=user_data_root / "aa_config.json",
        legacy_config_path=legacy_config_root / "aa_config.json",
        database_path=user_data_root / "aa_assets.db",
        database_seed_path=(
            resource_root / "data" / "halocue_labels.db"
            if process_is_frozen
            else resource_root / "aa_assets.db"
        ),
        resource_index_path=user_data_root / "aa_resources.json",
        model_profiles_path=user_data_root / "llm_profiles.json",
        output_root=user_data_root / "out",
        thumbs_root=user_data_root / ".thumbs",
    )


def ensure_user_database(layout: RuntimeLayout) -> Path:
    """Atomically initialize the user database from the packaged seed once."""
    destination = layout.database_path
    if destination.exists():
        return destination
    layout.user_data_root.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w+b",
            delete=False,
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
        ) as temporary:
            temporary_path = Path(temporary.name)
            with layout.database_seed_path.open("rb") as seed:
                shutil.copyfileobj(seed, temporary)
            temporary.flush()
            os.fsync(temporary.fileno())
        if destination.exists():
            temporary_path.unlink()
            return destination
        os.replace(temporary_path, destination)
        temporary_path = None
        return destination
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
