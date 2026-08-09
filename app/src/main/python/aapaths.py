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
import json, os, sys

from aa_install_discovery import discover_aa, normalize_aa_data_path

APPDATA_LOW = os.path.join(os.path.expanduser("~"), "AppData", "LocalLow")
VENDOR = os.path.join(APPDATA_LOW, "foxxlight", "AzureArchive")
CONF_NAME = "aa_config.json"
HERE = os.path.dirname(os.path.abspath(__file__))


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
        config_path=os.path.join(HERE, CONF_NAME),
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
            f"  1. 在 {HERE} 下建 {CONF_NAME}，内容：",
            '     { "aa_data": "你的路径\\\\data" }',
            "  2. 设环境变量 AA_DATA",
            "  3. 命令行加 --aa-data 你的路径",
            "",
            "路径长这样：…\\AzureArchive\\存储文件\\data（里面应该有 projects / saves / overrides）",
        ]
        sys.exit("\n".join(msg))
    return p


def save_config(data_dir=None, *, executable=None, cache_dir=None):
    conf = os.path.join(HERE, CONF_NAME)
    old = {}
    if os.path.exists(conf):
        try:
            old = json.load(open(conf, encoding="utf-8"))
        except Exception:
            old = {}
    if not isinstance(old, dict):
        old = {}
    updates = {
        "aa_data": str(data_dir) if data_dir else None,
        "aa_executable": str(executable) if executable else None,
        "aa_cache": str(cache_dir) if cache_dir else None,
    }
    old.update({key: value for key, value in updates.items() if value})
    with open(conf, "w", encoding="utf-8") as fh:
        json.dump(old, fh, ensure_ascii=False, indent=1)
    return conf


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
