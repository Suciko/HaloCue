"""Each origin probe has its own interpreter; never evict host modules in tests."""

import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
PRELUDE = r"""
import importlib, json, os, sys
from pathlib import Path
from types import SimpleNamespace, ModuleType
from halocue_production.config import Settings
from halocue_production.errors import ProductionError
from halocue_production.legacy_adapter import Legacy093Adapter
base = Path(sys.argv[1])
os.environ['HALOCUE_USER_DATA_DIR'] = str(base / 'compat-data')
os.environ['HALOCUE_RESOURCE_INDEX'] = str(base / 'missing-index.json')
names = ('document', 'draft_store', 'build_bundle', 'install_manager', 'annotate',
         'assetdb', 'asset_catalog', 'portrait_layout', 'asset_import', 'aa_install_discovery')
def checkout(label, version='1.0.0'):
    root = base / label
    root.mkdir()
    (root / 'pyproject.toml').write_text('[project]\nversion = "' + version + '"\n')
    for name in names:
        text = 'ORIGIN = ' + repr(label) + '\n'
        if name == 'draft_store':
            text += 'class DraftStore:\n    def __init__(self, **kwargs): pass\n'
        if name == 'annotate':
            text += 'from types import SimpleNamespace\nPROMPT = SimpleNamespace()\n'
        (root / (name + '.py')).write_text(text)
    for name in ('llm', 'spine_face_analysis', 'teacher_presentation', 'helper'):
        (root / (name + '.py')).write_text('ORIGIN = ' + repr(label) + '\n')
    return root
def adapter(root, label):
    return Legacy093Adapter(Settings(project_root=base, data_dir=base/('data-'+label),
        legacy_root=root, resource_index=None, aa_data=None))
def rejected(call):
    try:
        call()
    except ProductionError as error:
        assert error.code in {'legacy_code_root_conflict', 'legacy_module_origin_mismatch', 'legacy_module_missing'}, error.code
        return error
    raise AssertionError('silently accepted a conflicting or incomplete code root')
"""


def probe(tmp_path, code):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join((str(ROOT / "services/halocue/production/src"), str(ROOT)))
    for key in ("HALOCUE_AA_DATA", "HALOCUE_LEGACY_ROOT", "SPINE_CLI", "HALOCUE_SPINE_CLI"):
        env.pop(key, None)
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", PRELUDE + code, str(tmp_path)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=40,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_second_checkout_is_rejected_without_mutating_first_adapter(tmp_path):
    probe(
        tmp_path,
        r"""
a = checkout('a'); b = checkout('b', '0.95')
first = adapter(a, 'first')
before = list(sys.path)
error = rejected(lambda: adapter(b, 'second'))
assert sys.path == before
assert first.document.ORIGIN == 'a'
assert sys.modules['document'] is first.document
assert first.legacy_version == '1.0.0'
assert 'b' in str(error.details)
""",
    )


def test_same_checkout_reuse_reports_actual_code_and_data_roots(tmp_path):
    probe(
        tmp_path,
        r"""
a = checkout('a')
first = adapter(a, 'first'); second = adapter(a, 'second')
assert first.document is second.document
info = second.capabilities()['legacy_adapter']
assert info['code_root'] == str(a)
assert info['data_root'] == str(a)
assert info['version'] == '1.0.0'
""",
    )


@pytest.mark.parametrize("polluted", ["document", "helper"])
def test_host_cached_foreign_module_is_rejected_before_importing_selected_code(tmp_path, polluted):
    probe(
        tmp_path,
        r"""
a = checkout('a'); b = checkout('b')
sys.path.insert(0, str(a))
importlib.import_module("""
        + repr(polluted)
        + r""")
sys.path.remove(str(a))
(b/'document.py').write_text('import helper\nfrom pathlib import Path\nPath(' + repr(str(base/'selected-executed')) + ').touch()\n')
before = list(sys.path)
rejected(lambda: adapter(b, 'second'))
assert sys.path == before
assert not (base/'selected-executed').exists()
""",
    )


def test_partial_checkout_cannot_fall_back_to_other_code(tmp_path):
    probe(
        tmp_path,
        r"""
a = checkout('a'); b = base/'partial'; b.mkdir()
(b/'document.py').write_text('ORIGIN = "partial"\n')
sys.path.insert(0, str(a))
rejected(lambda: adapter(b, 'partial'))
assert 'document' not in sys.modules
""",
    )


def test_cached_module_without_origin_fails_closed(tmp_path):
    probe(
        tmp_path,
        r"""
a = checkout('a')
sys.modules['document'] = ModuleType('document')
rejected(lambda: adapter(a, 'a'))
""",
    )


def test_data_only_root_uses_bundled_code_not_its_version_marker(tmp_path):
    probe(
        tmp_path,
        r"""
data = base/'data-only'; data.mkdir()
(data/'pyproject.toml').write_text('[project]\nversion = "9.9.9"\n')
instance = adapter(data, 'only')
info = instance.capabilities()['legacy_adapter']
actual = Path(instance.document.__file__).resolve().parent
assert info['code_root'] == str(actual)
assert info['data_root'] == str(data)
assert info['version'] == instance._detect_legacy_version(actual)
assert info['version'] != '9.9.9'
assert str(data) not in sys.path
""",
    )


def test_lazy_spine_import_cannot_select_another_checkout(tmp_path):
    probe(
        tmp_path,
        r"""
from halocue_production.spine_rendering import _legacy_module
a = checkout('a'); b = checkout('b')
first = _legacy_module('spine_face_analysis', a)
rejected(lambda: _legacy_module('spine_face_analysis', b))
assert first.ORIGIN == 'a'
""",
    )


def test_lazy_model_provider_cannot_select_another_checkout(tmp_path):
    probe(
        tmp_path,
        r"""
from halocue_production.direction_models import DirectionModelGateway
a = checkout('a'); b = checkout('b')
for root in (a, b):
    (root/'llm.py').write_text('def make_provider_from_settings(*args): return ' + repr(root.name) + '\n')
settings = SimpleNamespace(provider_settings=lambda: ('synthetic', {}))
assert DirectionModelGateway(settings, a).provider() == 'a'
rejected(lambda: DirectionModelGateway(settings, b).provider())
""",
    )


def test_missing_transitive_module_does_not_silently_import_bundled_alternative(tmp_path):
    probe(
        tmp_path,
        r"""
a = checkout('a')
(a/'document.py').write_text('import annotation_memory\nORIGIN = "a"\n')
rejected(lambda: adapter(a, 'a'))
""",
    )


def test_late_teacher_module_pollution_is_rejected(tmp_path):
    probe(
        tmp_path,
        r"""
a = checkout('a'); b = checkout('b')
first = adapter(a, 'a')
foreign = ModuleType('teacher_presentation')
foreign.__file__ = str(b/'teacher_presentation.py')
sys.modules['teacher_presentation'] = foreign
rejected(lambda: first._legacy_module('teacher_presentation'))
assert first.document.ORIGIN == 'a'
""",
    )


def test_frozen_bundle_uses_meipass_without_evaluating_source_tree_parents(tmp_path):
    probe(
        tmp_path,
        r"""
from halocue_production import legacy_modules
bundle = base/'bundle'; bundle.mkdir()
data = base/'data-only'; data.mkdir()
sys.frozen = True
sys._MEIPASS = str(bundle)
legacy_modules.__file__ = str(Path(base.anchor)/'app'/'halocue_production'/'legacy_modules.py')
module = ModuleType('document'); module.__file__ = str(bundle/'document.pyc')
sys.modules['document'] = module
root, loaded = legacy_modules.load_modules(data, ('document',))
assert root == bundle
assert loaded['document'] is module
""",
    )


def test_repeated_origin_checks_reuse_path_normalization_but_detect_changed_origin(tmp_path):
    probe(
        tmp_path,
        r"""
from halocue_production.legacy_modules import load_module
a = checkout('a'); b = checkout('b')
first = adapter(a, 'a')
load_module('document', a)
original = Path.resolve
calls = []
def resolve(path, *args, **kwargs):
    calls.append(str(path))
    return original(path, *args, **kwargs)
Path.resolve = resolve
load_module('document', a)
assert len(calls) < 20, len(calls)
first.document.__file__ = str(b/'document.py')
rejected(lambda: load_module('document', a))
""",
    )


def test_file_link_into_other_checkout_is_not_reported_as_selected_code(tmp_path):
    probe(
        tmp_path,
        r"""
from halocue_production.legacy_modules import load_module
a = checkout('a'); b = checkout('b')
module = ModuleType('document'); module.__file__ = str(b/'document.py')
sys.modules['document'] = module
# Simulate an individual linked source file without requiring Windows symlink privileges.
original = Path.resolve
def resolve(path, *args, **kwargs):
    if path == b/'document.py':
        return a/'document.py'
    return original(path, *args, **kwargs)
Path.resolve = resolve
rejected(lambda: load_module('document', b))
""",
    )


def test_missing_optional_spine_analysis_disables_preview_not_overall_capability(tmp_path):
    probe(
        tmp_path,
        r"""
from halocue_production.spine_rendering import capability
a = checkout('a')
(a/'spine_face_analysis.py').unlink()
first = adapter(a, 'a')
assert capability(legacy_root=a, data_dir=base/'settings')['state'] == 'not_configured'
assert first.capabilities()['legacy_adapter']['state'] == 'available'
""",
    )


def test_optional_spine_capability_does_not_hide_origin_conflicts(tmp_path):
    probe(
        tmp_path,
        r"""
from halocue_production.spine_rendering import capability
a = checkout('a'); b = checkout('b')
first = adapter(a, 'a')
foreign = ModuleType('spine_face_analysis'); foreign.__file__ = str(b/'spine_face_analysis.py')
sys.modules['spine_face_analysis'] = foreign
error = rejected(lambda: capability(legacy_root=a, data_dir=base/'settings'))
assert error.code == 'legacy_module_origin_mismatch'
""",
    )
