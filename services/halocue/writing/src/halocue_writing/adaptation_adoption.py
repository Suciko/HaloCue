"""Explicit adoption into the existing scene manuscript/revision pipeline."""

import json

from .adaptation import validate_chapter_candidate
from .adaptation_targets import resolve_target
from .errors import DomainError, NotFound
from .repository import canonical_json, new_id, now
from .workflow_pack import MODE_SOURCES


def _source_chapter(connection, work_id, candidate):
    current = connection.execute(
        "SELECT current_version_id FROM work_sources WHERE work_id=?", (work_id,)
    ).fetchone()
    if not current or current["current_version_id"] != candidate["source_version_id"]:
        raise DomainError("proposal_superseded", "原文版本已更新，请重新生成改编候选。", status=409)
    row = connection.execute(
        "SELECT document_json FROM source_versions WHERE id=? AND work_id=?",
        (current["current_version_id"], work_id),
    ).fetchone()
    document = json.loads(row["document_json"]) if row else {}
    chapter = next(
        (ch for ch in document.get("chapters", []) if ch["id"] == candidate["source_chapter_id"]),
        None,
    )
    if not chapter:
        raise DomainError("proposal_superseded", "原文章节已变化，不能采纳旧候选。", status=409)
    validate_chapter_candidate(
        candidate,
        source_id=current["current_version_id"],
        chapter=chapter,
        code="proposal_candidate_invalid",
        status=409,
    )
    return chapter


def _check_target(payload, target):
    if ("target_scene_id" in payload and payload["target_scene_id"] != target["scene_id"]) or (
        "target_chapter_id" in payload and payload["target_chapter_id"] != target["chapter_id"]
    ):
        raise DomainError(
            "adaptation_target_changed",
            "目标与候选预览不一致，请重新查看目标后再确认。",
            status=409,
        )


def _save_scene(service, c, work_id, chapter_row, source_chapter, candidate, target, provenance):
    scene_id = target["scene_id"]
    is_new = not scene_id
    if is_new:
        destination = c.execute(
            "SELECT id FROM chapters WHERE id=? AND work_id=?", (target["chapter_id"], work_id)
        ).fetchone()
        if not destination:
            raise DomainError("adaptation_target_missing", "目标章节不存在。", status=409)
        scene_id = new_id("scene")
        count = c.execute(
            "SELECT COUNT(*) FROM scenes WHERE chapter_id=?", (destination["id"],)
        ).fetchone()[0]
        writing_mode = "bond_short"
        brief = c.execute(
            "SELECT r.* FROM artifacts a JOIN revisions r ON r.id=a.current_revision_id WHERE a.work_id=? AND a.kind='brief'",
            (work_id,),
        ).fetchone()
        if brief:
            value = service._verified_revision_content(brief, artifact_id=brief["artifact_id"])
            if value.get("mode") in MODE_SOURCES:
                writing_mode = value["mode"]
        contract = {
            "location": "",
            "goal": "呈现本章已提供内容",
            "known_facts": [],
            "forbidden_reveals": [],
            "stop_boundary": "已提供的原文章节边界",
            "writing_mode": writing_mode,
        }
        timestamp = now()
        c.execute(
            "INSERT INTO scenes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                scene_id,
                work_id,
                destination["id"],
                f"{count + 1:06d}",
                source_chapter["title"],
                "planned",
                1,
                None,
                canonical_json(contract),
                timestamp,
                timestamp,
            ),
        )
    artifact = service._artifact(c, work_id, "scene_script", "scene", scene_id)
    base_blocks = []
    if not is_new and target["base_revision_id"]:
        revision = c.execute(
            "SELECT * FROM revisions WHERE id=?", (target["base_revision_id"],)
        ).fetchone()
        content = service._verified_revision_content(revision, artifact_id=artifact["id"])
        base_blocks = content.get("blocks") or service._scene_blocks_from_text(
            content.get("text", "")
        )
    scene_content = service._scene_content_preserving_unchanged_blocks(
        candidate["text"], base_blocks
    )
    scene_content["blocks"] = service._normalize_scene_blocks(scene_content["blocks"])
    scene_content["text"] = service._scene_text_from_blocks(scene_content["blocks"])
    provenance = {
        **provenance,
        "source_version_id": candidate["source_version_id"],
        "source_chapter_id": candidate["source_chapter_id"],
        "source_refs": candidate["source_refs"],
        "normalization_changed_text": scene_content["text"] != candidate["text"],
    }
    revision_id = service._add_revision(
        c, artifact, scene_content, "user", provenance, schema_version="scene-blocks/1.0"
    )
    c.execute(
        "UPDATE scenes SET current_revision_id=?,status='review',version=version+1,updated_at=? WHERE id=?",
        (revision_id, now(), scene_id),
    )
    dependency = json.loads(chapter_row["dependency_json"] or "{}")
    dependency["scene_target"] = {"scene_id": scene_id, "chapter_id": target["chapter_id"]}
    c.execute(
        "UPDATE adaptation_chapters SET status='accepted',dependency_json=?,candidate_json=?,updated_at=? WHERE id=?",
        (
            canonical_json(dependency),
            canonical_json(
                {**candidate, "formal": True, "revision_id": revision_id, "scene_id": scene_id}
            ),
            now(),
            chapter_row["id"],
        ),
    )
    if is_new:
        service._record_current_story_structure(c, work_id, workflow="adaptation.scene.create")
    service._ensure_memory_extract_work_item(c, work_id, scene_id, revision_id)
    service._supersede_background_knowledge_suggestions(
        c,
        work_id=work_id,
        scene_id=scene_id,
        current_revision_id=revision_id,
        reason="采纳改编产生了新的场景正文，旧建议不再适用。",
    )
    return {
        "scene_id": scene_id,
        "revision_id": revision_id,
        "target_chapter_id": target["chapter_id"],
        "normalization_changed_text": provenance["normalization_changed_text"],
    }


def accept_candidate(service, work_id, proposal_id, payload):
    with service.repo.transaction() as c:
        version = service._check_work_version(c, work_id, int(payload.get("expected_version", -1)))
        proposal = c.execute(
            "SELECT * FROM proposals WHERE id=? AND work_id=?", (proposal_id, work_id)
        ).fetchone()
        if not proposal or proposal["kind"] != "adaptation_chapter":
            raise NotFound("proposal", proposal_id)
        if proposal["status"] != "pending":
            raise DomainError("proposal_not_pending", "候选方案已经处理。", status=409)
        candidate = json.loads(service._verified_proposal_candidate(proposal))
        if (
            not isinstance(candidate, dict)
            or candidate.get("formal") is not False
            or candidate.get("schema_version") != "adaptation-chapter/1.0"
            or "source_version_id" not in candidate
            or "source_chapter_id" not in candidate
        ):
            raise DomainError("proposal_candidate_invalid", "改编候选格式无效。", status=409)
        source_chapter = _source_chapter(c, work_id, candidate)
        evidence = json.loads(proposal["evidence_json"] or "{}")
        if (
            evidence.get("source_version_id") != candidate["source_version_id"]
            or evidence.get("source_chapter_id") != candidate["source_chapter_id"]
            or evidence.get("source_digest") != source_chapter["content_digest"]
        ):
            raise DomainError("proposal_superseded", "原文引用已变化，不能采纳旧候选。", status=409)
        chapter_row = c.execute(
            "SELECT * FROM adaptation_chapters WHERE id=? AND adaptation_id IN (SELECT id FROM adaptations WHERE work_id=?)",
            (proposal["scope_id"], work_id),
        ).fetchone()
        if not chapter_row:
            raise NotFound("adaptation_chapter", proposal["scope_id"])
        if chapter_row["source_chapter_id"] != candidate["source_chapter_id"]:
            raise DomainError(
                "proposal_candidate_invalid", "候选引用不属于此改编章节。", status=409
            )
        adaptation = c.execute(
            "SELECT source_version_id FROM adaptations WHERE id=?", (chapter_row["adaptation_id"],)
        ).fetchone()
        if not adaptation or adaptation["source_version_id"] != candidate["source_version_id"]:
            raise DomainError(
                "proposal_candidate_invalid", "候选原文版本不属于此改编任务。", status=409
            )
        target = resolve_target(c, work_id, chapter_row)
        if proposal["base_revision_id"] != target["base_revision_id"]:
            raise service._proposal_superseded("已采纳场景正文已变化，请基于当前正文重新生成。")
        pinned = candidate.get("target")
        if pinned is not None and pinned != target:
            raise service._proposal_superseded("候选目标已变化，请重新查看后生成。")
        if pinned is None and "target_chapter_id" not in payload:
            raise DomainError(
                "adaptation_target_required",
                "旧候选没有目标预览，请明确确认放入的章节。",
                status=409,
            )
        _check_target(payload, target)
        result = _save_scene(
            service,
            c,
            work_id,
            chapter_row,
            source_chapter,
            candidate,
            target,
            {
                "workflow": "adaptation.chapter",
                "proposal_id": proposal_id,
                "candidate_hash": proposal["candidate_hash"],
            },
        )
        timestamp = now()
        c.execute(
            "UPDATE proposals SET status='accepted',decided_at=? WHERE id=?",
            (timestamp, proposal_id),
        )
        c.execute(
            "INSERT INTO decisions VALUES (?,?,?,?,?,?,?)",
            (
                new_id("decision"),
                work_id,
                "proposal",
                proposal_id,
                "accepted",
                str(payload.get("note", "")),
                timestamp,
            ),
        )
        for item in c.execute(
            "SELECT id,output_refs_json FROM work_items WHERE status='waiting_user'"
        ).fetchall():
            if proposal_id in json.loads(item["output_refs_json"]):
                c.execute(
                    "UPDATE work_items SET status='succeeded',updated_at=? WHERE id=?",
                    (timestamp, item["id"]),
                )
        service._bump_work(c, work_id, version)
    service._schedule_commit_projection(work_id, result["revision_id"])
    return {**result, "proposal_id": proposal_id, "work": service.get_work(work_id)}


def promote_legacy(service, work_id, adaptation_id, source_chapter_id, payload):
    revision_id = payload.get("expected_revision_id")
    chapter_id = payload.get("target_chapter_id")
    if (
        not isinstance(revision_id, str)
        or not revision_id
        or not isinstance(chapter_id, str)
        or not chapter_id
    ):
        raise DomainError(
            "adaptation_target_required", "请明确确认旧稿修订和放入的目标章节。", status=409
        )
    with service.repo.transaction() as c:
        chapter_row = c.execute(
            "SELECT ch.* FROM adaptation_chapters ch JOIN adaptations a ON a.id=ch.adaptation_id WHERE a.id=? AND a.work_id=? AND ch.source_chapter_id=?",
            (adaptation_id, work_id, source_chapter_id),
        ).fetchone()
        if not chapter_row:
            raise NotFound("adaptation_chapter", source_chapter_id)
        dependency = json.loads(chapter_row["dependency_json"] or "{}")
        receipt = dependency.get("legacy_promotion")
        if receipt:
            if (
                receipt.get("legacy_revision_id") != revision_id
                or receipt.get("target_chapter_id") != chapter_id
            ):
                raise DomainError(
                    "adaptation_target_changed",
                    "这份旧稿已经放入场景，不能把重试当作另一次覆盖。",
                    status=409,
                )
            result = {key: receipt[key] for key in ("scene_id", "revision_id", "target_chapter_id")}
            replay = True
        else:
            version = service._check_work_version(
                c, work_id, int(payload.get("expected_version", -1))
            )
            if dependency.get("scene_target"):
                raise DomainError(
                    "adaptation_target_changed",
                    "本章已关联正式场景，请在场景中继续编辑。",
                    status=409,
                )
            artifact = c.execute(
                "SELECT * FROM artifacts WHERE work_id=? AND kind='adaptation_manuscript' AND scope_type='adaptation_chapter' AND scope_id=?",
                (work_id, chapter_row["id"]),
            ).fetchone()
            if not artifact or artifact["current_revision_id"] != revision_id:
                raise DomainError(
                    "proposal_superseded",
                    "旧改编稿修订已变化，请重新查看后再放入场景。",
                    status=409,
                )
            revision = c.execute("SELECT * FROM revisions WHERE id=?", (revision_id,)).fetchone()
            old = service._verified_revision_content(revision, artifact_id=artifact["id"])
            if (
                old.get("schema_version") != "adaptation-manuscript/1.0"
                or old.get("source_chapter_id") != source_chapter_id
            ):
                raise DomainError(
                    "proposal_candidate_invalid", "旧改编稿的格式或章节引用无效。", status=409
                )
            candidate = {
                "schema_version": "adaptation-chapter/1.0",
                "formal": False,
                **{
                    key: old.get(key)
                    for key in ("text", "source_version_id", "source_chapter_id", "source_refs")
                },
                "deviations": old.get("deviations", []),
                "open_threads": old.get("open_threads", []),
            }
            source_chapter = _source_chapter(c, work_id, candidate)
            target = {
                "scene_id": None,
                "chapter_id": chapter_id,
                "base_revision_id": revision_id,
                "mode": "create",
            }
            result = _save_scene(
                service,
                c,
                work_id,
                chapter_row,
                source_chapter,
                candidate,
                target,
                {
                    "workflow": "adaptation.legacy.promote",
                    "legacy_revision_id": revision_id,
                    "legacy_content_hash": revision["content_hash"],
                },
            )
            updated = c.execute(
                "SELECT dependency_json FROM adaptation_chapters WHERE id=?", (chapter_row["id"],)
            ).fetchone()
            dependency = json.loads(updated["dependency_json"])
            dependency["legacy_promotion"] = {**result, "legacy_revision_id": revision_id}
            c.execute(
                "UPDATE adaptation_chapters SET dependency_json=? WHERE id=?",
                (canonical_json(dependency), chapter_row["id"]),
            )
            c.execute(
                "INSERT INTO decisions VALUES (?,?,?,?,?,?,?)",
                (
                    new_id("decision"),
                    work_id,
                    "revision",
                    revision_id,
                    "promoted_to_scene",
                    str(payload.get("note", "明确把旧改编稿放入场景")),
                    now(),
                ),
            )
            service._bump_work(c, work_id, version)
            replay = False
    if not replay:
        service._schedule_commit_projection(work_id, result["revision_id"])
    return {**result, "deduplicated": replay, "work": service.get_work(work_id)}
