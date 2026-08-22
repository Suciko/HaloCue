"""Build the compact character-name index shipped with HaloCue.

The source character cards contain writing knowledge that does not belong in the
desktop package.  This tool extracts only ``name`` and ``aliases`` so runtime
character lookup can reconcile regional translations without depending on the
authoring skill directory.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def build_index(source_dir: Path) -> dict:
    grouped: dict[str, dict] = {}
    source_files = 0
    normalized_source_files = 0
    for path in sorted(source_dir.glob("*.json"), key=lambda item: item.name):
        source_text = path.read_text(encoding="utf-8-sig")
        try:
            payload = json.loads(source_text)
        except json.JSONDecodeError as exc:
            # A few authoring cards use JSON-with-trailing-commas.  Accept only
            # that mechanical extension; any other syntax error still fails.
            normalized = re.sub(r",(?=\s*[}\]])", "", source_text)
            try:
                payload = json.loads(normalized)
            except json.JSONDecodeError:
                raise ValueError(
                    f"invalid character card JSON: {path}: {exc}"
                ) from exc
            normalized_source_files += 1
        canonical_name = str(payload.get("name") or "").strip()
        if not canonical_name:
            continue
        source_files += 1
        entry = grouped.setdefault(
            canonical_name,
            {"canonical_name": canonical_name, "aliases": []},
        )
        seen = {str(value).casefold() for value in entry["aliases"]}
        for value in payload.get("aliases") or []:
            alias = str(value or "").strip()
            if not alias or alias.casefold() in seen:
                continue
            seen.add(alias.casefold())
            entry["aliases"].append(alias)
    return {
        "version": 1,
        "source_files": source_files,
        "normalized_source_files": normalized_source_files,
        "characters": list(grouped.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    index = build_index(args.source_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
