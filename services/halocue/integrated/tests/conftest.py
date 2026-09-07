"""Load isolated data defaults even when integrated pyproject is the pytest root."""

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from services.halocue._test_support import (  # noqa: E402,F401
    isolated_legacy_root,
    isolated_production_defaults,
)
