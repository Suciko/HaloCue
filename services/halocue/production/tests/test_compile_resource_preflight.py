import json
from dataclasses import replace
from pathlib import Path

import pytest

from halocue_production.errors import ProductionError
from halocue_production.service import ProductionService


@pytest.fixture
def ready_compile(settings, tmp_path):
    aa = tmp_path / 'aa'
    for name in ('projects', 'saves', 'overrides', 'settings'):
        (aa / name).mkdir(parents=True)
    resources = {'bg': {}, 'sounds': [], 'characters': [],
                 'enums': {'emoticon': {}, 'action': {}}}
    index = tmp_path / 'aa_resources.json'
    index.write_text(json.dumps(resources), encoding='utf8')
    service = ProductionService(replace(settings, resource_index=index, aa_data=aa))
    try:
        created = service.create_run({'project': '资源前置检查', 'source': {'kind': 'inline', 'text': '旁白: 测试。\n'}})
        run_id = created['run']['run_id']
        mapped = service.update_cast(run_id, {'speaker': '旁白', 'mapping': {'kind': 'narrator'}, 'expected_draft_version': created['draft']['draft_version']})
        approved = service.approve_review(run_id, {'card_ids': None, 'expected_draft_version': mapped['draft']['draft_version']})
        path = service.adapter.store.get_draft_path(approved['run']['draft_token']) / 'resources.json'
        yield service, run_id, approved['draft']['draft_version'], path, resources
    finally:
        service.jobs.close()


@pytest.mark.parametrize('damage,missing', [
    ('file', None), ('json', None), ('root', None),
    ('enums', ['enums']), ('enums_type', ['enums']),
    ('emoticon', ['enums.emoticon']), ('action', ['enums.action']),
    ('action_type', ['enums.action']), ('characters_type', ['characters']),
])
def test_compile_rejects_invalid_frozen_index_before_creating_job(ready_compile, damage, missing):
    service, run_id, version, path, resources = ready_compile
    if damage == 'file':
        path.unlink()
    elif damage == 'json':
        path.write_text('{', encoding='utf8')
    elif damage == 'root':
        path.write_text('[]', encoding='utf8')
    else:
        if damage == 'enums': resources.pop('enums')
        elif damage == 'enums_type': resources['enums'] = []
        elif damage == 'characters_type': resources['characters'] = {}
        elif damage == 'action_type': resources['enums']['action'] = []
        else: resources['enums'].pop(damage)
        path.write_text(json.dumps(resources), encoding='utf8')
    before = service._run(run_id).to_dict()
    with pytest.raises(ProductionError) as caught:
        service.compile(run_id, {'expected_draft_version': version})
    assert caught.value.code == ('resource_index_not_configured' if damage == 'file' else 'resource_index_incomplete')
    assert caught.value.status == 409
    if missing is not None:
        assert caught.value.details['missing'] == missing
    assert service._run(run_id).to_dict() == before
    assert not service.jobs.list()
    assert not list((path.parent / 'builds').rglob('input'))


def test_minimal_explicit_index_builds_from_frozen_snapshot(ready_compile):
    service, run_id, version, path, resources = ready_compile
    original = path.read_bytes()
    token = service._run(run_id).draft_token
    build_id = service.adapter.create_compile_snapshot(token, version)
    built = service.adapter.execute_compile(token, build_id)
    bundle = Path(built['bundle_dir'])
    assert bundle.is_relative_to(path.parent)
    assert (bundle / 'bundle.complete').is_file()
    assert list(bundle.glob('*.aap'))
    assert path.read_bytes() == original


def test_compile_gate_reports_incomplete_frozen_index(ready_compile):
    service, run_id, _, path, resources = ready_compile
    resources.pop('enums')
    path.write_text(json.dumps(resources), encoding='utf8')
    gate = service.run_detail(run_id)['gates']['compile']
    assert gate['passed'] is False
    assert 'resource_index_incomplete' in gate['blockers']

def test_restored_draft_preview_survives_missing_global_resource_index(ready_compile):
    service, run_id, version, path, resources = ready_compile
    restored = ProductionService(replace(service.settings, resource_index=None, aa_data=None))
    try:
        before = restored._run(run_id).to_dict()
        preview = restored.performance_preview(run_id)
        assert preview['frames']
        assert any(frame['text'] == '测试。' for frame in preview['frames'])
        assert all(frame['background_preview_available'] is False for frame in preview['frames'])
        assert restored._run(run_id).to_dict() == before
    finally:
        restored.jobs.close()
