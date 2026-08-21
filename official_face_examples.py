"""Compact official face-context retrieval for annotation prompts.

The official corpus is kept outside the runtime prompt.  This module builds a
small, cacheable index keyed by the exact AA character id and face id, then
returns representative Chinese text contexts and silent reaction contexts.
It deliberately does not expose the official command stream to the model.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

import assetdb


HERE = Path(__file__).resolve().parent
DEFAULT_CORPUS_ROOT = HERE.parents[1] / "05-官方演出语料库"
DEFAULT_INDEX_PATH = DEFAULT_CORPUS_ROOT / "derived" / "face_text_examples.json"


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _compact_actions(events: list[Mapping[str, Any]], slot: int, start: int, end: int) -> tuple[list[str], list[str], bool]:
    emoticons: list[str] = []
    actions: list[str] = []
    closeup = False
    for event in events:
        index = int(event.get("event_index") or -1)
        if index <= start or index >= end or int(event.get("slot") or -1) != slot:
            continue
        command = str(event.get("command_normalized") or "").strip().lower()
        if command == "em":
            value = _clean_text(event.get("emoticon_raw"))
            if value and value not in emoticons:
                emoticons.append(value)
        elif command in {"jump", "hophop", "stiff", "shake", "greeting", "falldownl", "falldownr"}:
            if command not in actions:
                actions.append(command)
        elif command == "closeup":
            closeup = True
    return emoticons, actions, closeup


def build_face_example_index(corpus_root: str | Path = DEFAULT_CORPUS_ROOT) -> dict[str, Any]:
    """Build an index from the lossless official JSONL corpus."""
    root = Path(corpus_root)
    result: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    records_dir = root / "records"
    for path in sorted(records_dir.glob("scenario_*.jsonl")):
        with path.open(encoding="utf-8") as handle:
            for raw in handle:
                try:
                    record = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                events = [event for event in record.get("script_events") or [] if isinstance(event, Mapping)]
                character_events = [
                    event for event in events
                    if event.get("line_type") == "character" and str(event.get("face_id") or "").strip()
                ]
                text = _clean_text((record.get("text") or {}).get("zh_cn"))
                record_uid = _clean_text(record.get("record_uid"))
                for position, event in enumerate(character_events):
                    start = int(event.get("event_index") or 0)
                    next_start = (
                        int(character_events[position + 1].get("event_index") or 0)
                        if position + 1 < len(character_events) else 10**9
                    )
                    slot = int(event.get("slot") or 0)
                    emoticons, actions, closeup = _compact_actions(events, slot, start, next_start)
                    dialogue = text if _clean_text(event.get("dialogue_kr")) else ""
                    if not dialogue and not emoticons and not actions and not closeup:
                        continue
                    example = {
                        "text": dialogue,
                        "silent": not bool(dialogue),
                        "emoticons": emoticons,
                        "actions": actions,
                        "closeup": closeup,
                        "record_uid": record_uid,
                    }
                    ident = _clean_text(event.get("character_name_kr"))
                    face_id = _clean_text(event.get("face_id"))
                    if ident and face_id:
                        result[ident][face_id].append(example)
    compact: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for ident, faces in result.items():
        compact[ident] = {}
        for face_id, examples in faces.items():
            seen: set[tuple[Any, ...]] = set()
            unique = []
            for example in examples:
                key = (
                    example["text"], example["silent"],
                    tuple(example["emoticons"]), tuple(example["actions"]), example["closeup"],
                )
                if key in seen:
                    continue
                seen.add(key)
                unique.append(example)
            compact[ident][face_id] = unique
    return {"schema_version": 1, "characters": compact}


def ensure_face_example_index(
    corpus_root: str | Path = DEFAULT_CORPUS_ROOT,
    index_path: str | Path = DEFAULT_INDEX_PATH,
) -> Path | None:
    """Create/update the compact index when the official corpus is available."""
    root = Path(corpus_root)
    if not (root / "records").is_dir():
        return None
    destination = Path(index_path)
    if destination.is_file():
        newest_source = max((path.stat().st_mtime for path in (root / "records").glob("scenario_*.jsonl")), default=0)
        if destination.stat().st_mtime >= newest_source:
            return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(build_face_example_index(root), ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return destination


def load_face_examples(
    cast: Mapping[str, Mapping[str, Any]],
    faces_by_id: Mapping[str, Any],
    *,
    corpus_root: str | Path = DEFAULT_CORPUS_ROOT,
    index_path: str | Path = DEFAULT_INDEX_PATH,
    representative_limit: int = 3,
    db_path: str | Path | None = None,
    allow_json_fallback: bool = False,
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Return only examples matching the current cast and offered face ids.

    Runtime callers should provide ``db_path``. SQLite is authoritative after
    import; the JSON index remains only as a compatibility/build fallback for
    tools that are explicitly run before importing the corpus.
    """
    if db_path is not None and Path(db_path).is_file():
        result: dict[str, dict[str, list[dict[str, Any]]]] = {}
        con = assetdb.connect(db_path)
        try:
            for character in cast.values():
                ident = _clean_text(character.get("id"))
                if not ident:
                    continue
                capability = faces_by_id.get(ident) or []
                if isinstance(capability, Mapping):
                    faces = capability.get("faces") or []
                else:
                    faces = capability
                allowed = {
                    _clean_text(face.get("id")) for face in faces
                    if isinstance(face, Mapping) and _clean_text(face.get("id"))
                }
                if not allowed:
                    continue
                selected = assetdb.official_face_usage(
                    con,
                    ident=ident,
                    face_ids=allowed,
                    spine_signature=character.get("spine_signature", ""),
                    outfit_key=character.get("outfit_key", ""),
                    representative_limit=representative_limit,
                )
                if selected:
                    result[ident] = selected
        finally:
            con.close()
        return result
    if not allow_json_fallback:
        return {}
    path = ensure_face_example_index(corpus_root, index_path)
    if path is None:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    available = payload.get("characters") if isinstance(payload, Mapping) else {}
    result: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for character in cast.values():
        ident = _clean_text(character.get("id"))
        if not ident or ident not in available:
            continue
        capability = faces_by_id.get(ident) or []
        faces = capability.get("faces") if isinstance(capability, Mapping) else capability
        allowed = {_clean_text(face.get("id")) for face in faces or [] if isinstance(face, Mapping)}
        if not allowed:
            continue
        selected: dict[str, list[dict[str, Any]]] = {}
        for face_id in sorted(allowed):
            examples = available[ident].get(face_id) or []
            # Prefer examples with text, then examples that show an explicit
            # official reaction.  The limit is retrieval relevance, not an
            # output-token or character budget.
            ranked = sorted(
                examples,
                key=lambda item: (not bool(item.get("text")), not bool(item.get("emoticons") or item.get("actions") or item.get("closeup"))),
            )
            if ranked:
                selected[face_id] = ranked[: max(1, int(representative_limit))]
        if selected:
            result[ident] = selected
    return result
