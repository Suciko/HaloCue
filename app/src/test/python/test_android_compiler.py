import json
from pathlib import Path

from android_compiler import compile_text


def test_compile_text_writes_a_valid_unimported_aap_to_app_workspace(tmp_path):
    result = compile_text(
        "桃井: 安卓端你好\n",
        project="安卓端最小工程",
        workspace=tmp_path,
    )

    aap_file = Path(result["aap_file"])
    project_dir = Path(result["project_dir"])
    payload = json.loads(aap_file.read_text(encoding="utf-8"))
    script_nodes = [
        node
        for node in payload["nodes"]["$values"]
        if node["$type"].startswith("ScriptNodeData")
    ]
    dialogue = script_nodes[0]["Scripts"]["$values"][0]

    assert result["project"] == "安卓端最小工程"
    assert result["dialogue_count"] == 1
    assert result["imported"] is False
    assert aap_file.parent == tmp_path / "exports"
    assert project_dir.parent == tmp_path / "exports"
    assert payload["ProjectName"] == "安卓端最小工程"
    assert dialogue["text"] == "安卓端你好"
    assert dialogue["characters"]["$values"][dialogue["speakerSlotNum"]]["name"] == "모모이"
