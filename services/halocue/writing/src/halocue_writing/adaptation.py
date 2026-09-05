"""Author-facing adaptation plan with automated analysis, checkpoints and chapter candidates."""
from __future__ import annotations
import json
from .errors import DomainError, NotFound
from .repository import canonical_json, new_id, now, sha256_text
from .source_catalog import source_windows
from .adaptation_prompts import build_chapter_prompt

class AdaptationService:
    def __init__(self, service): self.service=service; self.repo=service.repo; self.sources=service.sources
    def _row(self,row):
        if not row: return None
        return {**dict(row),"selected_chapter_ids":json.loads(row["selected_chapter_ids_json"]),"plan":json.loads(row["plan_json"]),"budget":json.loads(row["budget_json"])}
    def get(self,adaptation_id):
        with self.repo.connect() as c:
            row=c.execute("SELECT * FROM adaptations WHERE id=?",(adaptation_id,)).fetchone()
            if not row: raise NotFound("adaptation",adaptation_id)
            item=self._row(row); chapters=c.execute("SELECT * FROM adaptation_chapters WHERE adaptation_id=? ORDER BY ordinal",(adaptation_id,)).fetchall()
        item["chapters"]=[{**dict(ch),"candidate":json.loads(ch["candidate_json"]),"dependency":json.loads(ch["dependency_json"])} for ch in chapters]; item["plan_digest"]=sha256_text(canonical_json(item["plan"])); return item
    def create(self,work_id,payload):
        source=self.sources.get(work_id,payload.get("source_version_id"))
        if not source: raise DomainError("adaptation_source_required","请先导入并确认原文范围。",status=409)
        selected=payload.get("chapter_ids") or [c["id"] for c in source["chapters"]]; known={c["id"] for c in source["chapters"]}
        if any(x not in known for x in selected): raise DomainError("adaptation_chapter_invalid","改编章节不在当前原文版本中。",status=422)
        chapters=[c for c in source["chapters"] if c["id"] in selected]; plan={"schema_version":"adaptation-plan/1.0","fidelity":"faithful_source","unfinished_policy":"provided_scope_only","character_mapping":payload.get("character_mapping",{}),"scene_plan":[{"chapter_id":c["id"],"scenes":[],"sample_required":True} for c in chapters],"rules":["保留事件、私设、关系和揭示顺序","不续写未完结内容","角色知情不等于获准提前泄密"]}; adaptation_id=new_id("adaptation"); timestamp=now(); budget={"max_calls":int(payload.get("max_calls") or max(1,len(chapters)*5)),"reserved_calls":0}
        with self.repo.transaction() as c:
            c.execute("INSERT INTO adaptations VALUES (?,?,?,?,?,?,?,?,?,?)",(adaptation_id,work_id,source["id"],"1.0","awaiting_plan",canonical_json(selected),canonical_json(plan),canonical_json(budget),timestamp,timestamp))
            for ordinal,ch in enumerate(chapters): c.execute("INSERT INTO adaptation_chapters VALUES (?,?,?,?,?,?,?,?,?)",(new_id("adaptation-chapter"),adaptation_id,ch["id"],ordinal,"planned","{}","{}",timestamp,timestamp))
        return self.get(adaptation_id)
    def approve_plan(self,adaptation_id,payload):
        item=self.get(adaptation_id)
        if payload.get("plan_digest") and payload["plan_digest"]!=item["plan_digest"]: raise DomainError("adaptation_plan_changed","改编计划已变化，请重新查看。",status=409)
        with self.repo.transaction() as c: c.execute("UPDATE adaptations SET status='ready',updated_at=? WHERE id=? AND status='awaiting_plan'",(now(),adaptation_id))
        return self.get(adaptation_id)
    def run(self,adaptation_id,payload=None):
        item=self.get(adaptation_id)
        if item["status"] not in {"ready","running"}: raise DomainError("adaptation_plan_required","请先确认改编计划。",status=409)
        source=self.sources.get(item["work_id"],item["source_version_id"]); selected=set(item["selected_chapter_ids"]); windows=source_windows([c for c in source["chapters"] if c["id"] in selected],int((payload or {}).get("window_characters") or 10000))
        with self.repo.transaction() as c:
            c.execute("UPDATE adaptations SET status='running',updated_at=? WHERE id=?",(now(),adaptation_id))
            for window in windows: c.execute("UPDATE adaptation_chapters SET candidate_json=?,status='analyzed',updated_at=? WHERE adaptation_id=? AND source_chapter_id=?",(canonical_json({"window_id":window["id"],"coverage":window["spans"],"source_only":True}),now(),adaptation_id,window["chapter_id"]))
        return self.get(adaptation_id)

    def generate_chapter_candidate(self, adaptation_id: str, chapter_id: str, payload: dict | None = None):
        item = self.get(adaptation_id)
        if item["status"] not in {"ready", "running", "analyzed"}:
            raise DomainError("adaptation_plan_required", "请先确认改编计划。", status=409)
        source = self.sources.get(item["work_id"], item["source_version_id"])
        chapter = next((c for c in source["chapters"] if c["id"] == chapter_id), None)
        if not chapter or chapter_id not in item["selected_chapter_ids"]:
            raise NotFound("adaptation_chapter", chapter_id)
        system, user = build_chapter_prompt(source=source, chapter=chapter, character_mapping=item["plan"].get("character_mapping", {}), unfinished=source.get("completion_state") != "complete")
        provider = self.service.provider
        context = {"source_version": source["id"], "chapter": chapter, "brief": {"characters": list(item["plan"].get("character_mapping", {}).keys())}, "scene_contract": {"title": chapter["title"], "goal": "将本章已提供内容转换为连续剧本候选", "location": "原文既有地点"}, "runtime_character_cards": [], "character_mapping": item["plan"].get("character_mapping", {}), "unfinished": source.get("completion_state") != "complete", "adaptation_prompt": system, "user_prompt": user}
        with self.repo.transaction() as c:
            row = c.execute("SELECT budget_json FROM adaptations WHERE id=?", (adaptation_id,)).fetchone()
            budget = json.loads(row[0] or "{}")
            if int(budget.get("reserved_calls") or 0) >= int(budget.get("max_calls") or 0):
                raise DomainError("adaptation_budget_exhausted", "本次改编任务的调用预算已用尽。", status=409)
            budget["reserved_calls"] = int(budget.get("reserved_calls") or 0) + 1
            c.execute("UPDATE adaptations SET budget_json=?,updated_at=? WHERE id=?", (canonical_json(budget), now(), adaptation_id))
        try:
            call = provider._call_llm(system, user) if hasattr(provider, "_call_llm") else None
            raw_text = call.text if call is not None else provider.generate_scene(context)
        except Exception:
            with self.repo.transaction() as c:
                row = c.execute("SELECT budget_json FROM adaptations WHERE id=?", (adaptation_id,)).fetchone()
                budget = json.loads(row[0] or "{}")
                budget["reserved_calls"] = max(0, int(budget.get("reserved_calls") or 0) - 1)
                c.execute("UPDATE adaptations SET budget_json=?,updated_at=? WHERE id=?", (canonical_json(budget), now(), adaptation_id))
            raise
        structured = {}
        try:
            parsed = json.loads(raw_text)
            if isinstance(parsed, dict):
                structured = parsed
        except (TypeError, json.JSONDecodeError):
            pass
        text = str(structured.get("text") or raw_text).strip()
        refs = structured.get("source_refs") if isinstance(structured.get("source_refs"), list) else [
            {"paragraph_id": paragraph["id"], "quote": paragraph["text"][:160]}
            for paragraph in chapter.get("paragraphs", [])
        ]
        candidate = {"schema_version": "adaptation-chapter/1.0", "text": text, "source_version_id": source["id"], "source_chapter_id": chapter_id, "formal": False, "prompt_contract": "adaptation/1.0", "source_refs": refs, "deviations": structured.get("deviations", []), "open_threads": structured.get("open_threads", [])}
        candidate_id = new_id("proposal")
        candidate_uri, candidate_hash = self.repo.atomic_write_text(f"artifacts/proposals/{candidate_id}.json", canonical_json(candidate) + "\n")
        source_digest = next((item["content_digest"] for item in source["chapters"] if item["id"] == chapter_id), "")
        with self.repo.transaction() as c:
            chapter_row = c.execute("SELECT id FROM adaptation_chapters WHERE adaptation_id=? AND source_chapter_id=?", (adaptation_id, chapter_id)).fetchone()
            if not chapter_row:
                raise NotFound("adaptation_chapter", chapter_id)
            c.execute("UPDATE adaptation_chapters SET candidate_json=?,status='candidate',updated_at=? WHERE adaptation_id=? AND source_chapter_id=?", (canonical_json({**candidate, "proposal_id": candidate_id}), now(), adaptation_id, chapter_id))
            c.execute("INSERT INTO proposals (id,work_id,kind,scope_type,scope_id,base_revision_id,candidate_uri,candidate_hash,diff_json,evidence_json,risk,status,provider_json,created_at,decided_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (candidate_id, item["work_id"], "adaptation_chapter", "adaptation_chapter", chapter_row[0], None, candidate_uri, candidate_hash, canonical_json({"format": "adaptation-chapter/1.0", "source_refs": refs}), canonical_json({"source_version_id": source["id"], "source_chapter_id": chapter_id, "source_digest": source_digest}), "medium", "pending", canonical_json(provider.descriptor()), now(), None))
        return {"adaptation": self.get(adaptation_id), "proposal_id": candidate_id, "candidate": candidate}
