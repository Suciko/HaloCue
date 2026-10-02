"""One compatibility implementation per process, with explicit origin checks.

This is not an import sandbox or hot-reload mechanism. Data-only legacy roots keep
using bundled code; a selected code checkout must never fall back to another one.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import threading
from functools import lru_cache
from pathlib import Path
from types import ModuleType

from .errors import ProductionError
from .legacy_module_manifest import FIRST_PARTY_MODULES

CORE_MODULES = (
    "document",
    "draft_store",
    "build_bundle",
    "install_manager",
    "annotate",
    "assetdb",
    "asset_catalog",
    "portrait_layout",
    "asset_import",
    "aa_install_discovery",
)
LAZY_MODULES = (
    "llm",
    "spine_face_analysis",
    "spine_face_renderer",
    "teacher_identity",
    "teacher_presentation",
    "teacher_reply_plan",
    "script2aap",
    "aa_registry",
)
_IMPORT_LOCK = threading.RLock()
_loaded_root: Path | None = None


def _paths(root: Path, name: str) -> tuple[Path, ...]:
    return (
        root / f"{name}.py",
        root / f"{name}.pyc",
        root / name / "__init__.py",
        root / name / "__init__.pyc",
    )


def _code_root(selected: Path) -> Path:
    if not selected.is_dir():
        raise ProductionError(
            "legacy_adapter_unavailable",
            "找不到兼容转换模块",
            status=503,
            details={"legacy_root": str(selected)},
        )
    if any(
        path.is_file() for name in CORE_MODULES + LAZY_MODULES for path in _paths(selected, name)
    ):
        return selected
    # The data root can intentionally contain only an asset catalog/AA configuration.
    # Do not insert it on sys.path or claim its version marker identifies loaded code.
    bundled = _bundled_root()
    if bundled is None:
        raise ProductionError(
            "legacy_adapter_unavailable",
            "数据目录不包含兼容源码，当前安装中也未找到内置实现；请配置完整兼容源码目录后重新启动。",
            status=503,
            details={"legacy_root": str(selected)},
        )
    return bundled


@lru_cache(maxsize=1)
def _bundled_root() -> Path | None:
    if getattr(sys, "_MEIPASS", None):
        return Path(sys._MEIPASS).resolve()
    # Source checkouts and installed packages have different parent depths.
    # Find an actual colocated implementation rather than guessing by index.
    for parent in Path(__file__).resolve().parents:
        if all(
            any(path.is_file() for path in _paths(parent, name))
            for name in ("document", "draft_store", "annotate")
        ):
            return parent
    return None


@lru_cache(maxsize=16)
def _module_names(root: Path) -> frozenset[str]:
    # Include the shipped family too: a file missing from the selected checkout
    # must not silently become a transitive import from the bundled implementation.
    directories = {root}
    bundled = _bundled_root()
    if bundled is not None:
        directories.add(bundled)
    return (
        FIRST_PARTY_MODULES
        | frozenset(CORE_MODULES + LAZY_MODULES)
        | frozenset(path.stem for directory in directories for path in directory.glob("*.py"))
    )


@lru_cache(maxsize=4096)
def _normalized_origin(value: str) -> Path | None:
    # Imported code is pinned until restart; do not redo filesystem resolution for
    # every cached module on every lazy call. A changed __file__ is a new cache key.
    path = Path(value)
    return path.resolve() if path.is_absolute() else None


@lru_cache(maxsize=4096)
def _expected_origins(root: Path, name: str) -> frozenset[Path]:
    # The checkout directory is canonical already. A linked individual source file
    # resolving into a different checkout is mixed code, not another valid origin.
    return frozenset(_paths(root, name))


def _check_origin(root: Path, selected: Path, name: str, origin: object) -> None:
    try:
        actual = _normalized_origin(origin) if isinstance(origin, str) and origin else None
        matches = actual is not None and actual in _expected_origins(root, name)
    except (OSError, ValueError, RuntimeError):
        matches = False
    if not matches:
        raise ProductionError(
            "legacy_module_origin_mismatch",
            "兼容模块来源与所选实现不一致，请关闭当前进程后使用同一套源码重新启动。",
            status=503,
            details={
                "module": name,
                "selected_root": str(selected),
                "code_root": str(root),
                "actual_origin": str(origin) if origin else None,
            },
        )


def _check_cached(root: Path, selected: Path) -> None:
    for name in _module_names(root):
        if name in sys.modules:
            _check_origin(root, selected, name, getattr(sys.modules[name], "__file__", None))


def load_modules(selected_root: Path, names: tuple[str, ...]) -> tuple[Path, dict[str, ModuleType]]:
    """Preflight all requested modules before importing any; never evict global modules."""
    global _loaded_root
    selected = selected_root.resolve()
    with _IMPORT_LOCK:
        root = _code_root(selected)
        if _loaded_root is not None and _loaded_root != root:
            raise ProductionError(
                "legacy_code_root_conflict",
                "当前进程已加载另一套兼容源码，不能在运行中切换；请关闭后使用目标源码重新启动。",
                status=409,
                details={
                    "selected_root": str(selected),
                    "requested_code_root": str(root),
                    "loaded_code_root": str(_loaded_root),
                },
            )
        _check_cached(root, selected)
        for name in names:
            if name in sys.modules:
                _check_origin(root, selected, name, getattr(sys.modules[name], "__file__", None))
            elif not any(path.is_file() for path in _paths(root, name)):
                # Frozen importers can provide modules without loose .py files.
                spec = importlib.util.find_spec(name) if getattr(sys, "frozen", False) else None
                if spec is None:
                    raise ProductionError(
                        "legacy_module_missing",
                        "所选兼容源码不完整，不能混用其他目录的模块。",
                        status=503,
                        details={"module": name, "code_root": str(root)},
                    )
                _check_origin(root, selected, name, spec.origin)
        # Pin before imports: even a failed import may leave transitive modules cached.
        _loaded_root = root
        text = str(root)
        if not sys.path or sys.path[0] != text:
            if text in sys.path:
                sys.path.remove(text)
            sys.path.insert(0, text)
        modules = {}
        for name in names:
            module = importlib.import_module(name)
            _check_origin(root, selected, name, getattr(module, "__file__", None))
            _check_cached(root, selected)
            modules[name] = module
        return root, modules


def load_module(name: str, selected_root: Path) -> ModuleType:
    return load_modules(selected_root, (name,))[1][name]
