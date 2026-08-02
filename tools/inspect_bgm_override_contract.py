"""Inspect AA snapshots for evidence of a native BGM override contract.

Ordinary output is an evidence diff and is never allowed to replace an
existing file.  The repository's formal contract is written only from complete
before/after/restart snapshots plus a separate human verification record.  The
tool makes no BGM-ID, loop, playback, or restart inference on its own.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from pathlib import PureWindowsPath
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = PROJECT_ROOT / "docs" / "bgm-native-contract.json"
CONTRACT_FIELDS = (
    "manifest_entry_fields",
    "supported_extensions",
    "path_folder",
    "id_strategy",
    "loop_units",
    "restart_verified",
)


class ContractEvidenceError(ValueError):
    """Raised when snapshots do not justify writing the formal AA contract."""


def _field(mapping: Mapping[str, Any], *names: str) -> Any:
    """Return a mapping field, accepting AA's PascalCase/camelCase variants."""
    lowered = {key.casefold(): value for key, value in mapping.items()}
    for name in names:
        if name in mapping:
            return mapping[name]
        value = lowered.get(name.casefold())
        if value is not None:
            return value
    return None


def _values(value: Any) -> list[dict[str, Any]]:
    """Normalize a JSON list or an AzureArchive ``$values`` wrapper."""
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, Mapping):
        values = value.get("$values")
        if isinstance(values, list):
            return [item for item in values if isinstance(item, dict)]
    return []


def _walk_mappings(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _walk_mappings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_mappings(child)


def _rows(aap: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return script rows from either simplified or AzureArchive AAP JSON."""
    direct = _field(aap, "rows")
    if direct is not None:
        return _values(direct)

    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    for node in _walk_mappings(aap):
        scripts = _field(node, "Scripts")
        for row in _values(scripts):
            marker = id(row)
            if marker not in seen:
                seen.add(marker)
                rows.append(row)
    return rows


def _row_text(row: Mapping[str, Any]) -> str:
    text = _field(row, "text")
    return "" if text is None else str(text)


def _row_bgm_id(row: Mapping[str, Any]) -> Any:
    return _field(row, "bgmId", "BgmId")


def _bgm_entries(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    return _values(_field(manifest, "BgmOverrides"))


def _row_bgm_pairs(aap: Mapping[str, Any]) -> list[tuple[str, Any]]:
    return [(_row_text(row), _row_bgm_id(row)) for row in _rows(aap)]


def _strictly_added_bgm_entry(
    before_entries: list[dict[str, Any]], after_entries: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Return one true multiset addition, rejecting mutations and removals."""
    if len(after_entries) != len(before_entries) + 1:
        return None
    unmatched_after = list(after_entries)
    for before_entry in before_entries:
        for index, after_entry in enumerate(unmatched_after):
            if after_entry == before_entry:
                unmatched_after.pop(index)
                break
        else:
            return None
    return unmatched_after[0] if len(unmatched_after) == 1 else None


def inspect_contract(
    before_manifest: Mapping[str, Any],
    after_manifest: Mapping[str, Any],
    before_aap: Mapping[str, Any],
    after_aap: Mapping[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Diff AA manifest and AAP snapshots without making unsupported inferences."""
    before_entries = _bgm_entries(before_manifest)
    after_entries = _bgm_entries(after_manifest)
    added_entries = [entry for entry in after_entries if entry not in before_entries]

    # Match equal dialogue text in encounter order so repeated lines remain
    # distinct rather than silently overwriting one another in a dictionary.
    before_by_text: dict[str, list[Any]] = {}
    for row in _rows(before_aap):
        before_by_text.setdefault(_row_text(row), []).append(_row_bgm_id(row))

    encountered: dict[str, int] = {}
    bgm_id_changes: list[dict[str, Any]] = []
    for row in _rows(after_aap):
        text = _row_text(row)
        index = encountered.get(text, 0)
        encountered[text] = index + 1
        prior_ids = before_by_text.get(text, [])
        if index >= len(prior_ids):
            continue
        before_id = prior_ids[index]
        after_id = _row_bgm_id(row)
        if before_id != after_id:
            bgm_id_changes.append({"text": text, "before": before_id, "after": after_id})

    return {"added_entries": added_entries, "bgm_id_changes": bgm_id_changes}


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as source:
        payload = json.load(source)
    if not isinstance(payload, dict):
        raise ValueError(f"snapshot root must be a JSON object: {path}")
    return payload


def _is_formal_contract_path(output: Path) -> bool:
    if output.resolve() == CONTRACT_PATH.resolve():
        return True
    try:
        return output.samefile(CONTRACT_PATH)
    except OSError:
        return False


def _write_new_json(path: Path, content: str) -> None:
    """Create an output exactly once; never overwrite a pre-existing path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as destination:
        destination.write(content)


def _require_nonempty_string_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        raise ContractEvidenceError(f"verification record field {name!r} must be a non-empty string list")
    return value


def _validate_verification_record(
    record: Mapping[str, Any],
    added_entry: Mapping[str, Any],
) -> dict[str, Any]:
    missing = [field for field in CONTRACT_FIELDS if field not in record]
    if missing:
        raise ContractEvidenceError(f"verification record is missing required fields: {', '.join(missing)}")

    manifest_entry_fields = _require_nonempty_string_list(record["manifest_entry_fields"], "manifest_entry_fields")
    if set(manifest_entry_fields) != set(added_entry):
        raise ContractEvidenceError("manifest_entry_fields does not exactly match the imported BgmOverrides entry")

    extensions = _require_nonempty_string_list(record["supported_extensions"], "supported_extensions")

    path_folder = record["path_folder"]
    if not isinstance(path_folder, str) or not path_folder:
        raise ContractEvidenceError("verification record field 'path_folder' must be a non-empty string")
    entry_path = _field(added_entry, "Path")
    if not isinstance(entry_path, str):
        raise ContractEvidenceError("imported BgmOverrides entry has no string Path")
    path_parts = PureWindowsPath(entry_path).parts
    if len(path_parts) < 2 or path_parts[0].casefold() != path_folder.casefold():
        raise ContractEvidenceError("path_folder does not match the imported BgmOverrides Path")
    observed_extension = PureWindowsPath(entry_path).suffix
    if not observed_extension or len(extensions) != 1 or extensions[0].casefold() != observed_extension.casefold():
        raise ContractEvidenceError("supported_extensions must contain exactly the probe file extension")

    id_strategy = record["id_strategy"]
    if not isinstance(id_strategy, Mapping) or not isinstance(id_strategy.get("kind"), str) or not id_strategy["kind"]:
        raise ContractEvidenceError("id_strategy must be an object with a non-empty kind")

    loop_units = record["loop_units"]
    if not isinstance(loop_units, Mapping) or not loop_units:
        raise ContractEvidenceError("loop_units must be a non-empty object")

    if record["restart_verified"] is not True:
        raise ContractEvidenceError("restart_verified must be explicitly true")
    if record.get("playback_verified") is not True or record.get("loop_verified") is not True:
        raise ContractEvidenceError("manual playback_verified and loop_verified must both be explicitly true")

    return {field: record[field] for field in CONTRACT_FIELDS}


def _build_formal_contract(
    before_manifest: Mapping[str, Any],
    after_manifest: Mapping[str, Any],
    before_aap: Mapping[str, Any],
    after_aap: Mapping[str, Any],
    restart_manifest: Mapping[str, Any] | None,
    restart_aap: Mapping[str, Any] | None,
    verification_record: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if restart_manifest is None or restart_aap is None:
        raise ContractEvidenceError("formal contract output requires both restart snapshots")
    if verification_record is None:
        raise ContractEvidenceError("formal contract output requires a separate manual verification record")
    if _bgm_entries(after_manifest) != _bgm_entries(restart_manifest):
        raise ContractEvidenceError("BgmOverrides entries changed after AA restart")
    if _row_bgm_pairs(after_aap) != _row_bgm_pairs(restart_aap):
        raise ContractEvidenceError("script bgmId values changed after AA restart")

    added_entry = _strictly_added_bgm_entry(_bgm_entries(before_manifest), _bgm_entries(after_manifest))
    if added_entry is None:
        raise ContractEvidenceError("formal contract requires exactly one unmodified multiset BgmOverrides addition")
    evidence = inspect_contract(before_manifest, after_manifest, before_aap, after_aap)
    changes = evidence["bgm_id_changes"]
    if (
        len(changes) != 1
        or type(changes[0]["before"]) is not int
        or changes[0]["before"] != 999
        or type(changes[0]["after"]) is not int
        or changes[0]["after"] < 0
        or changes[0]["after"] == 999
    ):
        raise ContractEvidenceError("formal contract requires one script bgmId change from 999 to a non-999 value")
    return _validate_verification_record(verification_record, added_entry)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before-manifest", required=True, type=Path)
    parser.add_argument("--after-manifest", required=True, type=Path)
    parser.add_argument("--before-aap", required=True, type=Path)
    parser.add_argument("--after-aap", required=True, type=Path)
    parser.add_argument("--output", type=Path, help="optional JSON evidence output path")
    parser.add_argument("--restart-manifest", type=Path, help="manifest captured after AA restart")
    parser.add_argument("--restart-aap", type=Path, help="AAP captured after AA restart")
    parser.add_argument(
        "--verification-record",
        type=Path,
        help="separate JSON record with human playback/loop confirmation and contract metadata",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        before_manifest = _load_json(args.before_manifest)
        after_manifest = _load_json(args.after_manifest)
        before_aap = _load_json(args.before_aap)
        after_aap = _load_json(args.after_aap)
        result = inspect_contract(before_manifest, after_manifest, before_aap, after_aap)
        rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            if _is_formal_contract_path(args.output):
                restart_manifest = _load_json(args.restart_manifest) if args.restart_manifest else None
                restart_aap = _load_json(args.restart_aap) if args.restart_aap else None
                verification_record = _load_json(args.verification_record) if args.verification_record else None
                formal_contract = _build_formal_contract(
                    before_manifest,
                    after_manifest,
                    before_aap,
                    after_aap,
                    restart_manifest,
                    restart_aap,
                    verification_record,
                )
                _write_new_json(args.output, json.dumps(formal_contract, ensure_ascii=False, indent=2) + "\n")
            else:
                _write_new_json(args.output, rendered)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
