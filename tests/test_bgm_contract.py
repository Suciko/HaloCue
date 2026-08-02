import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools import inspect_bgm_override_contract as inspector
from tools.inspect_bgm_override_contract import inspect_contract


def _write_cli_snapshots(tmp_path):
    snapshots = {
        "before-manifest.json": {"BgmOverrides": []},
        "after-manifest.json": {"BgmOverrides": [{"Path": r"bgms\tone.ogg", "Volume": "1"}]},
        "before.aap": {"rows": [{"text": "probe", "bgmId": 999}]},
        "after.aap": {"rows": [{"text": "probe", "bgmId": 5}]},
        "restart-manifest.json": {"BgmOverrides": [{"Path": r"bgms\tone.ogg", "Volume": "1"}]},
        "restart.aap": {"rows": [{"text": "probe", "bgmId": 5}]},
    }
    for name, payload in snapshots.items():
        (tmp_path / name).write_text(json.dumps(payload), encoding="utf-8")
    return snapshots


def _cli_args(tmp_path, output, *, include_restart=False, verification_record=None):
    args = [
        "--before-manifest", str(tmp_path / "before-manifest.json"),
        "--after-manifest", str(tmp_path / "after-manifest.json"),
        "--before-aap", str(tmp_path / "before.aap"),
        "--after-aap", str(tmp_path / "after.aap"),
        "--output", str(output),
    ]
    if include_restart:
        args += [
            "--restart-manifest", str(tmp_path / "restart-manifest.json"),
            "--restart-aap", str(tmp_path / "restart.aap"),
        ]
    if verification_record:
        args += ["--verification-record", str(verification_record)]
    return args


def _write_verified_record(tmp_path, **overrides):
    record = {
        "manifest_entry_fields": ["Path", "Volume"],
        "supported_extensions": [".ogg"],
        "path_folder": "bgms",
        "id_strategy": {"kind": "native-probe-fixture"},
        "loop_units": {"LoopStartTime": "seconds"},
        "restart_verified": True,
        "playback_verified": True,
        "loop_verified": True,
    }
    record.update(overrides)
    path = tmp_path / "manual-verification.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def _run_formal_cli(tmp_path, contract_path, verification_record):
    return inspector.main(
        _cli_args(
            tmp_path,
            contract_path,
            include_restart=True,
            verification_record=verification_record,
        )
    )


def test_inspector_reports_one_added_bgm_and_changed_script_id():
    result = inspect_contract(
        {"BgmOverrides": []},
        {
            "BgmOverrides": [
                {
                    "Path": r"bgms\demo.ogg",
                    "LoopStartTime": "0",
                    "LoopEndTime": "12.5",
                    "LoopTransitionTime": "0",
                    "LoopOffsetTime": "0",
                    "Volume": "1",
                }
            ]
        },
        {"rows": [{"text": "probe", "bgmId": 999}]},
        {"rows": [{"text": "probe", "bgmId": 7}]},
    )

    assert result["added_entries"][0]["Path"] == r"bgms\demo.ogg"
    assert result["bgm_id_changes"] == [{"text": "probe", "before": 999, "after": 7}]


def test_inspector_reads_azurearchive_values_with_pascal_case_script_fields():
    before_aap = {
        "Nodes": {
            "$values": [
                {"Scripts": {"$values": [{"Text": "BGM_NATIVE_PROBE", "BgmId": 999}]}}
            ]
        }
    }
    after_aap = {
        "Nodes": {
            "$values": [
                {"Scripts": {"$values": [{"Text": "BGM_NATIVE_PROBE", "BgmId": 7}]}}
            ]
        }
    }

    result = inspect_contract(
        {"BgmOverrides": {"$values": []}},
        {"BgmOverrides": {"$values": [{"Path": r"bgms\probe.ogg"}]}},
        before_aap,
        after_aap,
    )

    assert result == {
        "added_entries": [{"Path": r"bgms\probe.ogg"}],
        "bgm_id_changes": [{"text": "BGM_NATIVE_PROBE", "before": 999, "after": 7}],
    }


def test_inspector_matches_duplicate_text_rows_by_occurrence():
    result = inspect_contract(
        {"BgmOverrides": []},
        {"BgmOverrides": []},
        {"rows": [{"text": "same", "bgmId": 999}, {"text": "same", "bgmId": 4}]},
        {"rows": [{"text": "same", "bgmId": 2}, {"text": "same", "bgmId": 4}]},
    )

    assert result["bgm_id_changes"] == [{"text": "same", "before": 999, "after": 2}]


def test_inspector_cli_loads_snapshots_and_writes_json(tmp_path):
    _write_cli_snapshots(tmp_path)

    output = tmp_path / "contract-evidence.json"
    script = Path(__file__).parents[1] / "tools" / "inspect_bgm_override_contract.py"
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--before-manifest",
            str(tmp_path / "before-manifest.json"),
            "--after-manifest",
            str(tmp_path / "after-manifest.json"),
            "--before-aap",
            str(tmp_path / "before.aap"),
            "--after-aap",
            str(tmp_path / "after.aap"),
            "--output",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    expected = {
        "added_entries": [{"Path": r"bgms\tone.ogg", "Volume": "1"}],
        "bgm_id_changes": [{"text": "probe", "before": 999, "after": 5}],
    }
    assert json.loads(completed.stdout) == expected
    assert json.loads(output.read_text(encoding="utf-8")) == expected


def test_cli_rejects_formal_contract_output_without_verified_evidence(tmp_path, monkeypatch):
    _write_cli_snapshots(tmp_path)
    contract_path = tmp_path / "docs" / "bgm-native-contract.json"
    monkeypatch.setattr(inspector, "CONTRACT_PATH", contract_path, raising=False)

    status = inspector.main(_cli_args(tmp_path, contract_path))

    assert status != 0
    assert not contract_path.exists()


def test_cli_rejects_formal_contract_output_when_restart_evidence_is_missing(tmp_path, monkeypatch):
    _write_cli_snapshots(tmp_path)
    contract_path = tmp_path / "docs" / "bgm-native-contract.json"
    verification_record = tmp_path / "manual-verification.json"
    verification_record.write_text(
        json.dumps(
            {
                "manifest_entry_fields": ["Path", "Volume"],
                "supported_extensions": [".ogg"],
                "path_folder": "bgms",
                "id_strategy": {"kind": "native-probe-fixture"},
                "loop_units": {"LoopStartTime": "seconds"},
                "restart_verified": True,
                "playback_verified": True,
                "loop_verified": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(inspector, "CONTRACT_PATH", contract_path, raising=False)

    status = inspector.main(_cli_args(tmp_path, contract_path, verification_record=verification_record))

    assert status != 0
    assert not contract_path.exists()


def test_cli_writes_formal_contract_only_from_complete_verified_evidence(tmp_path, monkeypatch):
    _write_cli_snapshots(tmp_path)
    contract_path = tmp_path / "docs" / "bgm-native-contract.json"
    verification_record = tmp_path / "manual-verification.json"
    verification_record.write_text(
        json.dumps(
            {
                "manifest_entry_fields": ["Path", "Volume"],
                "supported_extensions": [".ogg"],
                "path_folder": "bgms",
                "id_strategy": {"kind": "native-probe-fixture"},
                "loop_units": {"LoopStartTime": "seconds"},
                "restart_verified": True,
                "playback_verified": True,
                "loop_verified": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(inspector, "CONTRACT_PATH", contract_path, raising=False)

    status = inspector.main(
        _cli_args(
            tmp_path,
            contract_path,
            include_restart=True,
            verification_record=verification_record,
        )
    )

    assert status == 0
    assert json.loads(contract_path.read_text(encoding="utf-8")) == {
        "manifest_entry_fields": ["Path", "Volume"],
        "supported_extensions": [".ogg"],
        "path_folder": "bgms",
        "id_strategy": {"kind": "native-probe-fixture"},
        "loop_units": {"LoopStartTime": "seconds"},
        "restart_verified": True,
    }


def test_cli_rejects_formal_contract_when_restart_bgm_id_does_not_persist(tmp_path, monkeypatch):
    _write_cli_snapshots(tmp_path)
    (tmp_path / "restart.aap").write_text(
        json.dumps({"rows": [{"text": "probe", "bgmId": 999}]}), encoding="utf-8"
    )
    contract_path = tmp_path / "docs" / "bgm-native-contract.json"
    verification_record = tmp_path / "manual-verification.json"
    verification_record.write_text(
        json.dumps(
            {
                "manifest_entry_fields": ["Path", "Volume"],
                "supported_extensions": [".ogg"],
                "path_folder": "bgms",
                "id_strategy": {"kind": "native-probe-fixture"},
                "loop_units": {"LoopStartTime": "seconds"},
                "restart_verified": True,
                "playback_verified": True,
                "loop_verified": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(inspector, "CONTRACT_PATH", contract_path, raising=False)

    status = inspector.main(
        _cli_args(
            tmp_path,
            contract_path,
            include_restart=True,
            verification_record=verification_record,
        )
    )

    assert status != 0
    assert not contract_path.exists()


def test_cli_rejects_formal_contract_when_import_did_not_start_from_silence(tmp_path, monkeypatch):
    _write_cli_snapshots(tmp_path)
    (tmp_path / "before.aap").write_text(
        json.dumps({"rows": [{"text": "probe", "bgmId": 2}]}), encoding="utf-8"
    )
    contract_path = tmp_path / "docs" / "bgm-native-contract.json"
    verification_record = tmp_path / "manual-verification.json"
    verification_record.write_text(
        json.dumps(
            {
                "manifest_entry_fields": ["Path", "Volume"],
                "supported_extensions": [".ogg"],
                "path_folder": "bgms",
                "id_strategy": {"kind": "native-probe-fixture"},
                "loop_units": {"LoopStartTime": "seconds"},
                "restart_verified": True,
                "playback_verified": True,
                "loop_verified": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(inspector, "CONTRACT_PATH", contract_path, raising=False)

    status = inspector.main(
        _cli_args(
            tmp_path,
            contract_path,
            include_restart=True,
            verification_record=verification_record,
        )
    )

    assert status != 0
    assert not contract_path.exists()


def test_cli_does_not_overwrite_an_existing_formal_contract(tmp_path, monkeypatch):
    _write_cli_snapshots(tmp_path)
    contract_path = tmp_path / "docs" / "bgm-native-contract.json"
    contract_path.parent.mkdir()
    contract_path.write_text('{"preserve":"existing-contract"}', encoding="utf-8")
    verification_record = tmp_path / "manual-verification.json"
    verification_record.write_text(
        json.dumps(
            {
                "manifest_entry_fields": ["Path", "Volume"],
                "supported_extensions": [".ogg"],
                "path_folder": "bgms",
                "id_strategy": {"kind": "native-probe-fixture"},
                "loop_units": {"LoopStartTime": "seconds"},
                "restart_verified": True,
                "playback_verified": True,
                "loop_verified": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(inspector, "CONTRACT_PATH", contract_path, raising=False)

    status = inspector.main(
        _cli_args(
            tmp_path,
            contract_path,
            include_restart=True,
            verification_record=verification_record,
        )
    )

    assert status != 0
    assert contract_path.read_text(encoding="utf-8") == '{"preserve":"existing-contract"}'


def test_cli_does_not_overwrite_an_existing_ordinary_evidence_output(tmp_path):
    _write_cli_snapshots(tmp_path)
    output = tmp_path / "evidence.json"
    output.write_text('{"preserve":"ordinary-evidence"}', encoding="utf-8")

    status = inspector.main(_cli_args(tmp_path, output))

    assert status != 0
    assert output.read_text(encoding="utf-8") == '{"preserve":"ordinary-evidence"}'


def test_cli_treats_hardlink_alias_of_formal_contract_as_protected(tmp_path, monkeypatch):
    _write_cli_snapshots(tmp_path)
    contract_path = tmp_path / "docs" / "bgm-native-contract.json"
    contract_path.parent.mkdir()
    contract_path.write_text('{"preserve":"formal-contract"}', encoding="utf-8")
    alias = tmp_path / "formal-contract-alias.json"
    try:
        os.link(contract_path, alias)
    except OSError as exc:
        pytest.skip(f"hard links unavailable: {exc}")
    monkeypatch.setattr(inspector, "CONTRACT_PATH", contract_path, raising=False)

    assert inspector._is_formal_contract_path(alias)
    status = inspector.main(_cli_args(tmp_path, alias))

    assert status != 0
    assert contract_path.read_text(encoding="utf-8") == '{"preserve":"formal-contract"}'
    assert alias.samefile(contract_path)


def test_cli_rejects_manifest_entry_mutation_instead_of_one_new_entry(tmp_path, monkeypatch):
    _write_cli_snapshots(tmp_path)
    before = {"BgmOverrides": [{"Path": r"bgms\tone.ogg", "Volume": "0.4"}]}
    after = {"BgmOverrides": [{"Path": r"bgms\tone.ogg", "Volume": "1"}]}
    for name, payload in {
        "before-manifest.json": before,
        "after-manifest.json": after,
        "restart-manifest.json": after,
    }.items():
        (tmp_path / name).write_text(json.dumps(payload), encoding="utf-8")
    contract_path = tmp_path / "docs" / "bgm-native-contract.json"
    monkeypatch.setattr(inspector, "CONTRACT_PATH", contract_path, raising=False)

    status = _run_formal_cli(tmp_path, contract_path, _write_verified_record(tmp_path))

    assert status != 0
    assert not contract_path.exists()


def test_cli_rejects_contract_metadata_with_unobserved_extension(tmp_path, monkeypatch):
    _write_cli_snapshots(tmp_path)
    contract_path = tmp_path / "docs" / "bgm-native-contract.json"
    monkeypatch.setattr(inspector, "CONTRACT_PATH", contract_path, raising=False)

    status = _run_formal_cli(
        tmp_path,
        contract_path,
        _write_verified_record(tmp_path, supported_extensions=[".ogg", ".mp3"]),
    )

    assert status != 0
    assert not contract_path.exists()


@pytest.mark.parametrize(
    ("before_id", "after_id"),
    [
        ("999", 5),
        (True, 5),
        (999, "5"),
        (999, True),
        (999, {}),
        (999, -1),
    ],
)
def test_cli_rejects_non_integer_or_invalid_probe_bgm_ids(tmp_path, monkeypatch, before_id, after_id):
    _write_cli_snapshots(tmp_path)
    for name, payload in {
        "before.aap": {"rows": [{"text": "probe", "bgmId": before_id}]},
        "after.aap": {"rows": [{"text": "probe", "bgmId": after_id}]},
        "restart.aap": {"rows": [{"text": "probe", "bgmId": after_id}]},
    }.items():
        (tmp_path / name).write_text(json.dumps(payload), encoding="utf-8")
    contract_path = tmp_path / "docs" / "bgm-native-contract.json"
    monkeypatch.setattr(inspector, "CONTRACT_PATH", contract_path, raising=False)

    status = _run_formal_cli(tmp_path, contract_path, _write_verified_record(tmp_path))

    assert status != 0
    assert not contract_path.exists()


@pytest.mark.parametrize("bad_snapshot", ["missing", "invalid_json", "directory"])
def test_cli_reports_snapshot_input_errors_without_traceback(tmp_path, bad_snapshot):
    _write_cli_snapshots(tmp_path)
    after_aap = tmp_path / "after.aap"
    if bad_snapshot == "missing":
        after_aap.unlink()
    elif bad_snapshot == "invalid_json":
        after_aap.write_text("not json", encoding="utf-8")
    else:
        after_aap.unlink()
        after_aap.mkdir()
    script = Path(__file__).parents[1] / "tools" / "inspect_bgm_override_contract.py"
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--before-manifest", str(tmp_path / "before-manifest.json"),
            "--after-manifest", str(tmp_path / "after-manifest.json"),
            "--before-aap", str(tmp_path / "before.aap"),
            "--after-aap", str(after_aap),
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert completed.stderr.startswith("error: ")
    assert "Traceback" not in completed.stderr
