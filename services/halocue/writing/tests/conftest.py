import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from services.halocue._test_support import (  # noqa: E402, F401
    isolated_ba_writing_skill,
    isolated_bundled_metadata,
    small_ba_writing_skill,
    small_bundled_metadata,
)
