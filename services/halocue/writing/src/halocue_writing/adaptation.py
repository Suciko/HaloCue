"""Author-facing adaptation plan with automated analysis, checkpoints and chapter candidates."""

from __future__ import annotations
import json
from .workspace_access import workspace_operation
from .errors import DomainError, NotFound
from .repository import canonical_json, new_id, now, sha256_text
from .source_catalog import source_windows
from .adaptation_prompts import build_chapter_prompt


def validate_chapter_candidate(
    value, *, source_id, chapter, code="provider_output_invalid", status=502
):
    """Validate structure and exact pinned-source references, not literary fidelity."""

    def invalid(field):
        raise DomainError(
            code,
            "改编候选格式或原文引用无效，请重新生成并核对来源。",
            status=status,
            details={"field": field},
        )

    if not isinstance(value, dict) or value.get("schema_version") != "adaptation-chapter/1.0":
        invalid("schema_version")
    # Python's JSON decoder permits NaN/Infinity, including nested metadata.
    # Validate here so both new output and legacy candidate acceptance stay strict.
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError):
        invalid("json")
    text = value.get("text")
    if not isinstance(text, str) or not text.strip():
        invalid("text")
    for field in ("deviations", "open_threads"):
        if not isinstance(value.get(field), list) or any(
            not isinstance(x, (str, dict)) for x in value[field]
        ):
            invalid(field)
    for field, expected in (
        ("source_version_id", source_id),
        ("source_chapter_id", chapter["id"]),
        ("prompt_contract", "adaptation/1.0"),
    ):
        if field in value and value[field] != expected:
            invalid(field)
    if "formal" in value and value["formal"] is not False:
        invalid("formal")
    refs = value.get("source_refs")
    if not isinstance(refs, list) or not refs:
        invalid("source_refs")
    paragraphs = {item["id"]: item["text"] for item in chapter.get("paragraphs", [])}
    for index, ref in enumerate(refs):
        if not isinstance(ref, dict):
            invalid(f"source_refs[{index}]")
        paragraph_id, quote = ref.get("paragraph_id"), ref.get("quote")
        if not isinstance(paragraph_id, str) or paragraph_id not in paragraphs:
            invalid(f"source_refs[{index}].paragraph_id")
        if not isinstance(quote, str) or not quote.strip() or quote not in paragraphs[paragraph_id]:
            invalid(f"source_refs[{index}].quote")
    return value


class AdaptationService:
    def __init__(self, service):
        self.service = service
        self.repo = service.repo
        self.sources = service.sources
        self.data_access = self.repo.data_access

    def _row(self, row):
        if not row:
            return None
        return {
            **dict(row),
            "selected_chapter_ids": json.loads(row["selected_chapter_ids_json"]),
            "plan": json.loads(row["plan_json"]),
            "budget": json.loads(row["budget_json"]),
        }

    @workspace_operation
    def get(self, adaptation_id):
        with self.repo.connect() as c:
            row = c.execute("SELECT * FROM adaptations WHERE id=?", (adaptation_id,)).fetchone()
            if not row:
                raise NotFound("adaptation", adaptation_id)
            item = self._row(row)
            chapters = c.execute(
                "SELECT * FROM adaptation_chapters WHERE adaptation_id=? ORDER BY ordinal",
                (adaptation_id,),
            ).fetchall()
        item["chapters"] = [
            {
                **dict(ch),
                "candidate": json.loads(ch["candidate_json"]),
                "dependency": json.loads(ch["dependency_json"]),
            }
            for ch in chapters
        ]
        item["plan_digest"] = sha256_text(canonical_json(item["plan"]))
        return item

    @workspace_operation
    def list(self, work_id):
        """Return adaptation summaries for a work in newest-first order.

        The web client needs a stable collection endpoint so it can render the
        work's adaptation history without knowing task IDs.  Reuse ``get`` to
        keep the detail shape (including chapter checkpoints and plan digest)
        identical to the single-task endpoint.
        """
        with self.repo.connect() as c:
            rows = c.execute(
                "SELECT id FROM adaptations WHERE work_id=? ORDER BY updated_at DESC, id DESC",
                (work_id,),
            ).fetchall()
        return [self.get(row["id"]) for row in rows]

    @workspace_operation
    def create(self, work_id, payload):
        source = self.sources.get(work_id, payload.get("source_version_id"))
        if not source:
            raise DomainError("adaptation_source_required", "请先导入并确认原文范围。", status=409)
        selected = payload.get("chapter_ids") or [c["id"] for c in source["chapters"]]
        known = {c["id"] for c in source["chapters"]}
        if any(x not in known for x in selected):
            raise DomainError(
                "adaptation_chapter_invalid", "改编章节不在当前原文版本中。", status=422
            )
        chapters = [c for c in source["chapters"] if c["id"] in selected]
        plan = {
            "schema_version": "adaptation-plan/1.0",
            "fidelity": "faithful_source",
            "unfinished_policy": "provided_scope_only",
            "character_mapping": payload.get("character_mapping", {}),
            "scene_plan": [
                {"chapter_id": c["id"], "scenes": [], "sample_required": True} for c in chapters
            ],
            "rules": [
                "保留事件、私设、关系和揭示顺序",
                "不续写未完结内容",
                "角色知情不等于获准提前泄密",
            ],
        }
        adaptation_id = new_id("adaptation")
        timestamp = now()
        max_calls = payload.get("max_calls")
        if max_calls is None:
            max_calls = max(1, len(chapters) * 5)
        if type(max_calls) is not int or max_calls <= 0:
            raise DomainError(
                "invalid_adaptation_budget", "max_calls 必须是正整数候选调用上限。", status=422
            )
        budget = {"max_calls": max_calls, "reserved_calls": 0}
        with self.repo.transaction() as c:
            c.execute(
                "INSERT INTO adaptations VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    adaptation_id,
                    work_id,
                    source["id"],
                    "1.0",
                    "awaiting_plan",
                    canonical_json(selected),
                    canonical_json(plan),
                    canonical_json(budget),
                    timestamp,
                    timestamp,
                ),
            )
            for ordinal, ch in enumerate(chapters):
                c.execute(
                    "INSERT INTO adaptation_chapters VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        new_id("adaptation-chapter"),
                        adaptation_id,
                        ch["id"],
                        ordinal,
                        "planned",
                        "{}",
                        "{}",
                        timestamp,
                        timestamp,
                    ),
                )
        return self.get(adaptation_id)

    @workspace_operation
    def approve_plan(self, adaptation_id, payload):
        item = self.get(adaptation_id)
        if payload.get("plan_digest") and payload["plan_digest"] != item["plan_digest"]:
            raise DomainError("adaptation_plan_changed", "改编计划已变化，请重新查看。", status=409)
        with self.repo.transaction() as c:
            c.execute(
                "UPDATE adaptations SET status='ready',updated_at=? WHERE id=? AND status='awaiting_plan'",
                (now(), adaptation_id),
            )
        return self.get(adaptation_id)

    @workspace_operation
    def run(self, adaptation_id, payload=None):
        item = self.get(adaptation_id)
        if item["status"] not in {"ready", "running"}:
            raise DomainError("adaptation_plan_required", "请先确认改编计划。", status=409)
        source = self.sources.get(item["work_id"], item["source_version_id"])
        selected = set(item["selected_chapter_ids"])
        windows = source_windows(
            [chapter for chapter in source["chapters"] if chapter["id"] in selected],
            int((payload or {}).get("window_characters") or 10000),
        )
        by_chapter = {}
        for window in windows:
            by_chapter.setdefault(window["chapter_id"], []).append(window)
        with self.repo.transaction() as connection:
            connection.execute(
                "UPDATE adaptations SET status='running',updated_at=? WHERE id=?",
                (now(), adaptation_id),
            )
            for chapter_id, chapter_windows in by_chapter.items():
                row = connection.execute(
                    "SELECT * FROM adaptation_chapters WHERE adaptation_id=? AND source_chapter_id=?",
                    (adaptation_id, chapter_id),
                ).fetchone()
                analysis = {
                    "schema_version": "adaptation-analysis/1.0",
                    "source_only": True,
                    "source_version_id": source["id"],
                    "source_chapter_id": chapter_id,
                    "windows": [
                        {"window_id": w["id"], "coverage": w["spans"]} for w in chapter_windows
                    ],
                    "coverage": [span for w in chapter_windows for span in w["spans"]],
                }
                dependency = json.loads(row["dependency_json"] or "{}")
                dependency["analysis"] = analysis
                # Coverage is an analysis projection, never a replacement for a
                # pending candidate or an accepted formal manuscript.
                preserve_candidate = row["status"] in {"candidate", "accepted"}
                connection.execute(
                    "UPDATE adaptation_chapters SET dependency_json=?,candidate_json=?,status=?,updated_at=? WHERE id=?",
                    (
                        canonical_json(dependency),
                        row["candidate_json"] if preserve_candidate else canonical_json(analysis),
                        row["status"] if preserve_candidate else "analyzed",
                        now(),
                        row["id"],
                    ),
                )
        return self.get(adaptation_id)

    @workspace_operation
    def generate_chapter_candidate(
        self, adaptation_id: str, chapter_id: str, payload: dict | None = None
    ):
        item = self.get(adaptation_id)
        if item["status"] not in {"ready", "running", "analyzed"}:
            raise DomainError("adaptation_plan_required", "请先确认改编计划。", status=409)
        source = self.sources.get(item["work_id"], item["source_version_id"])
        chapter = next((c for c in source["chapters"] if c["id"] == chapter_id), None)
        if not chapter or chapter_id not in item["selected_chapter_ids"]:
            raise NotFound("adaptation_chapter", chapter_id)
        system, user = build_chapter_prompt(
            source=source,
            chapter=chapter,
            character_mapping=item["plan"].get("character_mapping", {}),
            unfinished=source.get("completion_state") != "complete",
        )
        provider, provider_identity = self.service._capture_provider()
        context = {
            "source_version": source["id"],
            "chapter": chapter,
            "brief": {"characters": list(item["plan"].get("character_mapping", {}).keys())},
            "scene_contract": {
                "title": chapter["title"],
                "goal": "将本章已提供内容转换为连续剧本候选",
                "location": "原文既有地点",
            },
            "runtime_character_cards": [],
            "character_mapping": item["plan"].get("character_mapping", {}),
            "unfinished": source.get("completion_state") != "complete",
            "adaptation_prompt": system,
            "user_prompt": user,
        }
        with self.repo.transaction() as c:
            chapter_row = c.execute(
                "SELECT id FROM adaptation_chapters WHERE adaptation_id=? AND source_chapter_id=?",
                (adaptation_id, chapter_id),
            ).fetchone()
            if not chapter_row:
                raise NotFound("adaptation_chapter", chapter_id)
            scope_id = chapter_row["id"]
            base_row = c.execute(
                "SELECT current_revision_id FROM artifacts WHERE work_id=? AND kind='adaptation_manuscript' AND scope_type='adaptation_chapter' AND scope_id=?",
                (item["work_id"], scope_id),
            ).fetchone()
            base_revision_id = base_row["current_revision_id"] if base_row else None
            current_source = c.execute(
                "SELECT current_version_id FROM work_sources WHERE work_id=?", (item["work_id"],)
            ).fetchone()
            if not current_source or current_source["current_version_id"] != source["id"]:
                raise DomainError(
                    "adaptation_inputs_changed",
                    "原文版本已更新，请基于当前原文重新创建改编任务。",
                    status=409,
                )
            row = c.execute(
                "SELECT budget_json FROM adaptations WHERE id=?", (adaptation_id,)
            ).fetchone()
            budget = json.loads(row[0] or "{}")
            if int(budget.get("reserved_calls") or 0) >= int(budget.get("max_calls") or 0):
                raise DomainError(
                    "adaptation_budget_exhausted", "本次改编任务的调用预算已用尽。", status=409
                )
            budget["reserved_calls"] = int(budget.get("reserved_calls") or 0) + 1
            c.execute(
                "UPDATE adaptations SET budget_json=?,updated_at=? WHERE id=?",
                (canonical_json(budget), now(), adaptation_id),
            )
        # Once dispatched, a failure/timeout may already have consumed provider
        # resources. Keep the attempt charged; do not refund it to zero usage.
        # This bounds logical candidate attempts, not transport-level retries.
        with self.service._provider_lock:
            call = provider._call_llm(system, user) if hasattr(provider, "_call_llm") else None
            raw_text = call.text if call is not None else provider.generate_scene(context)
        try:
            structured = json.loads(raw_text)
        except (TypeError, json.JSONDecodeError) as exc:
            raise DomainError(
                "provider_output_invalid", "改编模型没有返回契约要求的 JSON 候选。", status=502
            ) from exc
        validate_chapter_candidate(structured, source_id=source["id"], chapter=chapter)
        text, refs = structured["text"], structured["source_refs"]
        candidate = {
            "schema_version": "adaptation-chapter/1.0",
            "text": text,
            "source_version_id": source["id"],
            "source_chapter_id": chapter_id,
            "formal": False,
            "prompt_contract": "adaptation/1.0",
            "source_refs": refs,
            "deviations": structured["deviations"],
            "open_threads": structured["open_threads"],
        }
        candidate_id = new_id("proposal")
        source_digest = next(
            (item["content_digest"] for item in source["chapters"] if item["id"] == chapter_id), ""
        )
        with self.repo.transaction() as c:
            current_source = c.execute(
                "SELECT current_version_id FROM work_sources WHERE work_id=?", (item["work_id"],)
            ).fetchone()
            current_target = c.execute(
                "SELECT current_revision_id FROM artifacts WHERE work_id=? AND kind='adaptation_manuscript' AND scope_type='adaptation_chapter' AND scope_id=?",
                (item["work_id"], scope_id),
            ).fetchone()
            current_revision_id = current_target["current_revision_id"] if current_target else None
            if (
                not current_source
                or current_source["current_version_id"] != source["id"]
                or current_revision_id != base_revision_id
            ):
                raise DomainError(
                    "adaptation_inputs_changed",
                    "生成期间原文或已采纳稿件发生变化，晚到候选未写入。",
                    status=409,
                )
            candidate_uri, candidate_hash = self.repo.atomic_write_text(
                f"artifacts/proposals/{candidate_id}.json", canonical_json(candidate) + "\n"
            )
            c.execute(
                "UPDATE adaptation_chapters SET candidate_json=?,status='candidate',updated_at=? WHERE adaptation_id=? AND source_chapter_id=?",
                (
                    canonical_json({**candidate, "proposal_id": candidate_id}),
                    now(),
                    adaptation_id,
                    chapter_id,
                ),
            )
            c.execute(
                "INSERT INTO proposals (id,work_id,kind,scope_type,scope_id,base_revision_id,candidate_uri,candidate_hash,diff_json,evidence_json,risk,status,provider_json,created_at,decided_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    candidate_id,
                    item["work_id"],
                    "adaptation_chapter",
                    "adaptation_chapter",
                    scope_id,
                    base_revision_id,
                    candidate_uri,
                    candidate_hash,
                    canonical_json({"format": "adaptation-chapter/1.0", "source_refs": refs}),
                    canonical_json(
                        {
                            "source_version_id": source["id"],
                            "source_chapter_id": chapter_id,
                            "source_digest": source_digest,
                        }
                    ),
                    "medium",
                    "pending",
                    canonical_json(provider_identity),
                    now(),
                    None,
                ),
            )
        return {
            "adaptation": self.get(adaptation_id),
            "proposal_id": candidate_id,
            "candidate": candidate,
        }
