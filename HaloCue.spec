# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import os
from PyInstaller.utils.hooks import collect_submodules, copy_metadata

ROOT = Path(SPECPATH).resolve()

datas = [
    (str(ROOT / "ui.html"), "."),
    (str(ROOT / "js"), "js"),
    (str(ROOT / "css"), "css"),
    (str(ROOT / "branding"), "branding"),
    (str(ROOT / "data" / "halocue_labels.db"), "data"),
    (str(ROOT / "data" / "reference-pack"), "data/reference-pack"),
    (str(ROOT / "model_capabilities.py"), "."),
    (str(ROOT / "pyproject.toml"), "."),
    (str(ROOT / "services" / "halocue" / "writing" / "skill" / "ba-writing"),
     "services/halocue/writing/skill/ba-writing"),
]
for service, folder in (("writing", "web"), ("production", "ui"), ("integrated", "static")):
    datas.append((str(ROOT / "services" / "halocue" / service / folder),
                  f"services/halocue/{service}/{folder}"))

hiddenimports = [
    "desktop_app",
    "webview",
    "webview.platforms.edgechromium",
    "anthropic",
    "UnityPy",
    "services.halocue.codex_agent",
]
import sys
for service in ("writing", "production", "integrated"):
    sys.path.insert(0, str(ROOT / "services" / "halocue" / service / "src"))
    hiddenimports.extend(collect_submodules(f"halocue_{service}"))
# The production adapter imports the compatibility family dynamically.
hiddenimports.extend(path.stem for path in ROOT.glob("*.py") if path.stem not in {"setup", "mcp_launcher"})

excludes = [
    "archspec", "av", "bcrypt", "cv2", "hypothesis",
    "invoke", "matplotlib", "nacl", "numpy", "onnxruntime", "outcome",
    "pandas", "paramiko", "pkg_resources", "pluggy", "py", "pytest",
    "_pytest", "scipy", "setuptools", "sklearn", "sympy", "tkinter",
    "_tkinter", "torch", "torchvision", "transformers", "trio", "yt_dlp",
]

a = Analysis(
    [str(ROOT / "launcher.py")],
    pathex=[str(ROOT), *(str(ROOT / "services" / "halocue" / name / "src")
                         for name in ("writing", "production", "integrated"))],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HaloCue",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "branding" / "halocue.ico"),
    version=os.environ.get("HALOCUE_VERSION_FILE"),
)

# A separate console entry retains stdio pipes. The windowed app cannot serve
# MCP on Windows; both executables share the collected runtime libraries.
mcp_analysis = Analysis(
    [str(ROOT / "mcp_launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=copy_metadata("mcp"),
    hiddenimports=["mcp.server.fastmcp"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
mcp_pyz = PYZ(mcp_analysis.pure)
mcp_exe = EXE(
    mcp_pyz,
    mcp_analysis.scripts,
    [],
    exclude_binaries=True,
    name="HaloCueMCP",
    console=True,
    icon=str(ROOT / "branding" / "halocue.ico"),
    version=os.environ.get("HALOCUE_VERSION_FILE"),
)

coll = COLLECT(
    exe,
    mcp_exe,
    a.binaries,
    a.datas,
    mcp_analysis.binaries,
    mcp_analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="HaloCue",
)
