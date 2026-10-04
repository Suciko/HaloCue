"""Locate the shipped 1.0 services in source and frozen distributions."""

from pathlib import Path
import os
import sys


def repository_root() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root is not None:
        return Path(frozen_root).resolve()
    return Path(__file__).resolve().parents[2]


def service_root(name: str) -> Path:
    return repository_root() / "services" / "halocue" / name


def integrated_data_root() -> Path:
    explicit = os.environ.get("HALOCUE_USER_DATA_DIR")
    if explicit:
        return Path(explicit).expanduser().resolve() / "integrated"
    if getattr(sys, "frozen", False):
        from runtime_layout import LAYOUT

        return LAYOUT.user_data_root / "integrated"
    # Preserve existing source workspaces; desktop distributions use LocalAppData.
    return repository_root() / ".halocue" / "integrated"


def enable_service_imports() -> None:
    for name in ("writing", "production", "integrated"):
        path = str(service_root(name) / "src")
        if path not in sys.path:
            sys.path.insert(0, path)
