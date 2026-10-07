"""Service test defaults must never discover a maintainer's AA/catalog data."""

import json
import re
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest


def browser_failure_diagnostics(page):
    """Bounded transport evidence, without headers, query strings or payloads."""
    records = []

    def record(request, **details):
        if len(records) < 100:
            records.append(
                {"method": request.method, "path": urlsplit(request.url).path, **details}
            )

    def failed(request):
        codes = re.findall(r"net::ERR_[A-Z_]+", request.failure or "")
        record(request, failure=codes[0] if codes else "transport_failure")

    page.on("requestfailed", failed)
    page.on(
        "response",
        lambda response: (
            record(response.request, status=response.status) if response.status >= 400 else None
        ),
    )
    return records


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CHROMIUM_UNSAFE_PORTS = {
    1,
    7,
    9,
    11,
    13,
    15,
    17,
    19,
    20,
    21,
    22,
    23,
    25,
    37,
    42,
    43,
    53,
    69,
    77,
    79,
    87,
    95,
    101,
    102,
    103,
    104,
    109,
    110,
    111,
    113,
    115,
    117,
    119,
    123,
    135,
    137,
    139,
    143,
    161,
    179,
    389,
    427,
    465,
    512,
    513,
    514,
    515,
    526,
    530,
    531,
    532,
    540,
    548,
    554,
    556,
    563,
    587,
    601,
    636,
    989,
    990,
    993,
    995,
    1719,
    1720,
    1723,
    2049,
    3659,
    4045,
    5060,
    5061,
    6000,
    6566,
    6665,
    6666,
    6667,
    6668,
    6669,
    6697,
    10080,
}
# Compatibility modules remain shared code; data lookup uses a different root.
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


@pytest.fixture(scope="session")
def small_ba_writing_skill(tmp_path_factory):
    """Complete synthetic rules, independent of inherited maintainer settings."""
    from halocue_writing.workflow_pack import (
        ENGINE_RULE_SOURCE,
        MODE_SOURCES,
        WORKFLOW_RULE_SOURCES,
    )

    root = tmp_path_factory.mktemp("synthetic-writing-skill")
    paths = [path for group in WORKFLOW_RULE_SOURCES.values() for path in group]
    paths.extend([*MODE_SOURCES.values(), ENGINE_RULE_SOURCE, "knowledge/老师在场规则.md"])
    for logical_path in dict.fromkeys(paths):
        target = root / logical_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            f"# Synthetic rule: {logical_path}\nOnly for deterministic contract tests.\n",
            encoding="utf-8",
        )
    return root


@pytest.fixture(autouse=True)
def isolated_ba_writing_skill(monkeypatch, small_ba_writing_skill):
    monkeypatch.setenv("HALOCUE_BA_WRITING_SKILL_DIR", str(small_ba_writing_skill))


@pytest.fixture(scope="session")
def small_bundled_metadata(tmp_path_factory):
    """Bound ordinary workspaces; full research has separate opt-in acceptance."""
    path = tmp_path_factory.mktemp("synthetic-research") / "metadata.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE bg (name TEXT PRIMARY KEY, label TEXT, place TEXT, time TEXT, mood TEXT, tags TEXT);
            CREATE TABLE character (ident TEXT PRIMARY KEY, name TEXT, club TEXT, spine TEXT, avatar TEXT, source TEXT);
            CREATE TABLE character_variant (ident TEXT, spine_signature TEXT, outfit_key TEXT, spine TEXT);
            CREATE TABLE face (ident TEXT, face_id TEXT, raw TEXT, label TEXT, label_cn TEXT, PRIMARY KEY (ident, face_id));
            CREATE TABLE expression_part (ident TEXT, spine_signature TEXT, outfit_key TEXT, kind TEXT, raw_name TEXT, source TEXT);
            INSERT INTO bg VALUES ('BG_TestRoom', '测试教室', '测试校舍', 'day', '日常', '室内');
            INSERT INTO character VALUES ('test-character', '测试人物', '测试社团', 'synthetic-spine', '', 'synthetic');
            INSERT INTO character_variant VALUES ('test-character', 'synthetic', 'uniform', 'synthetic-spine');
            INSERT INTO face VALUES ('test-character', '01', '01_smile', 'smile', '微笑');
            INSERT INTO expression_part VALUES ('test-character', 'synthetic', 'uniform', 'eyes', 'eyes_smile', 'synthetic');
            """
        )
    return path


@pytest.fixture(autouse=True)
def isolated_bundled_metadata(request, monkeypatch, small_bundled_metadata):
    if request.node.get_closest_marker("bundled_research"):
        return
    source = REPOSITORY_ROOT / "services/halocue/writing/src"
    monkeypatch.syspath_prepend(str(source))
    from halocue_writing import resource_catalog

    monkeypatch.setattr(
        resource_catalog, "_bundled_metadata_database", lambda: small_bundled_metadata
    )


@pytest.fixture
def isolated_legacy_root(tmp_path):
    root = tmp_path / "isolated-legacy"
    root.mkdir(exist_ok=True)
    (root / "VERSION").write_text("1.0.0 synthetic fixture\n", encoding="utf-8")
    (root / "aa_resources.json").write_text(
        json.dumps({"bg": {}, "sounds": [], "characters": []}), encoding="utf-8"
    )
    return root


@pytest.fixture(autouse=True)
def isolated_production_defaults(request, monkeypatch, tmp_path):
    relative = Path(str(request.node.path)).relative_to(Path(__file__).parent)
    if relative.parts[0] not in {"production", "integrated"}:
        return
    isolated_legacy_root = request.getfixturevalue("isolated_legacy_root")
    monkeypatch.setenv("HALOCUE_LEGACY_ROOT", str(isolated_legacy_root))
    monkeypatch.setenv("HALOCUE_RESOURCE_INDEX", str(isolated_legacy_root / "aa_resources.json"))
    monkeypatch.setenv("HALOCUE_NAME_BASELINE", str(tmp_path / "absent-baseline.json"))
    monkeypatch.setenv("HALOCUE_USER_DATA_DIR", str(tmp_path / "compat-user-data"))
    monkeypatch.delenv("HALOCUE_AA_DATA", raising=False)
