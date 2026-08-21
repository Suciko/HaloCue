# -*- coding: utf-8 -*-
"""Targeted, local comparison of generated AA staging against official samples.

The benchmark intentionally compares staging structure rather than trying to
copy official dialogue, assets, or exact command counts.  It can export the
dialogue-only source for an annotation run, then report which observable event
families are absent or unsolicited in the generated AA script.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class BenchmarkSample:
    key: str
    label: str
    shard: str
    start: int
    end: int
    story_type: str
    purpose: str


SAMPLES = {
    "codebox_activity": BenchmarkSample(
        key="codebox_activity",
        label="Code:BOX 游戏开发部发现、邀请与游玩余波",
        shard="scenario_0",
        start=24423,
        end=24570,
        story_type="event",
        purpose="画外线索、登场揭示、群体反应、物件操作、蒙太奇与分组余波",
    ),
    "codebox_departure": BenchmarkSample(
        key="codebox_departure",
        label="Code:BOX 告别、退场与空镜余波",
        shard="scenario_0",
        start=24635,
        end=24699,
        story_type="event",
        purpose="离开意图、临别停顿、真实退场、脚步和留下者/空镜余波",
    ),
}

_OFFICIAL_FEATURES = {
    # `all` is the normalized form of #all;hide. It proves a clear/rebuild
    # command was emitted, but without video/manual evidence it is not proof
    # that every occurrence is a distinct hard cut in the final picture.
    "camera_cut": {"all"},
    # `a/al/ar` are appearance/alpha commands. They do not prove that a
    # character entered the physical scene; that needs explicit enter or
    # corroborating video/manual evidence.
    "real_entrance": {"enter"},
    "reveal_or_appearance": {"a", "al", "ar"},
    "real_exit": {"exit"},
    "emoticon": {"em"},
    "action": {"act", "greeting", "hophop", "jump", "stiff", "shake", "walk", "run", "move"},
    "closeup": {"closeup"},
    "reaction": {"em", "jump", "stiff", "hophop", "shake", "greeting"},
    "wait": {"wait"},
}
_GENERATED_COMMANDS = {
    "camera_cut": re.compile(r"^@camera_cut\b", re.IGNORECASE),
    "reveal_or_appearance": re.compile(r"^@reveal\b", re.IGNORECASE),
    "real_entrance": re.compile(r"^@enter\b", re.IGNORECASE),
    "real_exit": re.compile(r"^@exit\b", re.IGNORECASE),
    "sound": re.compile(r"^@(?:se|sound)\b", re.IGNORECASE),
    "wait": re.compile(r"^@wait\b", re.IGNORECASE),
    "background_transition": re.compile(r"^@trans\b", re.IGNORECASE),
    "background_change": re.compile(r"^@bg\b", re.IGNORECASE),
}
_REACTION_ACTIONS = {"greeting", "stiff", "shake", "jump", "hophop"}


def _dialogue_content_lines(text: str) -> list[str]:
    """Extract authored dialogue content while ignoring annotation metadata."""
    lines: list[str] = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("@"):
            continue
        if ":" not in line:
            continue
        _, content = line.split(":", 1)
        content = content.strip()
        if content:
            if content.startswith("#n") and lines:
                lines[-1] += content
            else:
                lines.append(content)
    return lines


def verify_generated_scope(expected_dialogue: str, generated_text: str) -> dict[str, Any]:
    """Verify that a generated annotated script covers the expected dialogue.

    Character names can be localized differently, so the comparison is made on
    ordered dialogue content. A mismatch makes the benchmark unverified; it
    must never be interpreted as a missing staging feature.
    """
    expected = _dialogue_content_lines(expected_dialogue)
    actual = _dialogue_content_lines(generated_text)
    expected_hash = hashlib.sha256("\n".join(expected).encode("utf-8")).hexdigest()
    actual_hash = hashlib.sha256("\n".join(actual).encode("utf-8")).hexdigest()
    mismatch_at = None
    for index, (left, right) in enumerate(zip(expected, actual)):
        if left != right:
            mismatch_at = index
            break
    if mismatch_at is None and len(expected) != len(actual):
        mismatch_at = min(len(expected), len(actual))
    return {
        "verified": mismatch_at is None,
        "expected_dialogue_lines": len(expected),
        "generated_dialogue_lines": len(actual),
        "first_mismatch_index": mismatch_at,
        "expected_content_sha256": expected_hash,
        "generated_content_sha256": actual_hash,
        "method": "ordered_dialogue_content_sha256",
        "note": "Names and annotation metadata are ignored; content order and count must match.",
    }


def _record_index(record: Mapping[str, Any]) -> int | None:
    value = record.get("global_record_index")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def load_sample_records(
    corpus_root: str | Path, sample: BenchmarkSample | str,
) -> list[dict[str, Any]]:
    """Read one bounded JSONL range without loading the official corpus."""
    spec = SAMPLES[sample] if isinstance(sample, str) else sample
    path = Path(corpus_root) / "records" / f"{spec.shard}.jsonl"
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for raw in handle:
            try:
                record = json.loads(raw)
            except json.JSONDecodeError:
                continue
            index = _record_index(record)
            if index is None or index < spec.start:
                continue
            if index > spec.end:
                break
            records.append(record)
    if not records:
        raise ValueError(f"未找到官方样本 {spec.key}: {path}")
    return records


def _commands(record: Mapping[str, Any]) -> Iterable[str]:
    for event in record.get("script_events") or []:
        if not isinstance(event, Mapping):
            continue
        command = str(event.get("command_normalized") or "").strip().lower()
        if command:
            yield command


def official_profile(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize the observable staging grammar of an official excerpt."""
    command_counts: Counter[str] = Counter()
    records_with_dialogue = 0
    silent_staging_records = 0
    background_changes = 0
    transitions = 0
    sounds = 0
    for record in records:
        commands = list(_commands(record))
        command_counts.update(commands)
        has_dialogue = bool(record.get("has_dialogue"))
        if has_dialogue:
            records_with_dialogue += 1
        elif commands:
            silent_staging_records += 1
        raw = record.get("raw") if isinstance(record.get("raw"), Mapping) else {}
        if raw.get("bg_name"):
            background_changes += 1
        if raw.get("transition"):
            transitions += 1
        if raw.get("sound"):
            sounds += 1
    features = {
        name: sum(command_counts[name] for name in commands)
        for name, commands in _OFFICIAL_FEATURES.items()
    }
    features.update({
        "silent_staging": silent_staging_records,
        "sound": sounds,
        "background_transition": transitions,
        "background_change": background_changes,
    })
    feature_confidence = {
        "camera_cut": "medium",
        "real_entrance": "high",
        "reveal_or_appearance": "high",
        "real_exit": "high",
        "emoticon": "high",
        "action": "high",
        "closeup": "high",
        "reaction": "high",
        "action": "high",
        "wait": "high",
        "sound": "medium",
        "background_transition": "medium",
        "background_change": "medium",
        # Consecutive raw records may be one fade/rebuild visual beat. Video
        # or a corrected manual annotation must establish the merged count.
        "silent_staging": "low",
    }
    evidence_basis = {
        "camera_cut": "normalized_command_only; #all;hide may combine clear/rebuild/fade boundaries",
        "real_entrance": "explicit_normalized_enter_only",
        "reveal_or_appearance": "normalized_appearance_command_only",
        "real_exit": "explicit_normalized_exit_only",
        "emoticon": "normalized_command_only",
        "action": "normalized_command_only",
        "closeup": "normalized_command_only",
        "reaction": "derived_union_of_emoticon_and_body_commands",
        "wait": "normalized_command_only",
        "sound": "raw_record_sound_field",
        "background_transition": "raw_record_transition_field",
        "background_change": "raw_record_bg_name_field",
        "silent_staging": "record_boundary_without_dialogue; low confidence until video/manual merge",
    }
    return {
        "records_with_dialogue": records_with_dialogue,
        "silent_staging_records": silent_staging_records,
        "command_counts": dict(sorted(command_counts.items())),
        "features": features,
        "feature_confidence": feature_confidence,
        "feature_evidence_basis": evidence_basis,
        "comparison_scope": "normalized official command records; not a frame-accurate visual ground truth",
    }


def generated_profile(script_text: str) -> dict[str, Any]:
    """Summarize a generated annotated script using AA-facing syntax only."""
    features: Counter[str] = Counter()
    command_counts: Counter[str] = Counter()
    dialogue_lines = 0
    silent_staging_lines = 0
    visible_characters: set[str] = set()
    nodialog_pending = False
    for raw in str(script_text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            # Compiler comments are annotations for humans, not dialogue nodes.
            continue
        if re.match(r"^@nodialog\b", line, re.IGNORECASE):
            silent_staging_lines += 1
            nodialog_pending = True
        camera = re.match(r"^@camera(?:_hold|_cut)?\s+(.+)$", line, re.IGNORECASE)
        if camera:
            next_visible = {
                value.strip() for value in camera.group(1).split(",")
                if value.strip() and value.strip().lower() != "auto"
            }
            features["reveal_or_appearance"] += len(next_visible - visible_characters)
            visible_characters = next_visible
        if re.match(r"^@reveal\b", line, re.IGNORECASE):
            features["visual_reveal"] += 1
        if re.match(r"^@fx\b.*(?:特写|closeup)\s*$", line, re.IGNORECASE) or re.search(
            r"<[^>]*(?:特写|closeup)[^>]*>", line, re.IGNORECASE
        ):
            features["closeup"] += 1
        matched = False
        for name, pattern in _GENERATED_COMMANDS.items():
            if pattern.match(line):
                features[name] += 1
                command_counts[name] += 1
                matched = True
                break
        if matched:
            continue
        if ":" in line and not line.startswith("@"):
            if nodialog_pending:
                nodialog_pending = False
            else:
                dialogue_lines += 1
            has_emoticon = bool(re.search(r"\[[^\]]+\]", line))
            has_emoticon = has_emoticon or bool(
                re.search(r"<[^>]*(?:emo|bubble|气泡)[^>]*>", line, re.IGNORECASE)
            )
            if has_emoticon:
                features["emoticon"] += 1
            line_reaction = False
            for action in re.findall(r"\{([^}]+)\}", line):
                normalized = action.strip().lower()
                if normalized in _REACTION_ACTIONS:
                    line_reaction = True
                features["action"] += 1
            if has_emoticon or line_reaction:
                features["reaction"] += 1
            continue
    features["silent_staging"] = silent_staging_lines
    return {
        "dialogue_lines": dialogue_lines,
        "silent_staging_lines": silent_staging_lines,
        "command_counts": dict(sorted(command_counts.items())),
        "features": dict(features),
        "comparison_scope": "generated annotated AA-facing text; counts authored syntax, not final frame semantics",
    }


def compare_profiles(reference: Mapping[str, Any], generated: Mapping[str, Any]) -> dict[str, Any]:
    """Report evidence-qualified structural gaps, never a similarity score."""
    reference_features = reference.get("features") if isinstance(reference.get("features"), Mapping) else {}
    generated_features = generated.get("features") if isinstance(generated.get("features"), Mapping) else {}
    confidence = reference.get("feature_confidence") if isinstance(
        reference.get("feature_confidence"), Mapping
    ) else {}
    evidence_basis = reference.get("feature_evidence_basis") if isinstance(
        reference.get("feature_evidence_basis"), Mapping
    ) else {}
    dimensions = sorted(set(reference_features) | set(generated_features))
    comparison = []
    for name in dimensions:
        expected = int(reference_features.get(name) or 0)
        actual = int(generated_features.get(name) or 0)
        status = "not_required" if not expected and not actual else (
            "missing" if expected and not actual else "unsolicited" if actual and not expected else "present"
        )
        level = str(confidence.get(name) or "unknown")
        comparison.append({
            "dimension": name,
            "official": expected,
            "generated": actual,
            "count_comparable": False,
            "count_note": "official command-event counts and generated authored-line counts use different units",
            "status": status,
            "confidence": level,
            "evidence_basis": str(evidence_basis.get(name) or "generated_syntax_only"),
            "score_eligible": level in {"high", "medium"},
        })
    return {
        "method": "feature_presence_and_count_report",
        "not_similarity_percentage": True,
        "warning": "This report does not estimate visual similarity or an official-match percentage.",
        "comparison": comparison,
        "missing": [
            item["dimension"] for item in comparison
            if item["status"] == "missing" and item.get("score_eligible")
        ],
        "low_confidence": [
            item["dimension"] for item in comparison
            if item.get("confidence") == "low"
        ],
    }


def dialogue_source(records: Iterable[Mapping[str, Any]]) -> str:
    """Export dialogue only, deliberately omitting the official command stream."""
    lines: list[str] = []
    for record in records:
        text = record.get("text") if isinstance(record.get("text"), Mapping) else {}
        localized = str(text.get("zh_cn") or text.get("zh_tw") or "").strip()
        dialogue_events = [
            event for event in record.get("script_events") or []
            if isinstance(event, Mapping) and str(event.get("dialogue_kr") or "").strip()
        ]
        if not dialogue_events:
            continue
        for index, event in enumerate(dialogue_events):
            speaker = str(event.get("character_name_kr") or "角色").strip()
            content = localized if index == 0 and localized else str(event.get("dialogue_kr") or "").strip()
            if speaker and content:
                lines.append(f"{speaker}: {content}")
    return "\n".join(lines) + ("\n" if lines else "")


def benchmark_sample(
    corpus_root: str | Path,
    sample: BenchmarkSample | str,
    generated_text: str,
    *,
    expected_dialogue: str | None = None,
    generated_scope: str | None = None,
) -> dict[str, Any]:
    spec = SAMPLES[sample] if isinstance(sample, str) else sample
    records = load_sample_records(corpus_root, spec)
    reference = official_profile(records)
    generated = generated_profile(generated_text)
    comparison = compare_profiles(reference, generated)
    if expected_dialogue is not None:
        official_to_input = verify_generated_scope(dialogue_source(records), expected_dialogue)
        input_to_generated = verify_generated_scope(expected_dialogue, generated_text)
        scope = {
            "verified": bool(official_to_input["verified"] and input_to_generated["verified"]),
            "official_to_input": official_to_input,
            "input_to_generated": input_to_generated,
            "note": "Both links must match before feature differences are interpretable.",
        }
    else:
        scope = {
            "verified": False,
            "status": "not_provided",
            "note": "Pass the exact dialogue-only input used for this run before interpreting differences.",
        }
    if not scope["verified"]:
        comparison["missing"] = []
        comparison["comparison_interpretable"] = False
        for item in comparison["comparison"]:
            item["status"] = "scope_unverified"
            item["score_eligible"] = False
    else:
        comparison["comparison_interpretable"] = True
    return {
        "sample": {
            "key": spec.key, "label": spec.label, "story_type": spec.story_type,
            "purpose": spec.purpose, "record_range": [spec.start, spec.end],
        },
        "reference": reference,
        "generated": generated,
        "generated_scope": generated_scope or "unspecified",
        "scope_verification": scope,
        **comparison,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare generated AA staging with a bounded official sample")
    parser.add_argument("--corpus-root", required=True, help="05-官方演出语料库 directory")
    parser.add_argument("--sample", choices=sorted(SAMPLES), default="codebox_activity")
    parser.add_argument("--generated", help="Generated annotated script to compare")
    parser.add_argument(
        "--expected-dialogue",
        help="Exact dialogue-only input used by the generation run; enables scope verification",
    )
    parser.add_argument(
        "--generated-scope",
        help="Human-readable generated scope label (for example: codebox_activity)",
    )
    parser.add_argument("--write-dialogue", help="Write dialogue-only input for an annotation run")
    args = parser.parse_args(argv)
    spec = SAMPLES[args.sample]
    records = load_sample_records(args.corpus_root, spec)
    if args.write_dialogue:
        Path(args.write_dialogue).write_text(dialogue_source(records), encoding="utf-8")
    report = benchmark_sample(
        args.corpus_root, spec,
        Path(args.generated).read_text(encoding="utf-8") if args.generated else "",
        expected_dialogue=(
            Path(args.expected_dialogue).read_text(encoding="utf-8")
            if args.expected_dialogue
            else None
        ),
        generated_scope=args.generated_scope,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
