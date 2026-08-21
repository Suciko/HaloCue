# -*- coding: utf-8 -*-
"""Plan and run resumable visual labeling for official AA face skeletons.

Default selection is deliberately conservative: complete CH/NP portrait
bundles, at least four distinct numbered faces, and no obvious anonymous mob
name.  Every exclusion is recorded in the plan so the filter can be audited.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import assetdb
from llm import make_provider, make_provider_from_settings
from model_profiles import ModelProfileStore
from official_spine_cache import materialize_official_spines
from spine_face_labeler import label_face_images, persist_visual_face_labels
from spine_face_inventory import (
    build_spine_animation_inventory,
    discover_spine_inventory_candidates,
)
from spine_face_web_renderer import SpineWebRenderer, _bundle_files, detect_spine_version


HERE = Path(__file__).resolve().parent
_MAIN_STEM_RE = re.compile(r"^(?:CH|NP)\d+_spr$", re.IGNORECASE)
_FACE_ID_RE = re.compile(r"^\d{2}$")
_SUPPORTING_NAME_RE = re.compile(
    r"(?:学生|成员|部员|组员|暴走族|Mob|モブ).*(?:[A-ZＡ-Ｚ]|[0-9０-９])(?:（[^）]+）)?$",
    re.IGNORECASE,
)


def _batch_provider(args):
    if args.model_profile_id:
        store = ModelProfileStore(args.model_profiles)
        name, settings = store.provider_settings_for_model(args.model_profile_id)
        provider = make_provider_from_settings(name, settings)
    else:
        provider = make_provider(args.llm, args.provider)
    if args.model:
        provider.model = str(args.model)
    return provider


@dataclass(frozen=True)
class IdentityBinding:
    identifier: str
    outfit_key: str
    spine_signature: str
    name: str
    club: str = ""
    identity_status: str = "mapped"

    def key(self) -> tuple[str, str, str]:
        return self.identifier, self.outfit_key, self.spine_signature


@dataclass(frozen=True)
class FaceBatchTarget:
    identifier: str
    name: str
    club: str
    source_dir: str
    spine_signature: str
    outfit_key: str
    spine_version: str
    face_ids: tuple[str, ...]
    source_kind: str = "extra_pack"
    source_root: str = ""
    identity_status: str = "mapped"
    source_evidence: dict | None = None
    identity_bindings: tuple[IdentityBinding, ...] = ()

    @property
    def face_count(self) -> int:
        return len(self.face_ids)

    @property
    def bindings(self) -> tuple[IdentityBinding, ...]:
        if self.identity_bindings:
            return self.identity_bindings
        return (IdentityBinding(
            identifier=self.identifier,
            outfit_key=self.outfit_key,
            spine_signature=self.spine_signature,
            name=self.name,
            club=self.club,
            identity_status=self.identity_status,
        ),)

    def to_json(self) -> dict:
        data = asdict(self)
        data["face_ids"] = list(self.face_ids)
        data["face_count"] = self.face_count
        data["identity_bindings"] = [asdict(item) for item in self.bindings]
        data["identity_binding_count"] = len(self.bindings)
        return data


def _spine_base(overrides_root: Path, value: str) -> Path:
    return overrides_root / Path(str(value or "").replace("\\", "/"))


def _candidate_bundle_dirs(root: Path, value: str) -> tuple[Path, ...]:
    base = _spine_base(root, value)
    # Extra packs store ``.../CHxxxx_spr/CHxxxx_spr.skel``. The materialized
    # official cache adds one directory named by the official outfit key so
    # hundreds of native bundles never share the same parent directory.
    candidates = [base] if base.is_dir() else []
    candidates.append(base.parent)
    return tuple(dict.fromkeys(path.resolve() for path in candidates))


def _inventory_maps(inventory: dict | None):
    by_outfit = {}
    by_spine = {}
    for row in (inventory or {}).get("records") or []:
        if not isinstance(row, dict) or row.get("status") != "ready":
            continue
        outfit = str(row.get("outfit_key") or "").strip().casefold()
        spine = str(row.get("spine") or "").replace("\\", "/").strip().casefold()
        if outfit:
            by_outfit.setdefault(outfit, row)
        if spine:
            by_spine.setdefault(spine, row)
    return by_outfit, by_spine


def _numbered_face_ids(character: dict) -> tuple[str, ...]:
    return tuple(sorted({
        str(item.get("id") or "")
        for item in character.get("faces") or []
        if isinstance(item, dict) and _FACE_ID_RE.fullmatch(str(item.get("id") or ""))
    }))


def discover_main_character_targets(
    index: dict,
    *,
    overrides_root: str | Path | Iterable[str | Path],
    min_faces: int = 4,
    include_supporting: bool = False,
    include_unmapped: bool = True,
    inventory: dict | None = None,
) -> tuple[list[FaceBatchTarget], list[dict]]:
    if isinstance(overrides_root, (str, Path)):
        roots = [Path(overrides_root).resolve()]
    else:
        roots = [Path(value).resolve() for value in overrides_root]
    roots = list(dict.fromkeys(roots))
    if not roots:
        raise ValueError("at least one resource root is required")
    targets: list[FaceBatchTarget] = []
    excluded: list[dict] = []
    seen_paths: set[str] = set()
    target_index_by_path: dict[str, int] = {}
    matched_inventory_dirs: set[str] = set()
    inventory_by_outfit, inventory_by_spine = _inventory_maps(inventory)
    for character in index.get("characters") or []:
        if not isinstance(character, dict):
            continue
        identifier = str(character.get("identifier") or "").strip()
        name = str(character.get("name") or identifier).strip()
        relative_spine = str(character.get("spine") or "")
        outfit_key = str(character.get("outfit_key") or "").strip()
        inventory_row = (
            inventory_by_outfit.get(outfit_key.casefold())
            or inventory_by_spine.get(
                relative_spine.replace("\\", "/").strip().casefold()
            )
        )
        face_ids = tuple(inventory_row.get("face_ids") or ()) if inventory_row else (
            _numbered_face_ids(character)
        )
        reason = ""
        if not identifier or not name:
            reason = "missing_character_name"
        elif len(face_ids) < max(1, int(min_faces)):
            reason = "too_few_faces"
        elif not include_supporting and _SUPPORTING_NAME_RE.search(identifier):
            reason = "anonymous_supporting_character"
        if reason:
            excluded.append({
                "identifier": identifier,
                "name": name,
                "spine": str(character.get("spine") or ""),
                "face_count": len(face_ids),
                "reason": reason,
            })
            continue
        selected = None
        failure_reasons = []
        if inventory_row:
            source_dir = Path(str(inventory_row.get("source_dir") or "")).resolve()
            selected = (source_dir, str(inventory_row.get("spine_version") or ""))
            matched_inventory_dirs.add(str(source_dir).casefold())
        else:
            for root in roots:
                for bundle_dir in _candidate_bundle_dirs(root, relative_spine):
                    try:
                        skeleton, _, _ = _bundle_files(bundle_dir)
                    except (OSError, ValueError) as exc:
                        failure_reasons.append(type(exc).__name__)
                        continue
                    version = detect_spine_version(skeleton)
                    if version.startswith(("3.8", "4.2")):
                        selected = (bundle_dir, version)
                        break
                    failure_reasons.append(f"spine_{version or 'unknown'}")
                if selected is not None:
                    break
        if selected is None:
            excluded.append({
                "identifier": identifier,
                "name": name,
                "spine": str(character.get("spine") or ""),
                "face_count": len(face_ids),
                "reason": "missing_bundle" if failure_reasons else "unsupported_spine_version",
                "bundle_roots_checked": [str(root) for root in roots],
                "bundle_errors": failure_reasons,
            })
            continue
        bundle_dir, version = selected
        key = str(bundle_dir.resolve()).casefold()
        binding = IdentityBinding(
            identifier=identifier,
            name=name,
            club=str(character.get("club") or "").strip(),
            spine_signature=str(
                (inventory_row or {}).get("spine_signature")
                or character.get("spine_signature") or ""
            ).strip(),
            outfit_key=str(
                character.get("outfit_key")
                or (inventory_row or {}).get("outfit_key")
                or bundle_dir.name
            ).strip(),
        )
        if key in target_index_by_path:
            target_index = target_index_by_path[key]
            existing_target = targets[target_index]
            bindings = existing_target.bindings
            if binding.key() not in {item.key() for item in bindings}:
                bindings = (*bindings, binding)
            targets[target_index] = replace(
                existing_target,
                face_ids=tuple(sorted(set(existing_target.face_ids) | set(face_ids))),
                identity_bindings=bindings,
            )
            continue
        seen_paths.add(key)
        target_index_by_path[key] = len(targets)
        targets.append(FaceBatchTarget(
            identifier=binding.identifier,
            name=binding.name,
            club=binding.club,
            source_dir=str(bundle_dir.resolve()),
            spine_signature=binding.spine_signature,
            outfit_key=binding.outfit_key,
            spine_version=version,
            face_ids=face_ids,
            source_kind=str((inventory_row or {}).get("source_kind") or "extra_pack"),
            source_root=str((inventory_row or {}).get("source_root") or ""),
            source_evidence=(inventory_row or {}).get("evidence") or {},
            identity_bindings=(binding,),
        ))
    for row in (inventory or {}).get("records") or []:
        if not isinstance(row, dict) or row.get("status") != "ready":
            continue
        source_dir = str(Path(str(row.get("source_dir") or "")).resolve())
        key = source_dir.casefold()
        if key in matched_inventory_dirs or key in seen_paths:
            continue
        face_ids = tuple(str(value) for value in row.get("face_ids") or [])
        if len(face_ids) < max(1, int(min_faces)) or not include_unmapped:
            excluded.append({
                "identifier": "",
                "name": str(row.get("outfit_key") or ""),
                "spine": str(row.get("spine") or ""),
                "face_count": len(face_ids),
                "reason": "too_few_faces" if len(face_ids) < min_faces else "unmapped_identity",
                "identity_status": "pending",
                "source_kind": str(row.get("source_kind") or ""),
                "source_dir": source_dir,
            })
            continue
        seen_paths.add(key)
        binding = IdentityBinding(
            identifier="",
            name=str(row.get("outfit_key") or Path(source_dir).name),
            outfit_key=str(row.get("outfit_key") or Path(source_dir).name),
            spine_signature=str(row.get("spine_signature") or ""),
            identity_status="pending",
        )
        target_index_by_path[key] = len(targets)
        targets.append(FaceBatchTarget(
            identifier="",
            name=str(row.get("outfit_key") or Path(source_dir).name),
            club="",
            source_dir=source_dir,
            spine_signature=str(row.get("spine_signature") or ""),
            outfit_key=str(row.get("outfit_key") or Path(source_dir).name),
            spine_version=str(row.get("spine_version") or ""),
            face_ids=face_ids,
            source_kind=str(row.get("source_kind") or ""),
            source_root=str(row.get("source_root") or ""),
            identity_status="pending",
            source_evidence=row.get("evidence") or {},
            identity_bindings=(binding,),
        ))
    return sorted(targets, key=lambda item: (item.name, item.outfit_key)), excluded


def _semantic_hints(index: dict) -> dict[tuple[str, str], dict[str, dict]]:
    hints: dict[tuple[str, str], dict[str, dict]] = {}
    for character in index.get("characters") or []:
        if not isinstance(character, dict):
            continue
        key = (
            str(character.get("identifier") or ""),
            str(character.get("outfit_key") or ""),
        )
        by_face: dict[str, dict] = {}
        for item in character.get("faces") or []:
            if not isinstance(item, dict):
                continue
            face_id = str(item.get("id") or "")
            if not _FACE_ID_RE.fullmatch(face_id):
                continue
            labels = by_face.setdefault(face_id, {"labels": []})["labels"]
            for value in (item.get("label"), item.get("raw")):
                value = str(value or "").strip()
                if value and value != face_id and value not in labels:
                    labels.append(value)
        hints[key] = by_face
    return hints


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Windows file scanners and report viewers can temporarily hold the target
    # open. A per-process staging file plus a short retry keeps a completed
    # character from aborting an otherwise resumable multi-process run.
    pending = path.with_name(f"{path.name}.{os.getpid()}.pending")
    pending.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    for attempt in range(8):
        try:
            pending.replace(path)
            return
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(0.15 * (attempt + 1))


def select_target_shard(
    targets: Iterable[FaceBatchTarget],
    *,
    shard_count: int,
    shard_index: int,
) -> list[FaceBatchTarget]:
    if shard_count < 1:
        raise ValueError("shard_count must be at least 1")
    if not 0 <= shard_index < shard_count:
        raise ValueError("shard_index must be in [0, shard_count)")
    return [
        item for index, item in enumerate(targets)
        if index % shard_count == shard_index
    ]


def _plan_payload(
    targets: Iterable[FaceBatchTarget],
    excluded: list[dict],
    inventory: dict | None = None,
) -> dict:
    rows = list(targets)
    source_targets = Counter(item.source_kind for item in rows)
    source_faces = Counter()
    for item in rows:
        source_faces[item.source_kind] += item.face_count
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inventory_status": (inventory or {}).get("status", "not_loaded"),
        "inventory_candidate_count": (inventory or {}).get("candidate_count", 0),
        "inventory_ready_count": (inventory or {}).get("ready_count", 0),
        "inventory_failed_count": (inventory or {}).get("failed_count", 0),
        "target_count": len(rows),
        "identity_binding_count": sum(len(item.bindings) for item in rows),
        "shared_skeleton_count": sum(len(item.bindings) > 1 for item in rows),
        "shared_identity_binding_count": sum(
            max(0, len(item.bindings) - 1) for item in rows
        ),
        "face_count": sum(item.face_count for item in rows),
        "pending_identity_count": sum(
            item.identity_status == "pending" for item in rows
        ),
        "sources": {
            key: {
                "target_count": source_targets[key],
                "face_count": source_faces[key],
            }
            for key in sorted(source_targets)
        },
        "targets": [item.to_json() for item in rows],
        "excluded": excluded,
    }


def _existing_ids(con, target: FaceBatchTarget, model: str) -> set[str]:
    existing_by_binding = []
    for binding in target.bindings:
        rows = con.execute(
            """
            SELECT face_id FROM face_visual_label
            WHERE ident=? AND spine_signature=? AND outfit_key=? AND model=?
            """,
            (
                binding.identifier,
                binding.spine_signature,
                binding.outfit_key,
                model,
            ),
        ).fetchall()
        existing_by_binding.append({str(row["face_id"]) for row in rows})
    return set.intersection(*existing_by_binding) if existing_by_binding else set()


def _existing_ids_for_binding(con, binding: IdentityBinding, model: str) -> set[str]:
    rows = con.execute(
        """
        SELECT face_id FROM face_visual_label
        WHERE ident=? AND spine_signature=? AND outfit_key=? AND model=?
        """,
        (
            binding.identifier, binding.spine_signature,
            binding.outfit_key, str(model),
        ),
    ).fetchall()
    return {str(row["face_id"]) for row in rows}


def persist_target_visual_face_labels(
    con,
    *,
    target: FaceBatchTarget,
    model: str,
    labels: Iterable[dict],
) -> dict:
    """Persist a result only when one skeleton has one semantic identity."""
    records = list(labels)
    if len(target.bindings) != 1:
        raise ValueError(
            "shared skeleton semantics must be labeled and persisted per identity"
        )
    binding_results = []
    for binding in target.bindings:
        result = persist_visual_face_labels(
            con,
            ident=binding.identifier,
            spine_signature=binding.spine_signature,
            outfit_key=binding.outfit_key,
            model=model,
            labels=records,
        )
        binding_results.append({**asdict(binding), **result})
    failures = sum(bool(item.get("failed")) for item in records)
    return {
        "saved_count": len(records) - failures,
        "failed_count": failures,
        "identity_rows_saved": sum(
            item["saved_count"] for item in binding_results
        ),
        "binding_results": binding_results,
    }


class FreshSpineRenderer:
    """Open an isolated Chromium/WebGL session for each character bundle.

    Spine's web runtime retains GPU resources while a page is alive.  A full
    catalog contains unrelated atlas layouts, so a long-lived page eventually
    becomes invalid on some Chromium/SwiftShader combinations.  The face
    images are cached on disk, making per-bundle isolation a small cost for a
    resumable batch and preventing one bad context from poisoning later work.
    """

    def __init__(self, *, canvas_size: int) -> None:
        self.canvas_size = canvas_size

    def __enter__(self) -> "FreshSpineRenderer":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def render(self, *args, **kwargs):
        # Retry once only for the local renderer/process failure observed in
        # bulk work. Asset validation errors must still surface immediately.
        for attempt in range(2):
            try:
                skeleton, _, _ = _bundle_files(args[0])
                version = detect_spine_version(skeleton)
                with SpineWebRenderer(
                    canvas_size=self.canvas_size,
                    spine_version=version,
                ) as renderer:
                    return renderer.render(*args, **kwargs)
            except OSError:
                if attempt:
                    raise


def _label_batch_activation_ready(report: Mapping, target_count: int) -> bool:
    completed = list(report.get("completed") or [])
    return bool(target_count) and not report.get("failed") and all(
        entry.get("status") in {"complete", "cached_labels"}
        and not entry.get("missing_face_ids")
        and not int(entry.get("failed_count") or 0)
        for entry in completed
    ) and len(completed) == target_count


def run_batch(args, targets: list[FaceBatchTarget], index: dict, report_path: Path) -> int:
    provider = _batch_provider(args)
    # The two-stage observation/backend pipeline has separate provenance from
    # old one-stage labels.  An explicit --label-version still wins, while a
    # normal run automatically starts/resumes the v4 lane instead of silently
    # reusing stale semantic-only rows.
    label_version = str(
        args.label_version or f"{provider.model}:semantic-profile-v4"
    ).strip()
    # Some OpenAI-compatible Gemini gateways accept json_schema but silently
    # ignore it (for example returning one face object instead of {items:[...]}).
    # The provider's JSON-object compatibility mode repeats the schema in the
    # prompt and has proved reliable on the configured gateway.
    if hasattr(provider, "_strict_response_format_unavailable") or provider.name == "openai":
        provider._strict_response_format_unavailable = True
    con = assetdb.connect(args.db)
    active_model_before = assetdb.active_face_label_model(con)
    hints = _semantic_hints(index)
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "provider_model": provider.model,
        "label_version": label_version,
        "activation_requested": bool(args.activate_on_complete),
        "active_model_before": active_model_before,
        "target_count": len(targets),
        "identity_binding_count": sum(len(item.bindings) for item in targets),
        "face_count": sum(item.face_count for item in targets),
        "completed": [],
        "failed": [],
    }
    print(f"模型：{provider.name} / {provider.model}；标注版本：{label_version}")
    print(f"准备处理 {len(targets)} 套骨骼、{report['face_count']} 个表情。")
    with FreshSpineRenderer(canvas_size=args.canvas_size) as renderer:
        for target_index, target in enumerate(targets, start=1):
            existing = _existing_ids(con, target, label_version)
            if not args.force_vision and set(target.face_ids).issubset(existing):
                print(f"[{target_index}/{len(targets)}] 跳过 {target.name}：已有完整标注")
                report["completed"].append({
                    **target.to_json(), "status": "cached_labels", "labeled_count": len(existing)
                })
                _write_json(report_path, report)
                continue
            started = time.monotonic()
            print(
                f"[{target_index}/{len(targets)}] {target.name} / {target.outfit_key} "
                f"({target.face_count} 个表情)"
            )
            try:
                render_report = renderer.render(
                    target.source_dir,
                    face_ids=target.face_ids,
                    cache_root=args.cache_root,
                    force=args.force_render,
                    progress=lambda face_id, current, total: print(
                        f"  渲染 {current}/{total}  {face_id}", end="\r", flush=True
                    ),
                )
                print(" " * 50, end="\r")
                if render_report.missing_face_ids:
                    print("  跳过骨骼中不存在的编号：" + "、".join(render_report.missing_face_ids))
                binding_results = []
                for binding_index, binding in enumerate(target.bindings, start=1):
                    binding_existing = _existing_ids_for_binding(
                        con, binding, label_version
                    )
                    faces_to_label = render_report.faces
                    if not args.force_vision:
                        faces_to_label = tuple(
                            face for face in render_report.faces
                            if face.face_id not in binding_existing
                        )
                    if not faces_to_label:
                        binding_results.append({
                            **asdict(binding), "status": "cached_labels",
                            "saved_count": 0, "failed_count": 0, "failures": [],
                        })
                        continue
                    print(
                        f"  身份 {binding_index}/{len(target.bindings)}  "
                        f"{binding.name or binding.identifier}"
                    )
                    face_ids = [face.face_id for face in faces_to_label]
                    official_usage = assetdb.official_face_usage(
                        con,
                        ident=binding.identifier,
                        face_ids=face_ids,
                        spine_signature=binding.spine_signature,
                        outfit_key=binding.outfit_key,
                        representative_limit=3,
                    )
                    official_profiles = assetdb.official_face_usage_profiles(
                        con,
                        ident=binding.identifier,
                        face_ids=face_ids,
                        spine_signature=binding.spine_signature,
                        outfit_key=binding.outfit_key,
                    )
                    labels = label_face_images(
                        provider,
                        faces_to_label,
                        batch_size=args.batch_size,
                        batch_workers=args.api_workers,
                        confidence_threshold=args.confidence_threshold,
                        semantic_hints=hints.get(
                            (binding.identifier, binding.outfit_key), {}
                        ),
                        official_usage=official_usage,
                        official_profiles=official_profiles,
                        comparison_memory=True,
                        require_visual_facts=True,
                        require_semantic_profile=True,
                        require_semantic_modes=True,
                        diagnostic_errors=True,
                        progress=lambda done, total, batches, reviewed: print(
                            f"  识别 {done}/{total}，批次 {batches}，复核 {reviewed}",
                            end="\r", flush=True,
                        ),
                    )
                    result = persist_visual_face_labels(
                        con,
                        ident=binding.identifier,
                        spine_signature=binding.spine_signature,
                        outfit_key=binding.outfit_key,
                        model=label_version,
                        labels=labels,
                    )
                    binding_results.append({
                        **asdict(binding), "status": (
                            "complete" if not result.get("failed_count") else "partial"
                        ), **result,
                    })
                saved = {
                    "saved_count": sum(
                        int(item.get("saved_count") or 0) for item in binding_results
                    ),
                    "failed_count": sum(
                        int(item.get("failed_count") or 0) for item in binding_results
                    ),
                    "identity_rows_saved": sum(
                        int(item.get("saved_count") or 0) for item in binding_results
                    ),
                    "binding_results": binding_results,
                }
                con.commit()
                elapsed = round(time.monotonic() - started, 2)
                entry = {
                    **target.to_json(),
                    "status": "complete" if not saved.get("failed_count") else "partial",
                    "render_cached": render_report.cached,
                    "rendered_count": len(render_report.faces),
                    "missing_face_ids": list(render_report.missing_face_ids),
                    "elapsed_seconds": elapsed,
                    **saved,
                }
                report["completed"].append(entry)
                print(
                    f"  完成：写入 {saved['saved_count']}，失败 {saved['failed_count']}，"
                    f"{elapsed:.1f} 秒" + " " * 12
                )
            except KeyboardInterrupt:
                report["interrupted_at"] = datetime.now(timezone.utc).isoformat()
                _write_json(report_path, report)
                raise
            except Exception as exc:
                con.rollback()
                report["failed"].append({
                    **target.to_json(),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                })
                print(f"  失败（已保留此前结果）：{type(exc).__name__}: {exc}")
            _write_json(report_path, report)
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["provider_report"] = provider.report()
    activation_ready = _label_batch_activation_ready(report, len(targets))
    if args.activate_on_complete and activation_ready:
        assetdb.set_active_face_label_model(con, label_version)
        report["active_model_after"] = label_version
        report["activated"] = True
    else:
        report["active_model_after"] = assetdb.active_face_label_model(con)
        report["activated"] = False
        if args.activate_on_complete and not activation_ready:
            report["activation_blocked_reason"] = "batch_incomplete_or_needs_review"
    _write_json(report_path, report)
    print(provider.report())
    print(f"报告：{report_path}")
    return 1 if report["failed"] else 0


def _load_inventory(path: str | Path) -> dict | None:
    inventory_path = Path(path)
    if not inventory_path.is_file():
        return None
    try:
        value = json.loads(inventory_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _official_paths(args, config: dict) -> tuple[Path, Path]:
    catalog_value = args.official_catalog or config.get("aa_catalog")
    if not catalog_value:
        executable = config.get("aa_executable")
        if executable:
            catalog_value = (
                Path(executable).resolve().parent
                / "AzureArchive_Data" / "StreamingAssets" / "aa" / "catalog.json"
            )
    cache_value = args.official_cache or config.get("aa_cache")
    return Path(catalog_value or "").resolve(), Path(cache_value or "").resolve()


def _prepare_inventory(args, config: dict, override_roots: list[Path]) -> dict:
    catalog_path, official_cache = _official_paths(args, config)
    if not catalog_path.is_file():
        raise FileNotFoundError(f"AA official catalog not found: {catalog_path}")
    if not official_cache.is_dir():
        raise FileNotFoundError(f"AA official resource cache not found: {official_cache}")
    official_root = Path(args.official_extract_root).resolve()
    print("正在只读导出官方基础 Spine 缓存……")
    materialized = materialize_official_spines(
        catalog_path,
        official_cache,
        official_root,
        force=args.force_prepare,
        progress=lambda current, total, name: print(
            f"  基础包 {current}/{total}  {name}", end="\r", flush=True
        ),
    )
    print(" " * 80, end="\r")
    roots = [("official_base", official_root)]
    roots.extend(("extra_pack", root) for root in override_roots)
    candidates, discovery_failures = discover_spine_inventory_candidates(
        roots,
        isolation_root=HERE / "out" / "spine-inventory-isolated",
    )
    print(f"正在读取 {len(candidates)} 套骨骼的真实动画清单……")
    inventory = build_spine_animation_inventory(
        candidates,
        args.inventory,
        force=args.force_prepare,
        progress=lambda current, total, name: print(
            f"  动画库存 {current}/{total}  {name}", end="\r", flush=True
        ),
    )
    print(" " * 80, end="\r")
    preparation_failures = [
        {"source_kind": "official_base", **failure}
        for failure in materialized.get("failures") or []
    ]
    preparation_failures.extend(discovery_failures)
    if preparation_failures:
        inventory["failed_count"] = int(inventory.get("failed_count") or 0) + len(
            preparation_failures
        )
        inventory["failures"] = [
            *(inventory.get("failures") or []), *preparation_failures
        ]
        inventory["status"] = "partial"
        _write_json(Path(args.inventory), inventory)
    _write_json(Path(args.output).resolve() / "materialize-report.json", materialized)
    return inventory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="批量渲染并标注 AA 官方角色表情")
    parser.add_argument(
        "mode", choices=("prepare", "plan", "run"), nargs="?", default="plan"
    )
    parser.add_argument("--config", default=str(HERE / "aa_config.json"))
    parser.add_argument("--index", default=str(HERE / "aa_resources.json"))
    parser.add_argument("--db", default=str(HERE / "aa_assets.db"))
    parser.add_argument("--llm", default=str(HERE / "llm.json"))
    parser.add_argument(
        "--model-profiles", default=str(HERE / "llm_profiles.json"),
        help="Model workbench state; secrets remain in Windows Credential Manager",
    )
    parser.add_argument(
        "--model-profile-id",
        help="Use one saved model-workbench entry instead of llm.json",
    )
    parser.add_argument("--provider")
    parser.add_argument("--model", help="Vision model ID used for this batch only")
    parser.add_argument(
        "--label-version",
        help="Independent provenance version; use a new value when re-labeling",
    )
    parser.add_argument(
        "--activate-on-complete", action="store_true",
        help="Activate this label version only after every selected target completes cleanly",
    )
    parser.add_argument(
        "--overrides", action="append",
        help="可重复指定基础包/额外包的 overrides 根目录；按顺序优先使用",
    )
    parser.add_argument("--min-faces", type=int, default=4)
    parser.add_argument("--include-supporting", action="store_true")
    parser.add_argument("--exclude-unmapped", action="store_true")
    parser.add_argument("--ident", action="append", default=[])
    parser.add_argument("--outfit", action="append", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--subshard-count", type=int, default=1)
    parser.add_argument("--subshard-index", type=int, default=0)
    parser.add_argument("--force-vision", action="store_true")
    parser.add_argument("--force-render", action="store_true")
    parser.add_argument("--force-prepare", action="store_true")
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--api-workers", type=int, default=2)
    parser.add_argument("--confidence-threshold", type=float, default=0.75)
    parser.add_argument("--canvas-size", type=int, default=2048)
    parser.add_argument("--cache-root", default=str(HERE / "out" / "spine-face-batch-cache"))
    parser.add_argument("--output", default=str(HERE / "out" / "spine-face-batch"))
    parser.add_argument("--official-catalog")
    parser.add_argument("--official-cache")
    parser.add_argument(
        "--official-extract-root",
        default=str(HERE / "out" / "official-spine-cache"),
    )
    parser.add_argument(
        "--inventory",
        default=str(HERE / "out" / "spine-face-inventory.json"),
    )
    args = parser.parse_args(argv)
    if args.shard_count < 1:
        parser.error("--shard-count must be at least 1")
    if not 0 <= args.shard_index < args.shard_count:
        parser.error("--shard-index must be in [0, --shard-count)")
    if args.subshard_count < 1:
        parser.error("--subshard-count must be at least 1")
    if not 0 <= args.subshard_index < args.subshard_count:
        parser.error("--subshard-index must be in [0, --subshard-count)")

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    index = json.loads(Path(args.index).read_text(encoding="utf-8"))
    configured_roots = config.get("aa_override_roots") or []
    if args.overrides:
        override_roots = [Path(value) for value in args.overrides]
    elif configured_roots:
        override_roots = [Path(value) for value in configured_roots]
    else:
        override_roots = [Path(config["aa_data"]) / "overrides"]
    inventory = (
        _prepare_inventory(args, config, override_roots)
        if args.mode == "prepare"
        else _load_inventory(args.inventory)
    )
    targets, excluded = discover_main_character_targets(
        index,
        overrides_root=override_roots,
        min_faces=args.min_faces,
        include_supporting=args.include_supporting,
        include_unmapped=not args.exclude_unmapped,
        inventory=inventory,
    )
    if args.ident:
        selected = set(args.ident)
        selected_targets = []
        for item in targets:
            bindings = tuple(
                binding for binding in item.bindings
                if binding.identifier in selected
            )
            if not bindings:
                continue
            primary = bindings[0]
            selected_targets.append(replace(
                item,
                identifier=primary.identifier,
                name=primary.name,
                club=primary.club,
                outfit_key=primary.outfit_key,
                spine_signature=primary.spine_signature,
                identity_bindings=bindings,
            ))
        targets = selected_targets
    if args.outfit:
        selected_outfits = {str(value).casefold() for value in args.outfit}
        targets = [
            item for item in targets
            if any(
                binding.outfit_key.casefold() in selected_outfits
                for binding in item.bindings
            )
        ]
    targets = select_target_shard(
        targets,
        shard_count=args.shard_count,
        shard_index=args.shard_index,
    )
    targets = select_target_shard(
        targets,
        shard_count=args.subshard_count,
        shard_index=args.subshard_index,
    )
    if args.limit is not None:
        targets = targets[: max(0, args.limit)]

    output = Path(args.output).resolve()
    plan_path = output / "plan.json"
    report_path = output / "report.json"
    plan_payload = _plan_payload(targets, excluded, inventory)
    plan_payload["selection"] = {
        "shard_count": args.shard_count,
        "shard_index": args.shard_index,
        "subshard_count": args.subshard_count,
        "subshard_index": args.subshard_index,
    }
    _write_json(plan_path, plan_payload)
    print(
        f"筛出 {len(targets)} 套正常主要角色骨骼，共 "
        f"{sum(item.face_count for item in targets)} 个表情。"
    )
    print(f"计划：{plan_path}")
    if args.mode in {"prepare", "plan"}:
        print("计划已生成；使用 run 子命令开始渲染和模型标注。")
        return 0
    return run_batch(args, targets, index, report_path)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n已中断；已完成角色仍保留，下次运行会断点续跑。")
        raise SystemExit(130)
