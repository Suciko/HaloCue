import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "tools" / "verify_clean_source.py"


def _track(source, *relative_paths):
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    subprocess.run(
        ["git", "-C", str(source), "add", "--", *relative_paths],
        check=True,
    )


def _run_verifier(source, cwd):
    return subprocess.run(
        [sys.executable, str(VERIFIER), "--source", str(source)],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONUTF8": "1"},
    )


def test_verifier_rejects_private_test_dependency_without_reading_config(tmp_path):
    source = tmp_path / "source"
    tests = source / "tests"
    private_name = "llm.json"
    private_marker = "private-marker"
    tests.mkdir(parents=True)
    (source / private_name).write_text(
        '{"api_key": "private-marker"}', encoding="utf-8"
    )
    (tests / "test_private_config.py").write_text(
        "from pathlib import Path\n"
        f"CONFIG = Path(__file__).resolve().parents[1] / {private_name!r}\n"
        "def test_config_exists():\n"
        "    assert CONFIG.read_text(encoding='utf-8')\n",
        encoding="utf-8",
    )

    _track(source, "tests/test_private_config.py")
    result = _run_verifier(source, tmp_path)
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert "private dependency: tests/test_private_config.py -> llm.json" in output
    assert private_marker not in output


def test_verifier_excludes_ignored_candidate_fixture_and_reports_collection_failure(
    tmp_path,
):
    source = tmp_path / "source"
    fixtures = source / "tests" / "fixtures"
    fixtures.mkdir(parents=True)
    private_marker = "ignored-private-marker"
    (source / ".gitignore").write_text(
        "tests/fixtures/aa_config.json\n", encoding="utf-8"
    )
    (fixtures / "aa_config.json").write_text(private_marker, encoding="utf-8")
    (source / "tests" / "test_missing_fixture.py").write_text(
        "from pathlib import Path\n"
        "CONFIG = (Path(__file__).parent / 'fixtures' / 'aa_config.json').read_text()\n"
        "def test_config_loaded():\n"
        "    assert CONFIG\n",
        encoding="utf-8",
    )
    _track(source, ".gitignore", "tests/test_missing_fixture.py")

    result = _run_verifier(source, tmp_path)
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert "pytest collection failed" in output
    assert "aa_config.json" in output
    assert private_marker not in output


def test_verifier_rejects_private_source_paths_at_any_depth(tmp_path):
    source = tmp_path / "source"
    private_paths = (
        "nested/llm.json",
        "nested/aa_resources.json",
        "nested/aa_assets.db",
        "nested/aa_config.json",
        "nested/llm_profiles.json",
        "nested/cast.json",
        "nested/.thumbs/portrait.png",
        "nested/out/private.txt",
        "nested/output/private.txt",
        "nested/release/private.txt",
        "nested/release-staging/private.txt",
        "nested/staging/private.txt",
        "nested/scripts/private.txt",
        "nested/chapters/private.txt",
        "nested/cast-personal.json",
    )
    smoke = source / "tests" / "test_smoke.py"
    smoke.parent.mkdir(parents=True)
    smoke.write_text("def test_smoke():\n    assert True\n", encoding="utf-8")
    for relative in private_paths:
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("private", encoding="utf-8")
    _track(source, "tests/test_smoke.py", *private_paths)

    result = _run_verifier(source, tmp_path)
    output = result.stdout + result.stderr

    assert result.returncode != 0
    for relative in private_paths:
        assert f"private source path: {relative}" in output


def test_verifier_detects_path_cwd_private_dependency_without_running_test(tmp_path):
    source = tmp_path / "source"
    tests = source / "tests"
    tests.mkdir(parents=True)
    (tests / "test_cwd_config.py").write_text(
        "from pathlib import Path\n"
        "CONFIG = Path.cwd() / 'nested' / 'llm.json'\n"
        "def test_config_exists():\n"
        "    assert CONFIG.read_text(encoding='utf-8')\n",
        encoding="utf-8",
    )
    _track(source, "tests/test_cwd_config.py")

    result = _run_verifier(source, tmp_path)
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert "private dependency: tests/test_cwd_config.py -> llm.json" in output


def test_verifier_resolves_module_string_constant_in_private_dependency(tmp_path):
    source = tmp_path / "source"
    tests = source / "tests"
    tests.mkdir(parents=True)
    (tests / "test_constant_config.py").write_text(
        "from pathlib import Path\n"
        "ROOT = Path(__file__).resolve().parents[1]\n"
        "PRIVATE_NAME = 'llm.json'\n"
        "CONFIG = ROOT / PRIVATE_NAME\n"
        "def test_config_exists():\n"
        "    assert CONFIG.read_text(encoding='utf-8')\n",
        encoding="utf-8",
    )
    _track(source, "tests/test_constant_config.py")

    result = _run_verifier(source, tmp_path)
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert "private dependency: tests/test_constant_config.py -> llm.json" in output


def test_verifier_resolves_module_string_tuple_in_private_dependency(tmp_path):
    source = tmp_path / "source"
    tests = source / "tests"
    tests.mkdir(parents=True)
    (tests / "test_tuple_config.py").write_text(
        "from pathlib import Path\n"
        "ROOT = Path(__file__).resolve().parents[1]\n"
        "PRIVATE_PARTS = ('nested', 'llm.json')\n"
        "CONFIG = ROOT.joinpath(*PRIVATE_PARTS)\n"
        "def test_config_exists():\n"
        "    assert CONFIG.read_text(encoding='utf-8')\n",
        encoding="utf-8",
    )
    _track(source, "tests/test_tuple_config.py")

    result = _run_verifier(source, tmp_path)
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert "private dependency: tests/test_tuple_config.py -> llm.json" in output


def test_verifier_accepts_only_tracked_sanitized_release_database(tmp_path):
    source = tmp_path / "source"
    smoke = source / "tests" / "test_smoke.py"
    database = source / "data" / "halocue_labels.db"
    smoke.parent.mkdir(parents=True)
    database.parent.mkdir(parents=True)
    smoke.write_text("def test_smoke():\n    assert True\n", encoding="utf-8")
    database.write_bytes(b"sanitized labels")
    _track(source, "tests/test_smoke.py", "data/halocue_labels.db")

    result = _run_verifier(source, tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr


def test_verifier_rejects_every_other_tracked_database_path(tmp_path):
    source = tmp_path / "source"
    forbidden_paths = (
        "aa_assets.db",
        "nested/aa_assets.db",
        "data/renamed/aa_assets.db",
        "nested/halocue_labels.db",
        "data/halocue_labels-copy.db",
        "data/raw.db",
    )
    smoke = source / "tests" / "test_smoke.py"
    smoke.parent.mkdir(parents=True)
    smoke.write_text("def test_smoke():\n    assert True\n", encoding="utf-8")
    for relative in forbidden_paths:
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"private database")
    _track(source, "tests/test_smoke.py", *forbidden_paths)

    result = _run_verifier(source, tmp_path)
    output = result.stdout + result.stderr

    assert result.returncode != 0
    for relative in forbidden_paths:
        assert f"private source path: {relative}" in output


def test_data_asset_database_remains_ignored_until_explicitly_force_added():
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", "--no-index", "data/aa_assets.db"],
        cwd=ROOT,
    )

    assert result.returncode == 0
