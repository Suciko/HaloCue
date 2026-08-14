"""Resolve immutable application resources and writable HaloCue user state."""

from __future__ import annotations

import json
import os
import shutil
import sys
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
    layout.user_data_root.mkdir(parents=True, exist_ok=True)
    layout.out_root.mkdir(parents=True, exist_ok=True)

    seed_db = layout.resource_root / "aa_assets.db"
    if not layout.database_path.exists() and seed_db.is_file():
        shutil.copy2(seed_db, layout.database_path)

    seed_index = layout.resource_root / "aa_resources.json"
    if not layout.resource_index_path.exists() and seed_index.is_file():
        try:
            data = json.loads(seed_index.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            shutil.copy2(seed_index, layout.resource_index_path)
        else:
            if isinstance(data, dict):
                data["_source"] = ""
            layout.resource_index_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=1),
                encoding="utf-8",
            )


LAYOUT = resolve_runtime_layout()
