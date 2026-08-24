import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from halocue_writing.workflow_pack import (  # noqa: E402
    MODE_SOURCES,
    WORKFLOW_RULE_SOURCES,
)


_SYNTHETIC_SKILL_DIR = tempfile.TemporaryDirectory(
    prefix="halocue-test-ba-writing-"
)
_SYNTHETIC_SKILL_ROOT = Path(_SYNTHETIC_SKILL_DIR.name)
_SYNTHETIC_SKILL_PATHS = [
    path
    for sources in WORKFLOW_RULE_SOURCES.values()
    for path in sources
]
_SYNTHETIC_SKILL_PATHS.extend(MODE_SOURCES.values())
_SYNTHETIC_SKILL_PATHS.append("knowledge/老师在场规则.md")

for logical_path in dict.fromkeys(_SYNTHETIC_SKILL_PATHS):
    target = _SYNTHETIC_SKILL_ROOT / logical_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        f"# Synthetic rule: {logical_path}\nOnly for deterministic contract tests.\n",
        encoding="utf-8",
    )

# The production runtime still requires an explicit external Skill. Tests use a
# complete synthetic pack so their result never depends on private local files.
os.environ["HALOCUE_BA_WRITING_SKILL_DIR"] = str(_SYNTHETIC_SKILL_ROOT)
