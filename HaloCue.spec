# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

ROOT = Path(SPECPATH).resolve()

datas = [
    (str(ROOT / "ui.html"), "."),
    (str(ROOT / "js"), "js"),
    (str(ROOT / "css"), "css"),
    (str(ROOT / "branding"), "branding"),
    (str(ROOT / "data" / "halocue_labels.db"), "data"),
]

hiddenimports = [
    "desktop_app",
    "webview",
    "webview.platforms.edgechromium",
    "anthropic",
    "UnityPy",
]

excludes = [
    "archspec", "av", "bcrypt", "cryptography", "cv2", "hypothesis",
    "invoke", "matplotlib", "nacl", "numpy", "onnxruntime", "outcome",
    "pandas", "paramiko", "pkg_resources", "pluggy", "py", "pytest",
    "_pytest", "scipy", "setuptools", "sklearn", "sympy", "tkinter",
    "_tkinter", "torch", "torchvision", "transformers", "trio", "yt_dlp",
]

a = Analysis(
    [str(ROOT / "launcher.py")],
    pathex=[str(ROOT)],
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
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="HaloCue",
)
