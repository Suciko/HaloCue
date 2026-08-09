# -*- coding: utf-8 -*-
"""HaloCue 的 Windows 一键启动与环境体检入口。"""

from __future__ import annotations

import argparse
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
from halocue_meta import APP_ID, DISPLAY_NAME, MIN_PYTHON
from runtime_paths import ensure_user_database, resolve_runtime_layout


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

RUNTIME_LAYOUT = resolve_runtime_layout(module_file=__file__, executable=sys.executable)
PROGRAM_DIR = RUNTIME_LAYOUT.resource_root
ENTRY_FILE = "启动AA自动写剧本.cmd"
ERROR_LOG = RUNTIME_LAYOUT.user_data_root / "启动失败日志.txt"
CORE_FILES = (
    ("ui.html",)
    if getattr(sys, "frozen", False)
    else ("webui.py", "ui.html")
)


def _discover_aa(
    explicit_aa_data: str | None,
    explicit_aa_install: str | None,
):
    selection = explicit_aa_data or explicit_aa_install
    return discover_aa(
        selection,
        config_path=RUNTIME_LAYOUT.config_path,
        fallback_config_paths=(RUNTIME_LAYOUT.legacy_config_path,),
    )


def build_environment_report(
    program_dir: str | os.PathLike,
    explicit_aa_data: str | None = None,
    *,
    explicit_aa_install: str | None = None,
) -> dict:
    """Return a redacted, serializable startup-readiness report."""
    root = Path(program_dir).resolve()
    missing_files = [
        name for name in CORE_FILES if not (root / name).is_file()
    ]
    database_path = RUNTIME_LAYOUT.database_path
    if root == RUNTIME_LAYOUT.resource_root and RUNTIME_LAYOUT.database_seed_path.is_file():
        try:
            ensure_user_database(RUNTIME_LAYOUT)
        except OSError:
            pass
    database_ready = database_path.is_file()
    pillow_ready = importlib.util.find_spec("PIL") is not None
    python_ready = sys.version_info >= MIN_PYTHON
    discovery = _discover_aa(explicit_aa_data, explicit_aa_install)
    aa_data = discovery.data
    issues: list[str] = []
    if not python_ready:
        issues.append(
            "Python 版本过低，需要 Python "
            f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]} 或更高版本。"
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
            "没有找到 AA 工作区；请选择包含 projects 文件夹的 data 目录。"
        )
    return {
        "ok": not issues,
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
        if payload.get("app_id") != APP_ID:
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
        config_path=RUNTIME_LAYOUT.config_path,
        fallback_config_paths=(RUNTIME_LAYOUT.legacy_config_path,),
    )


def _human_report(report: dict) -> str:
    lines = [
        f"{DISPLAY_NAME} · 运行环境检查",
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
    ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
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
            f"{DISPLAY_NAME} 无法启动",
            0x10,
        )
    except Exception:
        pass


def _start_application(
    aa_data: Path,
    *,
    port: int = 8770,
    no_browser: bool = False,
    ready_file: Path | None = None,
) -> int:
    url = f"http://127.0.0.1:{port}"
    if is_existing_server(url):
        print("程序已经在运行，正在打开现有页面……")
        webbrowser.open(url)
        return 0
    application_args = [
        "--aa-data",
        str(aa_data),
        "--port",
        str(port),
    ]
    if no_browser:
        application_args.append("--no-browser")
    if ready_file is not None:
        application_args.extend(("--ready-file", str(ready_file)))
    print("环境检查通过，正在打开网页……")
    print("程序运行期间请保留这个窗口；关闭窗口即可停止程序。")
    try:
        if getattr(sys, "frozen", False):
            import webui

            return webui.main(application_args)
        command = [
            sys.executable,
            str(PROGRAM_DIR / "webui.py"),
            *application_args,
        ]
        return subprocess.call(command, cwd=PROGRAM_DIR)
    except KeyboardInterrupt:
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=f"{DISPLAY_NAME} 启动器"
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--aa-data")
    parser.add_argument("--aa-install")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--ready-file", type=Path)
    args = parser.parse_args(argv)

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

    if (args.aa_data or args.aa_install) and report["aa"]["connected"]:
        _save_aa_path(
            Path(report["aa"]["path"]),
            executable=(
                Path(report["aa"]["executable"])
                if report["aa"].get("executable") else None
            ),
            cache_dir=(
                Path(report["aa"]["resource_cache"])
                if report["aa"].get("resource_cache") else None
            ),
        )

    if not report["aa"]["connected"]:
        chosen_install = (
            _choose_aa_install() if os.name == "nt" else None
        )
        if chosen_install is not None:
            report = build_environment_report(
                PROGRAM_DIR,
                explicit_aa_install=str(chosen_install),
            )
            if report["aa"]["connected"]:
                _save_aa_path(
                    Path(report["aa"]["path"]),
                    executable=(
                        Path(report["aa"]["executable"])
                        if report["aa"]["executable"] else None
                    ),
                    cache_dir=(
                        Path(report["aa"]["resource_cache"])
                        if report["aa"]["resource_cache"] else None
                    ),
                )
        if not report["aa"]["connected"]:
            chosen_data = _choose_aa_data()
            if chosen_data is not None:
                _save_aa_path(chosen_data)
                report = build_environment_report(
                    PROGRAM_DIR,
                    explicit_aa_data=str(chosen_data),
                )

    if not report["ok"]:
        _write_failure_log(report)
        message = (
            _human_report(report)
            + "\n\n详细结果已保存到：\n"
            + str(ERROR_LOG)
        )
        print(message)
        _show_error(message)
        return 1

    aa_data = Path(report["aa"]["path"])
    if args.port == 8770 and not args.no_browser and args.ready_file is None:
        return _start_application(aa_data)
    return _start_application(
        aa_data,
        port=args.port,
        no_browser=args.no_browser,
        ready_file=args.ready_file,
    )


if __name__ == "__main__":
    raise SystemExit(main())
