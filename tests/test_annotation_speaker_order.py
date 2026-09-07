"""Full annotation input assembly across hash seeds, synthetic files only."""

import json
import os
import subprocess
import sys

import pytest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROGRAM = r"""
import hashlib,json,sys
from pathlib import Path
import annotate
root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=True)
names=json.loads(sys.argv[2]); cast=json.loads(sys.argv[3])
if int(sys.argv[4])%2: cast=dict(reversed(list(cast.items())))
used=[];original_build=annotate.build_static
def capture(idx,cast,names,**kwargs):
 used.append(list(names));return original_build(idx,cast,names,**kwargs)
annotate.build_static=capture
(root/'source.txt').write_text('\n'.join(name+': Synthetic line.' for name in names)+'\n',encoding='utf-8')
(root/'cast.json').write_text(json.dumps({'cast':cast}),encoding='utf-8')
(root/'index.json').write_text(json.dumps({'bg':{},'sounds':[],'characters':[],'enums':{'emoticon':{},'action':{}}}),encoding='utf-8')
(root/'llm.json').write_text('{}',encoding='utf-8')
class P:
 name='fake';model='fake';cfg={};stats={}
 def report(self):return 'fake'
def agent(items,**kwargs):
 value={'static':hashlib.sha256(kwargs['static_system'].encode()).hexdigest(),'fingerprint':kwargs['run_fingerprint'],'used':used}
 (root/'captured.json').write_text(json.dumps(value,sort_keys=True),encoding='utf-8')
 return {'rows_by_id':{},'beats':[]}
annotate.run_annotation_agent=agent
annotate.annotate_script({'script':str(root/'source.txt'),'out':str(root/'out.txt'),'cast':str(root/'cast.json'),'index':str(root/'index.json'),'llm':str(root/'llm.json'),'agent_enabled':True,'checkpoint_dir':str(root/'checkpoints')},provider_instance=P())
"""


@pytest.mark.parametrize(
    "names,expected",
    [
        (
            ["Yuzu", "Alice", "Momoi", "Midori", "Kei", "Rin"],
            ["Yuzu", "Alice", "Momoi", "Midori", "Kei", "Rin"],
        ),
        (["别名乙", "Z", "别名甲", "A", "Z", "A"], ["Z", "A", "别名乙"]),
        (["甲", "é", "Ａ", "乙", "甲"], ["甲", "é", "Ａ", "乙"]),
    ],
)
def test_full_static_identity_is_stable_across_hash_seeds(tmp_path, names, expected):
    cast = {
        name: {"id": "shared" if name.startswith("别名") else name.lower(), "portrait": True}
        for name in names
    }
    results = []
    for seed in range(1, 5):
        env = {
            **os.environ,
            "PYTHONHASHSEED": str(seed),
            "PYTHONPATH": str(REPO),
            "HALOCUE_USER_DATA_DIR": str(tmp_path / "userdata"),
        }
        output = tmp_path / f"seed{seed}"
        run = subprocess.run(
            [
                sys.executable,
                "-X",
                "utf8",
                "-c",
                PROGRAM,
                str(output),
                json.dumps(names),
                json.dumps(cast),
                str(seed),
            ],
            env=env,
            cwd=REPO,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
        )
        assert run.returncode == 0, run.stdout + run.stderr
        results.append(json.loads((output / "captured.json").read_text(encoding="utf-8")))
    assert len({r["static"] for r in results}) == 1, [r["static"] for r in results]
    assert all(r["fingerprint"] == results[0]["fingerprint"] for r in results)
    assert results[0]["fingerprint"]["speaker_order_version"] == "frequency-first-mention/1"
    assert all(order == expected for r in results for order in r["used"])


def test_frequency_then_source_order_selects_stable_alias_representative():
    from annotate import ordered_annotation_speakers

    names = ["别名乙", "Z", "别名甲", "A", "Z", "A", "叙述"]
    items = [{"who": name} for name in names]
    cast = {
        "别名甲": {"id": "shared"},
        "别名乙": {"id": "shared"},
        "Z": {"id": "z"},
        "A": {"id": "a"},
        "叙述": {"narrator": True},
    }
    assert ordered_annotation_speakers(items, list(range(len(items))), cast) == [
        "Z",
        "A",
        "别名乙",
        "叙述",
    ]
    assert ordered_annotation_speakers(items, [2, 0, 6], cast) == ["别名甲", "叙述"]
    assert ordered_annotation_speakers(items, [], cast) == []
