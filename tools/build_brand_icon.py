"""Render the editable HaloCue mark to the app and browser icon formats."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from shutil import copyfile

import cairosvg
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
BRANDING = ROOT / "branding"
MASTER = BRANDING / "halocue-icon.svg"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def main() -> None:
    rendered = cairosvg.svg2png(url=str(MASTER), output_width=1024, output_height=1024)
    with Image.open(BytesIO(rendered)) as source:
        icon = source.convert("RGBA")
    icon.save(BRANDING / "halocue-icon.png", format="PNG", optimize=True)
    icon.resize((64, 64), Image.Resampling.LANCZOS).save(
        BRANDING / "halocue-favicon.png", format="PNG", optimize=True
    )
    icon.save(BRANDING / "halocue.ico", format="ICO", sizes=[(size, size) for size in SIZES])
    copyfile(BRANDING / "halocue-favicon.png", ROOT / "services/halocue/writing/web/halocue-favicon.png")


if __name__ == "__main__":
    main()
