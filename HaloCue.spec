import os
from pathlib import Path
import sys

from PyInstaller.utils.hooks import copy_metadata

ROOT = Path(SPECPATH)
sys.path.insert(0, str(ROOT))
from release_tools.build_public import pyinstaller_policy


policy = pyinstaller_policy()
hiddenimports = list(policy["hidden_imports"])
datas = [
    (str(ROOT / "ui.html"), "."),
    (str(ROOT / "js"), "js"),
    (str(ROOT / "css"), "css"),
    (str(ROOT / "branding" / "halocue-icon.png"), "branding"),
    (str(ROOT / "branding" / "halocue-favicon.png"), "branding"),
    (str(ROOT / "data" / "halocue_labels.db"), "data"),
    (str(ROOT / "README.md"), "."),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "THIRD_PARTY_NOTICES.md"), "."),
]
for distribution in policy["metadata_distributions"]:
    try:
        datas += copy_metadata(distribution, recursive=policy["metadata_recursive"])
    except Exception:
        pass

a = Analysis(
    [str(ROOT / "halocue_app.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=list(policy["excludes"]),
    noarchive=False,
    optimize=0,
)
a.datas = [
    entry
    for entry in a.datas
    if not entry[0].casefold().endswith(".gif")
    and not entry[0].casefold().endswith("direct_url.json")
]
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
    console=True,
    icon=str(ROOT / "branding" / "halocue.ico"),
    version=os.environ[policy["version_file_environment"]],
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
