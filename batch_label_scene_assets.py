# -*- coding: utf-8 -*-
"""Inventory and resumably label official and extra-pack AA scene images."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter, defaultdict
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

import assetdb
from PIL import Image, ImageOps
from llm import make_provider
from official_catalog import catalog_bundle_locations
from official_preview_index import _default_bundle_loader
from scene_asset_labeler import (
    SceneBatchValidationError,
    SceneVisionInput,
    label_scene_images,
    persist_scene_label,
)


HERE = Path(__file__).resolve().parent
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _item_id(channel: str, key: str, digest: str) -> str:
    value = f"{channel}\0{key.casefold()}\0{digest}".encode("utf-8")
    return "S" + hashlib.sha256(value).hexdigest()[:15]


def _reference_map(path: str | Path | None) -> tuple[dict[str, str], dict[str, str], dict]:
    if not path:
        return {}, {}, {"total": 0, "usable": 0, "errors": 0}
    source = json.loads(Path(path).read_text(encoding="utf-8"))
    by_name = {}
    by_stem = {}
    errors = 0
    for filename, value in source.items():
        description = str((value or {}).get("desc") or "").strip()
        if not description or description.startswith("ERR:"):
            errors += 1
            continue
        by_name[str(filename).casefold()] = description
        by_stem[Path(str(filename)).stem.casefold()] = description
    return by_name, by_stem, {
        "total": len(source), "usable": len(by_name), "errors": errors,
    }


def _reference_description(
    filename: str, asset_key: str, by_name: dict[str, str], by_stem: dict[str, str]
) -> str:
    return by_name.get(filename.casefold()) or by_stem.get(asset_key.casefold()) or ""


def materialize_official_popup_previews(
    catalog_path: str | Path,
    cache_root: str | Path,
    output_root: str | Path,
) -> Path:
    """Read AA's popup bundle and cache bounded previews outside AA."""
    output = Path(output_root).resolve()
    manifest_path = output / "manifest.json"
    locations = catalog_bundle_locations(
        catalog_path,
        cache_root,
        internal_predicate=lambda value: (
            "/uis/03_scenario/04_scenarioimage/" in value.casefold()
        ),
    )
    source_fingerprint = hashlib.sha256(
        "\n".join(
            f"{row.bundle_name}:{row.content_hash}" for row in locations
        ).encode("utf-8")
    ).hexdigest()
    try:
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        existing = {}
    if (
        existing.get("source_fingerprint") == source_fingerprint
        and all(
            (output / str(row.get("path") or "")).is_file()
            for row in existing.get("records") or []
        )
    ):
        return manifest_path

    records = []
    failures = []
    images_root = output / "popups"
    images_root.mkdir(parents=True, exist_ok=True)
    for location in locations:
        if location.data_path is None:
            failures.append({
                "bundle_name": location.bundle_name,
                "reason": "bundle_not_cached",
            })
            continue
        try:
            images = _default_bundle_loader(location.data_path)
            for source in images:
                key = str(source.name or "").strip()
                if not key:
                    continue
                token = hashlib.sha256(
                    f"{location.bundle_name}\0{location.content_hash}\0{key}".encode("utf-8")
                ).hexdigest()
                path = images_root / f"{token}.webp"
                image = ImageOps.contain(
                    source.image.convert("RGB"), (1280, 1280),
                    Image.Resampling.LANCZOS,
                )
                image.save(path, format="WEBP", quality=88, method=4)
                records.append({
                    "kind": "popup",
                    "key": key,
                    "path": path.relative_to(output).as_posix(),
                    "bundle_name": location.bundle_name,
                    "content_hash": location.content_hash,
                })
        except Exception as exc:
            failures.append({
                "bundle_name": location.bundle_name,
                "reason": f"{type(exc).__name__}: {exc}",
            })
    _write_json(manifest_path, {
        "schema_version": 1,
        "source_fingerprint": source_fingerprint,
        "records": records,
        "failures": failures,
    })
    return manifest_path


def discover_scene_targets(
    *,
    official_manifest: str | Path | None,
    override_roots: list[str | Path],
    official_popup_manifest: str | Path | None = None,
    reference_path: str | Path | None = None,
) -> tuple[list[SceneVisionInput], dict]:
    by_name, by_stem, reference_stats = _reference_map(reference_path)
    physical_files = 0
    missing_files = []
    candidates: list[SceneVisionInput] = []

    if official_manifest:
        manifest_path = Path(official_manifest).resolve()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        preview_root = manifest_path.parent
        for row in manifest.get("records") or []:
            if row.get("kind") != "background":
                continue
            path = (preview_root / str(row.get("path") or "")).resolve()
            key = str(row.get("key") or "").strip()
            if not key or not path.is_file():
                missing_files.append({"source_kind": "official_base", "asset_key": key})
                continue
            physical_files += 1
            digest = _sha256(path)
            original = key
            candidates.append(SceneVisionInput(
                item_id=_item_id("background", key, digest),
                asset_key=key,
                resource_channel="background",
                image_path=path,
                source_kind="official_base",
                source_category="AA/official_background",
                content_sha256=digest,
                original_filename=original,
                reference_description=_reference_description(
                    original, key, by_name, by_stem
                ),
            ))

    if official_popup_manifest:
        manifest_path = Path(official_popup_manifest).resolve()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        preview_root = manifest_path.parent
        for row in manifest.get("records") or []:
            if row.get("kind") != "popup":
                continue
            path = (preview_root / str(row.get("path") or "")).resolve()
            key = str(row.get("key") or "").strip()
            if not key or not path.is_file():
                missing_files.append({"source_kind": "official_base", "asset_key": key})
                continue
            physical_files += 1
            digest = _sha256(path)
            candidates.append(SceneVisionInput(
                item_id=_item_id("popup", key, digest),
                asset_key=key,
                resource_channel="popup",
                image_path=path,
                source_kind="official_base",
                source_category="AA/official_popup",
                content_sha256=digest,
                original_filename=key,
                reference_description=_reference_description(
                    key, key, by_name, by_stem
                ),
            ))

    for root_value in override_roots:
        root = Path(root_value).resolve()
        for folder, channel in (("bgs", "background"), ("popups", "popup")):
            source_root = root / folder
            if not source_root.is_dir():
                continue
            for path in sorted(source_root.rglob("*")):
                if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
                    continue
                physical_files += 1
                digest = _sha256(path)
                key = path.stem
                relative_parent = path.parent.relative_to(source_root).as_posix()
                if relative_parent == ".":
                    relative_parent = "未分类"
                candidates.append(SceneVisionInput(
                    item_id=_item_id(channel, key, digest),
                    asset_key=key,
                    resource_channel=channel,
                    image_path=path,
                    source_kind="extra_pack",
                    source_category=f"AA/{folder}/{relative_parent}",
                    content_sha256=digest,
                    original_filename=path.name,
                    reference_description=_reference_description(
                        path.name, key, by_name, by_stem
                    ),
                ))

    priority = {"extra_pack": 0, "official_base": 1}

    def source_rank(item: SceneVisionInput) -> tuple[int, int]:
        return (
            priority.get(item.source_kind, 9),
            1 if item.source_category.endswith("/未分类") else 0,
        )

    deduplicated = {}
    duplicate_copies = []
    for item in candidates:
        identity = (
            item.resource_channel, item.asset_key.casefold(), item.content_sha256
        )
        existing = deduplicated.get(identity)
        if existing is None or source_rank(item) < source_rank(existing):
            if existing is not None:
                duplicate_copies.append(asdict(existing))
            deduplicated[identity] = item
        else:
            duplicate_copies.append(asdict(item))
    targets = sorted(
        deduplicated.values(),
        key=lambda item: (
            item.resource_channel, item.asset_key.casefold(),
            priority.get(item.source_kind, 9), item.content_sha256,
        ),
    )

    variants = defaultdict(set)
    for item in targets:
        variants[(item.resource_channel, item.asset_key.casefold())].add(item.content_sha256)
    conflicts = [
        {"resource_channel": channel, "asset_key_normalized": key, "variants": len(digests)}
        for (channel, key), digests in variants.items() if len(digests) > 1
    ]
    stats = {
        "physical_files": physical_files,
        "target_count": len(targets),
        "duplicate_copy_count": len(duplicate_copies),
        "identity_conflict_count": len(conflicts),
        "missing_file_count": len(missing_files),
        "by_channel": dict(Counter(item.resource_channel for item in targets)),
        "by_source_kind": dict(Counter(item.source_kind for item in targets)),
        "source_categories": dict(Counter(item.source_category for item in targets)),
        "reference": {
            **reference_stats,
            "matched_targets": sum(bool(item.reference_description) for item in targets),
        },
        "identity_conflicts": conflicts,
        "missing_files": missing_files,
    }
    return targets, stats


def select_target_shard(
    targets: list[SceneVisionInput], *, shard_count: int, shard_index: int
) -> list[SceneVisionInput]:
    return [
        target for index, target in enumerate(targets)
        if index % shard_count == shard_index
    ]


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _already_labeled(con, target: SceneVisionInput, model: str) -> bool:
    row = con.execute(
        """
        SELECT status FROM scene_visual_label
        WHERE resource_channel=? AND asset_key=? AND content_sha256=? AND model=?
        """,
        (
            target.resource_channel, target.asset_key,
            target.content_sha256, model,
        ),
    ).fetchone()
    return bool(row and row["status"] in {"ready", "candidate", "manual_locked"})


def _report(con, targets: list[SceneVisionInput], model: str, failures: list[dict]) -> dict:
    keys = {
        (target.resource_channel, target.asset_key, target.content_sha256)
        for target in targets
    }
    rows = con.execute(
        """
        SELECT resource_channel,asset_key,content_sha256,source_kind,visual_kind,
               status,confidence,label_json
        FROM scene_visual_label WHERE model=?
        """,
        (model,),
    ).fetchall()
    selected = [
        row for row in rows
        if (row["resource_channel"], row["asset_key"], row["content_sha256"]) in keys
    ]
    invalid = []
    main_categories = Counter()
    channel_kinds = Counter()
    for row in selected:
        channel_kinds[f"{row['resource_channel']}:{row['visual_kind']}"] += 1
        try:
            labels = json.loads(row["label_json"] or "{}")
        except (TypeError, ValueError):
            invalid.append({"asset_key": row["asset_key"], "reason": "invalid_label_json"})
            continue
        category = str(labels.get("main_category") or "")
        if category:
            main_categories[category] += 1
        if row["status"] == "ready" and category == "unknown":
            invalid.append({"asset_key": row["asset_key"], "reason": "unknown_main_category"})
        if row["status"] == "ready" and labels.get("setting_scope") == "unknown":
            invalid.append({"asset_key": row["asset_key"], "reason": "unknown_setting_scope"})
        if row["status"] == "ready" and labels.get("reuse_scope") == "unknown":
            invalid.append({"asset_key": row["asset_key"], "reason": "unknown_reuse_scope"})
        subcategory = str(labels.get("subcategory") or "")
        if row["status"] == "ready" and (
            not str(labels.get("label") or "").strip()
            or not str(labels.get("description") or "").strip()
        ):
            invalid.append({"asset_key": row["asset_key"], "reason": "empty_core_semantics"})
        if subcategory and not any("\u4e00" <= char <= "\u9fff" for char in subcategory):
            invalid.append({"asset_key": row["asset_key"], "reason": "non_chinese_subcategory"})
        if row["visual_kind"] != "background" and labels.get("dialogue_suitable") is True:
            invalid.append({"asset_key": row["asset_key"], "reason": "cg_dialogue_suitable"})
    recorded = len(selected)
    completed = sum(row["status"] in {"ready", "candidate", "manual_locked"} for row in selected)
    return {
        "model": model,
        "expected": len(targets),
        "recorded": recorded,
        "completed": completed,
        "remaining": len(targets) - recorded,
        "completion_ratio": round(completed / len(targets), 6) if targets else 1.0,
        "by_status": dict(Counter(row["status"] for row in selected)),
        "by_visual_kind": dict(Counter(row["visual_kind"] for row in selected)),
        "by_channel_visual_kind": dict(channel_kinds),
        "by_source_kind": dict(Counter(row["source_kind"] for row in selected)),
        "by_main_category": dict(main_categories),
        "low_confidence": sum(float(row["confidence"] or 0) < 0.75 for row in selected),
        "invalid_semantic_count": len(invalid),
        "invalid_semantics": invalid,
        "failure_count": len(failures),
        "failures": failures,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _label_status(labels: dict, confidence_threshold: float) -> str:
    if (
        float(labels.get("confidence") or 0) >= confidence_threshold
        and labels.get("visual_kind") != "unknown"
        and labels.get("main_category") != "unknown"
        and labels.get("setting_scope") != "unknown"
        and labels.get("reuse_scope") != "unknown"
        and (
            labels.get("setting_scope") not in {"specific", "mixed"}
            or float(labels.get("affiliation_confidence") or 0) >= 0.65
        )
    ):
        return "ready"
    return "candidate"


def run_batch(args, targets: list[SceneVisionInput], report_path: Path) -> int:
    provider = make_provider(args.llm, args.provider)
    if args.model:
        provider.model = str(args.model)
    if provider.name == "openai":
        # Several OpenAI-compatible Gemini gateways accept json_schema but
        # silently return an incompatible top-level shape. The compatible
        # path still validates locally against the same strict schema.
        provider._strict_response_format_unavailable = True
    model = str(args.label_version or provider.model).strip()
    con = assetdb.connect(args.db)
    assetdb.set_active_scene_label_model(con, model)
    pending = [
        target for target in targets
        if args.force or not _already_labeled(con, target, model)
    ]
    failures = []
    print(f"模型：{provider.name} / {provider.model}；标注版本：{model}")
    print(f"目标 {len(targets)} 项，本次待处理 {len(pending)} 项，每批 {args.batch_size} 张。")
    for offset in range(0, len(pending), args.batch_size):
        batch = pending[offset:offset + args.batch_size]
        try:
            labels = label_scene_images(provider, batch, retries=args.retries)
        except SceneBatchValidationError as exc:
            failure = {
                "item_ids": [target.item_id for target in batch],
                "asset_keys": [target.asset_key for target in batch],
                "error": str(exc),
            }
            failures.append(failure)
            for target in batch:
                persist_scene_label(
                    con, target=target, model=model,
                    labels={"visual_kind": "unknown"}, status="failed",
                    evidence={"batch_error": str(exc)},
                )
        else:
            for target, label in zip(batch, labels):
                final = label
                if float(label.get("confidence") or 0) < args.confidence_threshold:
                    try:
                        final = label_scene_images(
                            provider, [replace(target, item_id="SINGLE")],
                            retries=args.retries,
                        )[0]
                    except SceneBatchValidationError:
                        final = label
                status = _label_status(final, args.confidence_threshold)
                persist_scene_label(
                    con, target=target, model=model, labels=final, status=status,
                    evidence={
                        "original_filename": target.original_filename,
                        "reference_used": bool(target.reference_description),
                    },
                )
        report = _report(con, targets, model, failures)
        _write_json(report_path, report)
        done = min(offset + len(batch), len(pending))
        print(
            f"  {done}/{len(pending)}  ready={report['by_status'].get('ready', 0)} "
            f"candidate={report['by_status'].get('candidate', 0)} "
            f"failed={report['by_status'].get('failed', 0)}"
        )
        if args.delay > 0:
            time.sleep(args.delay)
    final = _report(con, targets, model, failures)
    _write_json(report_path, final)
    con.close()
    print(f"报告：{report_path}")
    return 0 if not final["remaining"] and not final["by_status"].get("failed") else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="批量分类并标注 AA 背景与剧情 CG")
    parser.add_argument("mode", choices=("plan", "run", "audit"), nargs="?", default="plan")
    parser.add_argument("--config", default=str(HERE / "aa_config.json"))
    parser.add_argument("--db", default=str(HERE / "aa_assets.db"))
    parser.add_argument("--llm", default=str(HERE / "llm.json"))
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--label-version")
    parser.add_argument("--official-manifest", default=str(HERE / "out" / "official-previews" / "manifest.json"))
    parser.add_argument("--official-catalog")
    parser.add_argument("--official-cache")
    parser.add_argument(
        "--official-popup-cache",
        default=str(HERE / "out" / "official-popup-previews"),
    )
    parser.add_argument("--overrides", action="append")
    parser.add_argument("--reference", default="")
    parser.add_argument("--output", default=str(HERE / "out" / "scene-asset-labels"))
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--confidence-threshold", type=float, default=0.75)
    parser.add_argument("--delay", type=float, default=0.0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--channel", choices=("background", "popup"))
    parser.add_argument("--source-kind", choices=("official_base", "extra_pack"))
    parser.add_argument(
        "--asset-key", action="append", default=[],
        help="只处理指定真实资源 key；可重复传入",
    )
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--retry-failed", action="store_true",
        help="只重试当前标注版本中 status=failed 的真实内容身份",
    )
    args = parser.parse_args(argv)
    if not 1 <= args.batch_size <= 4:
        parser.error("--batch-size must be between 1 and 4")
    if args.shard_count < 1 or not 0 <= args.shard_index < args.shard_count:
        parser.error("invalid shard selection")
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    roots = args.overrides or config.get("aa_override_roots") or [
        str(Path(config["aa_data"]) / "overrides")
    ]
    manifest = args.official_manifest if Path(args.official_manifest).is_file() else None
    catalog = args.official_catalog or config.get("aa_catalog")
    cache = args.official_cache or config.get("aa_cache")
    popup_manifest = None
    if catalog and cache and Path(catalog).is_file() and Path(cache).is_dir():
        popup_manifest = materialize_official_popup_previews(
            catalog, cache, args.official_popup_cache
        )
    targets, stats = discover_scene_targets(
        official_manifest=manifest,
        override_roots=roots,
        official_popup_manifest=popup_manifest,
        reference_path=args.reference or None,
    )
    if args.channel:
        targets = [
            target for target in targets
            if target.resource_channel == args.channel
        ]
    if args.source_kind:
        targets = [
            target for target in targets
            if target.source_kind == args.source_kind
        ]
    if args.asset_key:
        selected_keys = {str(key).casefold() for key in args.asset_key}
        targets = [
            target for target in targets
            if target.asset_key.casefold() in selected_keys
        ]
    if args.retry_failed:
        con = assetdb.connect(args.db)
        failed = {
            (str(row["resource_channel"]), str(row["asset_key"]).casefold(), str(row["content_sha256"]))
            for row in con.execute(
                "SELECT resource_channel,asset_key,content_sha256 "
                "FROM scene_visual_label WHERE model=? AND status='failed'",
                (str(args.label_version or args.model or "").strip(),),
            )
        }
        con.close()
        targets = [
            target for target in targets
            if (target.resource_channel, target.asset_key.casefold(), target.content_sha256)
            in failed
        ]
    targets = select_target_shard(
        targets, shard_count=args.shard_count, shard_index=args.shard_index
    )
    if args.limit is not None:
        targets = targets[:max(0, args.limit)]
    output = Path(args.output).resolve()
    _write_json(output / "inventory.json", {
        "stats": stats,
        "selection": {
            "shard_count": args.shard_count,
            "shard_index": args.shard_index,
            "limit": args.limit,
            "channel": args.channel,
            "source_kind": args.source_kind,
            "asset_keys": args.asset_key,
            "retry_failed": args.retry_failed,
        },
        "selected_count": len(targets),
        "targets": [asdict(target) for target in targets],
    })
    print(
        f"盘点到 {stats['target_count']} 个内容身份："
        f"background={stats['by_channel'].get('background', 0)}，"
        f"popup={stats['by_channel'].get('popup', 0)}。"
    )
    print(
        f"来源：基础包={stats['by_source_kind'].get('official_base', 0)}，"
        f"额外包={stats['by_source_kind'].get('extra_pack', 0)}；"
        f"参考描述匹配={stats['reference']['matched_targets']}。"
    )
    if args.mode == "plan":
        print(f"清单：{output / 'inventory.json'}")
        return 0
    model = str(args.label_version or args.model or "").strip()
    if args.mode == "audit":
        con = assetdb.connect(args.db)
        report = _report(con, targets, model or assetdb.active_scene_label_model(con), [])
        con.close()
        _write_json(output / "audit.json", report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    return run_batch(args, targets, output / "report.json")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n已中断；已完成批次已经写入数据库，下次运行会继续。")
        raise SystemExit(130)
