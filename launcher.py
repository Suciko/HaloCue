# -*- coding: utf-8 -*-
"""AA 自动写剧本的 Windows 一键启动与环境体检入口。"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from aa_install_discovery import discover_aa, normalize_aa_data_path
from runtime_layout import LAYOUT, prepare_user_state


if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

if LAYOUT.frozen:
    prepare_user_state(LAYOUT)
PROGRAM_DIR = LAYOUT.resource_root
ENTRY_FILE = "启动AA自动写剧本.cmd"
ERROR_LOG = LAYOUT.user_data_root / "启动失败日志.txt"
MIN_PYTHON = (3, 9)
CORE_FILES = ("webui.py", "ui.html")


def write_package_self_test(output_path: str | os.PathLike) -> int:
    """Verify imports and immutable resources from inside the frozen EXE."""
    required_modules = (
        "PIL",
        "UnityPy",
        "anthropic",
        "webview",
        "webview.platforms.edgechromium",
        "fmod_toolkit",
        "archspec",
        "clr",
        "annotation_scene_planner",
        "annotation_agent",
        "annotation_protocol",
        "direction_quality",
        "face_selection",
        "portrait_layout",
        "scene_asset_labeler",
        "spine_face_web_renderer",
    )
    imported = {}
    failures = []
    for name in required_modules:
        try:
            importlib.import_module(name)
        except Exception as exc:
            failures.append(f"module:{name}:{type(exc).__name__}")
        else:
            imported[name] = True

    required_resources = (
        "ui.html",
        "portrait_layout_hints.json",
        "js/spine-webgl-3.8.95.js",
        "js/spine-webgl-4.2.119.min.js",
        "tools/spine_web_runtime/spine-webgl-4.2.119.min.js",
        "tools/spine_web_runtime/SPINE-RUNTIMES-LICENSE.txt",
        "webview/lib/Microsoft.Web.WebView2.Core.dll",
        "webview/lib/runtimes/win-x64/native/WebView2Loader.dll",
        "aa_assets.db",
        "aa_config.seed.json",
    )
    resources = {}
    for relative in required_resources:
        ready = (LAYOUT.resource_root / relative).is_file()
        resources[relative] = ready
        if not ready:
            failures.append(f"resource:{relative}:missing")

    database_paths = []
    try:
        import webui

        database_paths = webui.configured_asset_database_paths()
        if len(database_paths) < 2:
            failures.append("database:expected-primary-and-overlay")
    except Exception as exc:
        failures.append(f"database:{type(exc).__name__}")

    payload = {
        "ok": not failures,
        "version": "0.95",
        "frozen": bool(getattr(sys, "frozen", False)),
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "modules": imported,
        "resources": resources,
        "database_count": len(database_paths),
        "failures": failures,
    }
    Path(output_path).resolve().write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 0 if payload["ok"] else 1


def _discover_aa(
    explicit_aa_data: str | None,
    explicit_aa_install: str | None,
):
    selection = explicit_aa_data or explicit_aa_install
    return discover_aa(
        selection,
        config_path=(
            LAYOUT.config_path
            if LAYOUT.frozen
            else PROGRAM_DIR / "aa_config.json"
        ),
    )


def build_environment_report(
    program_dir: str | os.PathLike,
    explicit_aa_data: str | None = None,
    *,
    explicit_aa_install: str | None = None,
) -> dict:
    """Return a redacted, serializable startup-readiness report."""
    root = Path(program_dir).resolve()
    missing_files = []
    for name in CORE_FILES:
        if (root / name).is_file():
            continue
        if (
            LAYOUT.frozen
            and name.endswith(".py")
            and importlib.util.find_spec(name[:-3]) is not None
        ):
            continue
        missing_files.append(name)
    database_path = (
        LAYOUT.database_path
        if LAYOUT.frozen and root == PROGRAM_DIR
        else root / "aa_assets.db"
    )
    database_ready = database_path.is_file()
    pillow_ready = importlib.util.find_spec("PIL") is not None
    python_ready = sys.version_info >= MIN_PYTHON
    discovery = _discover_aa(explicit_aa_data, explicit_aa_install)
    aa_data = discovery.data
    issues: list[str] = []
    if not python_ready:
        issues.append(
            "Python 版本过低，需要 Python 3.9 或更高版本。"
        )
    for name in missing_files:
        issues.append(f"程序文件缺失：{name}")
    if not pillow_ready:
        issues.append(
            "缺少图片组件 Pillow。请运行：python -m pip install pillow"
        )
    if not database_ready:
        issues.append(
            "缺少素材数据库 aa_assets.db；请先完成素材库初始化或使用带数据库的发布包。"
        )
    if aa_data is None:
        issues.append(
            "尚未连接 AA；请在应用内选择 AzureArchive.exe。"
        )
    startup_ready = python_ready and not missing_files and pillow_ready and database_ready
    return {
        "ok": not issues,
        "startup_ready": startup_ready,
        "python": {
            "ready": python_ready,
            "version": (
                f"{sys.version_info.major}."
                f"{sys.version_info.minor}."
                f"{sys.version_info.micro}"
            ),
            "executable": sys.executable,
        },
        "program": {
            "ready": not missing_files,
            "path": str(root),
            "missing_files": missing_files,
        },
        "database": {
            "ready": database_ready,
            "path": str(database_path),
        },
        "pillow": {"ready": pillow_ready},
        "aa": {
            "connected": aa_data is not None,
            "path": str(aa_data) if aa_data else "",
            "executable": (
                str(discovery.executable)
                if discovery.executable else ""
            ),
            "install_root": (
                str(discovery.install_root)
                if discovery.install_root else ""
            ),
            "resource_status": (
                "installed"
                if discovery.resource_cache is not None
                else "not_installed"
            ),
            "resource_cache": (
                str(discovery.resource_cache)
                if discovery.resource_cache else ""
            ),
            "preview_status": "not_built",
            "projects": (
                str(discovery.projects)
                if discovery.projects else ""
            ),
            "saves": str(discovery.saves) if discovery.saves else "",
        },
        "entry_file": ENTRY_FILE,
        "blocking_issues": issues,
    }


def is_existing_server(url: str) -> bool:
    """Return true only for a current, model-workbench-capable server."""
    try:
        with urllib.request.urlopen(
            url.rstrip("/") + "/api/setup/status",
            timeout=0.8,
        ) as response:
            if response.status != 200:
                return False
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("entry_file") != ENTRY_FILE:
            return False
        with urllib.request.urlopen(
            url.rstrip("/") + "/api/llm/workbench",
            timeout=0.8,
        ) as response:
            if response.status != 200:
                return False
            workbench = json.loads(response.read().decode("utf-8"))
    except (
        OSError,
        ValueError,
        urllib.error.URLError,
    ):
        return False
    return workbench.get("schema_version") == 2


def _choose_aa_data() -> Path | None:
    """Ask a non-technical Windows user for the AA workspace folder."""
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox
    except Exception:
        return None
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        while True:
            selected = filedialog.askdirectory(
                title=(
                    "选择 AA 的 data 文件夹，"
                    "或“存储文件”工作区文件夹"
                )
            )
            if not selected:
                return None
            normalized = normalize_aa_data_path(selected)
            if normalized is not None:
                return normalized
            messagebox.showerror(
                "这里不是 AA 工作区",
                "请选择里面含有 projects 文件夹的 data 目录，"
                "也可以选择 data 的上一级“存储文件”目录。",
            )
    finally:
        root.destroy()


def _choose_aa_install() -> Path | None:
    """Ask for the AA executable before falling back to a workspace."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        return None
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        selected = filedialog.askopenfilename(
            filetypes=[
                ("AzureArchive", "AzureArchive.exe"),
                ("程序", "*.exe"),
            ],
        )
        return Path(selected).resolve() if selected else None
    finally:
        root.destroy()


def _save_aa_path(
    data_dir: Path,
    *,
    executable: Path | None = None,
    cache_dir: Path | None = None,
) -> None:
    sys.path.insert(0, str(PROGRAM_DIR))
    import aapaths

    aapaths.save_config(
        str(data_dir),
        executable=str(executable) if executable else None,
        cache_dir=str(cache_dir) if cache_dir else None,
    )


def _human_report(report: dict) -> str:
    lines = [
        "AA 自动写剧本 · 运行环境检查",
        "",
        f"Python：{'正常' if report['python']['ready'] else '异常'}"
        f"（{report['python']['version']}）",
        f"程序文件：{'正常' if report['program']['ready'] else '缺失'}",
        f"素材数据库：{'正常' if report['database']['ready'] else '缺失'}",
        f"图片组件：{'正常' if report['pillow']['ready'] else '缺失'}",
        f"AA 工作区：{'已连接' if report['aa']['connected'] else '未连接'}",
    ]
    if report["aa"]["path"]:
        lines.append(f"  {report['aa']['path']}")
    if report["blocking_issues"]:
        lines.extend(["", "需要处理："])
        lines.extend(
            f"{index}. {message}"
            for index, message in enumerate(
                report["blocking_issues"],
                1,
            )
        )
    else:
        lines.extend(["", "全部正常，可以启动。"])
    return "\n".join(lines)


def _write_failure_log(report: dict) -> None:
    ERROR_LOG.write_text(
        _human_report(report) + "\n",
        encoding="utf-8",
    )


def _show_error(message: str) -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            0,
            message,
            "AA 自动写剧本无法启动",
            0x10,
        )
    except Exception:
        pass


def _start_application(aa_data: Path | None) -> int:
    if getattr(sys, "frozen", False):
        try:
            from desktop_app import run_desktop

            return run_desktop(str(aa_data) if aa_data else None)
        except Exception as exc:
            message = f"HaloCue 桌面窗口启动失败：{exc}"
            try:
                ERROR_LOG.write_text(message + "\n", encoding="utf-8")
            except OSError:
                pass
            _show_error(message)
            return 1
    url = "http://127.0.0.1:8770"
    if is_existing_server(url):
        print("程序已经在运行，正在打开现有页面……")
        webbrowser.open(url)
        return 0
    command = [
        sys.executable,
        str(PROGRAM_DIR / "webui.py"),
        "--aa-data",
        str(aa_data or ""),
    ]
    print("环境检查通过，正在打开网页……")
    print("程序运行期间请保留这个窗口；关闭窗口即可停止程序。")
    try:
        return subprocess.call(command, cwd=PROGRAM_DIR)
    except KeyboardInterrupt:
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="AA 自动写剧本启动器"
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--aa-data")
    parser.add_argument("--aa-install")
    parser.add_argument("--package-self-test", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.package_self_test:
        return write_package_self_test(args.package_self_test)

    report = build_environment_report(
        PROGRAM_DIR,
        explicit_aa_data=args.aa_data,
        explicit_aa_install=args.aa_install,
    )
    if args.check:
        if args.json:
            print(json.dumps(report, ensure_ascii=False))
        else:
            print(_human_report(report))
        return 0 if report["ok"] else 1

    if not report.get("startup_ready", report["ok"]):
        _write_failure_log(report)
        message = (
            _human_report(report)
            + "\n\n详细结果已保存到：\n"
            + str(ERROR_LOG)
        )
        print(message)
        _show_error(message)
        return 1

    aa_path = str(report["aa"].get("path") or "").strip()
    return _start_application(Path(aa_path) if aa_path else None)


if __name__ == "__main__":
    raise SystemExit(main())
