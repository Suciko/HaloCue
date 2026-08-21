# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).resolve()
SEED = Path(os.environ["HALOCUE_BUILD_SEED_DIR"]).resolve()

datas = [
    (str(ROOT / "ui.html"), "."),
    (str(ROOT / "js"), "js"),
    (str(ROOT / "css"), "css"),
    (str(ROOT / "branding"), "branding"),
    (str(ROOT / "tools" / "spine_web_runtime"), "tools/spine_web_runtime"),
    (str(ROOT / "portrait_layout_hints.json"), "."),
    (str(SEED / "aa_assets.db"), "."),
    (str(SEED / "aa_resources.json"), "."),
    (str(SEED / "aa_config.seed.json"), "."),
] + collect_data_files("UnityPy", includes=["resources/*.tpk"])

if (SEED / "databases").is_dir():
    datas.append((str(SEED / "databases"), "databases"))

# UnityPy imports fmod_toolkit while opening UnityFS bundles.  Its native FMOD
# library is loaded through ctypes, so PyInstaller cannot discover it from
# Python imports and must receive the file explicitly.
datas += collect_data_files(
    "fmod_toolkit",
    includes=["libfmod/Windows/x64/fmod.dll"],
)
# pyfmodex detects the local CPU through archspec.  Those JSON tables are
# opened by relative filesystem paths at runtime rather than imported.
datas += collect_data_files("archspec", includes=["json/**/*.json"])

hiddenimports = [
    "desktop_app",
    "webview",
    "webview.platforms.edgechromium",
    "annotation_scene_planner",
    "annotation_agent",
    "annotation_protocol",
    "direction_quality",
    "face_selection",
    "portrait_layout",
    "scene_asset_labeler",
    "spine_face_web_renderer",
    # UnityPy imports this package dynamically when opening UnityFS bundles.
    # It is not discovered from the top-level ``import UnityPy`` alone.
    "UnityPy.resources",
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
    # The app is a local http.server + pywebview application.  These packages
    # are optional tools or residue from a developer's Python environment and
    # must not silently turn a portable release into a local inference/ASGI
    # bundle.
    excludes=[
        "pytest", "playwright",
        "torch", "torchvision", "torchaudio",
        "transformers", "tokenizers", "safetensors", "huggingface_hub",
        "fastapi", "starlette", "uvicorn", "websockets",
        # The release reads Unity bundles and images, but it does not offer
        # scientific computing, plotting, dataframe, or XML workflows.
        "scipy", "pandas", "matplotlib", "lxml",
    ],
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
