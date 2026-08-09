# -*- coding: utf-8 -*-
"""
跨机器路径探测。

AA 的存储目录默认在 %USERPROFILE%\\AppData\\LocalLow\\foxxlight\\AzureArchive\\data，
但用户可以在设置里改到别处（比如挪到 D 盘）。改过之后：
  - 默认位置只剩一个 settings\\user_settings.json
  - 真正的 data 在 <workspacePath>\\data
所以探测顺序是：读默认位置的 user_settings.json 拿 workspacePath，没有再退回默认。

任何脚本都不要写死绝对路径 —— 换台电脑就废了。
"""
import json, os, sys, tempfile
from pathlib import Path
from typing import Sequence

from aa_install_discovery import discover_aa, normalize_aa_data_path
from runtime_paths import resolve_runtime_layout

APPDATA_LOW = os.path.join(os.path.expanduser("~"), "AppData", "LocalLow")
VENDOR = os.path.join(APPDATA_LOW, "foxxlight", "AzureArchive")
CONF_NAME = "aa_config.json"
RUNTIME_LAYOUT = resolve_runtime_layout(module_file=__file__, executable=sys.executable)
HERE = str(RUNTIME_LAYOUT.resource_root)


def _read_settings(data_dir):
    p = os.path.join(data_dir, "settings", "user_settings.json")
    if not os.path.exists(p):
        return {}
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return {}


def _resource_cache_for_data(data_dir, settings):
    """AA 在 cachePath 留空时会把资源缓存放在工作区的兄弟目录“资源文件”中。"""
    configured = (settings.get("cachePath") or "").strip()
    if configured:
        return os.path.abspath(configured)
    workspace = os.path.dirname(os.path.abspath(data_dir))
    sibling = os.path.join(os.path.dirname(workspace), "资源文件")
    return sibling if os.path.isdir(sibling) else None


def _path_string(value):
    return str(value) if value is not None else None


def detect(explicit=None, *, aa_install=None):
    """Return legacy string paths backed by structured discovery."""
    selection = normalize_aa_data_path(explicit) if explicit else aa_install
    selection = selection or explicit or aa_install
    result = discover_aa(
        selection,
        config_path=RUNTIME_LAYOUT.config_path,
        fallback_config_paths=(RUNTIME_LAYOUT.legacy_config_path,),
    )
    return {
        "data": _path_string(result.data),
        "projects": _path_string(result.projects),
        "saves": _path_string(result.saves),
        "overrides": _path_string(result.overrides),
        "settings": _path_string(result.settings),
        "cache": _path_string(result.resource_cache),
        "source": result.source,
        "tried": [str(candidate.path) for candidate in result.data_candidates],
        "executable": _path_string(result.executable),
        "install_root": _path_string(result.install_root),
        "catalog": _path_string(result.catalog),
        "recent_project_files": [
            str(path) for path in result.recent_project_files
        ],
        "requires_selection": result.requires_selection,
    }


def require(explicit=None, what="AA 存储目录"):
    p = detect(explicit)
    if not p["data"]:
        msg = [f"找不到 {what}。试过这些位置："]
        for t in p.get("tried", []):
            msg.append("  " + t)
        msg += [
            "",
            "解决办法（任选其一）：",
            f"  1. 在 {RUNTIME_LAYOUT.config_path.parent} 下建 {CONF_NAME}，内容：",
            '     { "aa_data": "你的路径\\\\data" }',
            "  2. 设环境变量 AA_DATA",
            "  3. 命令行加 --aa-data 你的路径",
            "",
            "路径长这样：…\\AzureArchive\\存储文件\\data（里面应该有 projects / saves / overrides）",
        ]
        sys.exit("\n".join(msg))
    return p


def save_config(
    data_dir=None,
    *,
    executable=None,
    cache_dir=None,
    spine_cli=None,
    config_path=None,
    fallback_config_paths: Sequence[str | os.PathLike] = (),
):
    conf = Path(config_path) if config_path is not None else RUNTIME_LAYOUT.config_path
    old = {}
    if conf.is_file():
        try:
            old = json.loads(conf.read_text(encoding="utf-8-sig"))
        except Exception:
            old = {}
    if not isinstance(old, dict):
        old = {}
    for fallback_path in fallback_config_paths:
        try:
            fallback = json.loads(Path(fallback_path).read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, ValueError, TypeError):
            continue
        if not isinstance(fallback, dict):
            continue
        for key, value in fallback.items():
            if key not in old:
                old[key] = value
    updates = {
        "aa_data": str(data_dir) if data_dir else None,
        "aa_executable": str(executable) if executable else None,
        "aa_cache": str(cache_dir) if cache_dir else None,
        "spine_cli": str(spine_cli) if spine_cli else None,
    }
    old.update({key: value for key, value in updates.items() if value})
    conf.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            delete=False,
            dir=conf.parent,
            prefix=f".{conf.name}.",
            suffix=".tmp",
        ) as fh:
            temporary_path = Path(fh.name)
            json.dump(old, fh, ensure_ascii=False, indent=1)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temporary_path, conf)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
    return str(conf)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    p = detect(sys.argv[1] if len(sys.argv) > 1 else None)
    if not p["data"]:
        print("没找到 AA 存储目录。试过：")
        for t in p.get("tried", []):
            print("  ", t, "  ✗")
        sys.exit(1)
    print(f"找到了（来源：{p['source']}）")
    for k in ("data", "projects", "saves", "overrides", "settings", "cache"):
        v = p[k]
        mark = "" if (v and os.path.isdir(v)) else "   ← 不存在"
        print(f"  {k:<10} {v}{mark}")
