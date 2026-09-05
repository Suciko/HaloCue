from __future__ import annotations

import json
import mimetypes
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .errors import DomainError
from .service import WritingService


class WritingRequestHandler(BaseHTTPRequestHandler):
    service: WritingService
    static_dir: Path

    def log_message(self, format, *args):
        return

    def _headers(self, status: int, content_type: str, length: int):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'")
        self.end_headers()

    def _json(self, value, status=200):
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(body))
        self.wfile.write(body)

    def _bytes(self, body: bytes, content_type: str, status: int = 200):
        self._headers(status, content_type, len(body))
        self.wfile.write(body)

    def _download(self, body: bytes, filename: str):
        self.send_response(200)
        self.send_header("Content-Type", "application/vnd.halocue.writing-backup+zip")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _proxy_production_get(self):
        parsed = urlparse(self.path)
        upstream_path = parsed.path.removeprefix("/production")
        upstream_url = f"{self.service.production_url}{upstream_path}"
        if parsed.query:
            upstream_url += f"?{parsed.query}"
        request = urllib.request.Request(upstream_url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                body = response.read()
                content_type = response.headers.get("Content-Type", "application/json; charset=utf-8")
                return self._response_bytes(response.status, content_type, body)
        except urllib.error.HTTPError as exc:
            body = exc.read()
            content_type = exc.headers.get("Content-Type", "application/json; charset=utf-8") if exc.headers else "application/json; charset=utf-8"
            return self._response_bytes(exc.code, content_type, body)
        except (urllib.error.URLError, TimeoutError) as exc:
            return self._json({
                "ok": False,
                "error": {
                    "code": "production_unavailable",
                    "message": "AA 制作服务当前不可用，素材条目暂时无法读取。",
                    "details": {"reason": str(exc)},
                },
            }, status=503)

    def _response_bytes(self, status: int, content_type: str, body: bytes):
        self._headers(status, content_type, len(body))
        self.wfile.write(body)

    def _body(self, max_bytes: int = 8_000_000):
        length = int(self.headers.get("Content-Length", "0"))
        if length > max_bytes:
            raise DomainError("payload_too_large", "请求内容过大。", status=413)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DomainError("invalid_json", "请求不是有效 JSON。") from exc

    def _parts(self):
        return [item for item in urlparse(self.path).path.split("/") if item]

    def do_GET(self):
        try:
            parts = self._parts()
            if parts == ["api", "v1", "health"]:
                return self._json(self.service.health())
            if parts == ["api", "v1", "capabilities"]:
                return self._json({"ok": True, "data": self.service.capabilities()})
            if parts == ["api", "v1", "agent-tools"]:
                return self._json({"ok": True, "data": self.service.agent_tool_catalog()})
            if parts == ["api", "v1", "official-references", "search"]:
                query = parse_qs(urlparse(self.path).query)
                return self._json({"ok": True, "data": self.service.search_official_references(query.get("q", [""])[0], query.get("limit", [12])[0])})
            if parts == ["api", "v1", "resources", "catalog"]:
                return self._json({"ok": True, "data": self.service.resource_catalog_public()})
            if parts == ["api", "v1", "resources", "search"]:
                query = parse_qs(urlparse(self.path).query)
                if query.get("facets", [""])[0] == "1":
                    return self._json({"ok": True, "data": self.service.resource_catalog_facets(query.get("kind", ["backgrounds"])[0])})
                keys = [
                    value.strip()
                    for item in query.get("keys", [])
                    for value in item.split(",")
                    if value.strip()
                ]
                if keys:
                    return self._json({"ok": True, "data": self.service.lookup_resource_catalog(query.get("kind", ["backgrounds"])[0], keys)})
                return self._json({"ok": True, "data": self.service.search_resource_catalog(query.get("kind", ["backgrounds"])[0], query.get("q", [""])[0], query.get("limit", [24])[0])})
            if parts == ["api", "v1", "works"]:
                return self._json({"ok": True, "data": self.service.list_works()})
            if len(parts) == 5 and parts[:3] == ["api", "v1", "works"] and parts[4] == "source":
                query = parse_qs(urlparse(self.path).query)
                return self._json({"ok": True, "data": self.service.sources.get(parts[3], query.get("version_id", [None])[0])})
            if len(parts) == 5 and parts[:3] == ["api", "v1", "works"] and parts[4] == "adaptations":
                query = parse_qs(urlparse(self.path).query)
                ids = query.get("id", [])
                return self._json({"ok": True, "data": [self.service.adaptations.get(item) for item in ids] if ids else []})
            if len(parts) == 6 and parts[:3] == ["api", "v1", "works"] and parts[4] == "adaptations":
                return self._json({"ok": True, "data": self.service.adaptations.get(parts[5])})
            if len(parts) == 4 and parts[:3] == ["api", "v1", "intent-plans"]:
                return self._json({"ok": True, "data": self.service.get_intent_plan(parts[3])})
            if parts == ["api", "v1", "settings", "writing-model"]:
                return self._json(self.service.writing_model_settings_public())
            if parts == ["api", "v1", "settings", "preferences"]:
                return self._json(self.service.user_preferences())
            if parts == ["api", "v1", "settings", "diagnostics"]:
                return self._json(self.service.system_diagnostics())
            if parts == ["api", "v1", "settings", "backups", "export"]:
                filename, body, _ = self.service.export_writing_backup()
                return self._download(body, filename)
            if parts == ["api", "v1", "settings", "conversations"]:
                query = parse_qs(urlparse(self.path).query)
                return self._json({"ok": True, "data": self.service.list_archived_conversations(query.get("q", [""])[0])})
            if len(parts) == 7 and parts[:3] == ["api", "v1", "works"] and parts[4] == "attachments" and parts[6] == "content":
                content_type, body = self.service.get_conversation_attachment(parts[3], parts[5])
                return self._bytes(body, content_type)
            if len(parts) == 5 and parts[:3] == ["api", "v1", "works"] and parts[4] == "user-status":
                return self._json({"ok": True, "data": self.service.get_user_work_status(parts[3])})
            if len(parts) == 4 and parts[:3] == ["api", "v1", "works"]:
                return self._json({"ok": True, "data": self.service.get_work(parts[3])})
            if len(parts) == 5 and parts[:3] == ["api", "v1", "releases"] and parts[4] == "production-assets":
                return self._json({"ok": True, "data": self.service.production_asset_status(parts[3])})
            if parts[:2] == ["production", "api"]:
                return self._proxy_production_get()
            if len(parts) == 5 and parts[:3] == ["api", "v1", "works"] and parts[4] == "harness":
                query = parse_qs(urlparse(self.path).query)
                return self._json({
                    "ok": True,
                    "data": self.service.get_harness_status(
                        parts[3],
                        scope_type=query.get("scope_type", ["work"])[0],
                        scope_id=query.get("scope_id", [None])[0],
                    ),
                })
            if len(parts) == 5 and parts[:3] == ["api", "v1", "works"] and parts[4] == "current-projection":
                return self._json({"ok": True, "data": self.service.get_current_projection(parts[3])})
            if len(parts) == 5 and parts[:3] == ["api", "v1", "works"] and parts[4] == "doctor":
                return self._json({"ok": True, "data": self.service.diagnose_writing_harness(parts[3])})
            if len(parts) == 5 and parts[:3] == ["api", "v1", "works"] and parts[4] == "agent-usage":
                return self._json({"ok": True, "data": self.service.agent_usage(parts[3])})
            if len(parts) == 5 and parts[:3] == ["api", "v1", "works"] and parts[4] == "memories":
                return self._json({"ok": True, "data": self.service.list_memories(parts[3])})
            if len(parts) == 5 and parts[:3] == ["api", "v1", "works"] and parts[4] == "projection-search":
                query = parse_qs(urlparse(self.path).query)
                kinds = [
                    value.strip()
                    for item in query.get("kind", [])
                    for value in item.split(",")
                    if value.strip()
                ]
                return self._json({
                    "ok": True,
                    "data": self.service.search_commit_projections(
                        parts[3],
                        query.get("q", [""])[0],
                        artifact_kinds=kinds or None,
                        limit=query.get("limit", [8])[0],
                    ),
                })
            if len(parts) == 6 and parts[:3] == ["api", "v1", "works"] and parts[4] == "agent-runs":
                return self._json({"ok": True, "data": self.service.get_agent_run(parts[3], parts[5])})
            if len(parts) == 7 and parts[:3] == ["api", "v1", "works"] and parts[4] == "threads" and parts[6] == "agent-presentation":
                query = parse_qs(urlparse(self.path).query)
                return self._json({
                    "ok": True,
                    "data": self.service.get_agent_presentation(
                        parts[3], parts[5],
                        limit=query.get("limit", [100])[0],
                        cursor=query.get("cursor", [None])[0],
                    ),
                })
            if len(parts) == 6 and parts[:3] == ["api", "v1", "works"] and parts[4] == "agent-jobs":
                return self._json({"ok": True, "data": self.service.get_agent_job(parts[3], parts[5])})
            if len(parts) == 6 and parts[:3] == ["api", "v1", "works"] and parts[4] == "commit-projections":
                return self._json({"ok": True, "data": self.service.get_commit_projection(parts[3], parts[5])})
            if len(parts) == 7 and parts[:3] == ["api", "v1", "works"] and parts[4] == "proposals" and parts[6] == "impact":
                return self._json({"ok": True, "data": self.service.get_proposal_impact(parts[3], parts[5])})
            if len(parts) == 7 and parts[:3] == ["api", "v1", "works"] and parts[4] == "scenes" and parts[6] == "asset-suggestions":
                return self._json({"ok": True, "data": self.service.suggest_scene_assets(parts[3], parts[5])})
            if len(parts) == 9 and parts[:3] == ["api", "v1", "works"] and parts[4] == "artifacts" and parts[6] == "revisions" and parts[8] == "compare":
                query = parse_qs(urlparse(self.path).query)
                return self._json({
                    "ok": True,
                    "data": self.service.compare_artifact_revisions(
                        parts[3], parts[5], parts[7], query.get("against", [None])[0]
                    ),
                })
            if len(parts) == 4 and parts[:3] == ["api", "v1", "releases"]:
                return self._json({"ok": True, "data": self.service.get_release(parts[3])})
            return self._static(urlparse(self.path).path)
        except DomainError as exc:
            self._error(exc)
        except Exception as exc:
            self._error(DomainError("internal_error", "写作服务发生内部错误。", status=500, details={"type": type(exc).__name__}))

    def do_POST(self):
        try:
            parts = self._parts()
            body_limit = 128_000_000 if parts in (
                ["api", "v1", "settings", "backups", "inspect"],
                ["api", "v1", "settings", "backups", "restore"],
            ) else 48_000_000 if (
                parts in (
                    ["api", "v1", "imports", "aap:preview"],
                    ["api", "v1", "imports", "aap:stage"],
                    ["api", "v1", "imports", "aap:adopt"],
                    ["api", "v1", "imports", "story:preview"],
                    ["api", "v1", "imports", "story:stage"],
                    ["api", "v1", "imports", "story:adopt"],
                )
                or (len(parts) == 7 and parts[:3] == ["api", "v1", "works"] and parts[4] == "threads" and parts[6] == "attachments")
            ) else 8_000_000
            payload = self._body(body_limit)
            result = None
            if parts == ["api", "v1", "settings", "writing-model:activate"]:
                result = self.service.activate_writing_model(payload)
                return self._json(result)
            if parts == ["api", "v1", "settings", "writing-model"]:
                result = self.service.configure_writing_model(payload)
                return self._json(result)
            if parts == ["api", "v1", "settings", "writing-model", "fetch-models"]:
                result = self.service.fetch_writing_models(payload)
                return self._json({"ok": True, "models": result})
            if parts == ["api", "v1", "settings", "writing-model", "test"]:
                result = self.service.test_writing_model(payload)
                return self._json(result)
            if parts == ["api", "v1", "settings", "preferences"]:
                result = self.service.save_user_preferences(payload)
                return self._json(result)
            if parts == ["api", "v1", "settings", "feedback", "sync"]:
                return self._json({"ok": True, "data": self.service.sync_pending_feedback()})
            if parts == ["api", "v1", "settings", "backups", "inspect"]:
                return self._json({"ok": True, "data": self.service.inspect_writing_backup(payload)})
            if parts == ["api", "v1", "settings", "backups", "restore"]:
                return self._json({"ok": True, "data": self.service.restore_writing_backup(payload)})
            if parts == ["api", "v1", "resources", "catalog:import"]:
                return self._json({"ok": True, "data": self.service.import_resource_catalog(payload)})
            if parts == ["api", "v1", "resources", "overrides"]:
                return self._json({"ok": True, "data": self.service.save_resource_override(payload)})
            if parts == ["api", "v1", "imports", "aap:preview"]:
                return self._json({"ok": True, "data": self.service.preview_aap_import(payload)})
            if parts == ["api", "v1", "imports", "aap:stage"]:
                return self._json({"ok": True, "data": self.service.stage_aap_import(payload)}, 201)
            if parts == ["api", "v1", "imports", "aap:adopt"]:
                return self._json({"ok": True, "data": self.service.adopt_aap_import(payload)}, 201)
            if parts == ["api", "v1", "imports", "story:preview"]:
                return self._json({"ok": True, "data": self.service.preview_story_import(payload)})
            if parts == ["api", "v1", "imports", "story:stage"]:
                return self._json({"ok": True, "data": self.service.stage_story_import(payload)}, 201)
            if parts == ["api", "v1", "imports", "story:adopt"]:
                return self._json({"ok": True, "data": self.service.adopt_story_import(payload)}, 201)
            if parts == ["api", "v1", "feedback"]:
                result = self.service.submit_feedback(payload)
                return self._json({"ok": True, "data": result}, 201)
            if parts == ["api", "v1", "works"]:
                result = self.service.create_work(payload)
                return self._json({"ok": True, "data": result}, 201)
            if len(parts) == 5 and parts[:3] == ["api", "v1", "works"] and parts[4] in {"source:preview", "source:update"}:
                method = self.service.sources.preview if parts[4] == "source:preview" else self.service.sources.apply
                return self._json({"ok": True, "data": method(parts[3], payload)})
            if len(parts) == 5 and parts[:3] == ["api", "v1", "works"] and parts[4] == "adaptations":
                return self._json({"ok": True, "data": self.service.adaptations.create(parts[3], payload)}, 201)
            if len(parts) == 7 and parts[:3] == ["api", "v1", "works"] and parts[4] == "adaptations" and parts[6] == "plan:approve":
                return self._json({"ok": True, "data": self.service.adaptations.approve_plan(parts[5], payload)})
            if len(parts) == 7 and parts[:3] == ["api", "v1", "works"] and parts[4] == "adaptations" and parts[6] == "run":
                return self._json({"ok": True, "data": self.service.adaptations.run(parts[5], payload)}, 202)
            if len(parts) == 9 and parts[:3] == ["api", "v1", "works"] and parts[4] == "adaptations" and parts[6] == "chapters" and parts[8] == "candidate:generate":
                return self._json({"ok": True, "data": self.service.adaptations.generate_chapter_candidate(parts[5], parts[7], payload)}, 202)
            if parts == ["api", "v1", "intent"]:
                result = self.service.plan_intent(payload)
                return self._json({"ok": True, "data": result}, 202)
            # The public intent confirmation contract is /intent-plans/{id}:confirm.
            # Keep the idempotent route shape explicit; a plan id is one path segment.
            if len(parts) == 4 and parts[:3] == ["api", "v1", "intent-plans"] and parts[3].endswith(":confirm"):
                result = self.service.confirm_intent(parts[3][:-8], payload)
                return self._json({"ok": True, "data": result}, 202)
            if len(parts) == 4 and parts[:3] == ["api", "v1", "intent-plans"] and parts[3].endswith(":retry"):
                result = self.service.retry_intent(parts[3][:-6], payload)
                return self._json({"ok": True, "data": result}, 202)
            if len(parts) == 5 and parts[:3] == ["api", "v1", "works"] and parts[4] == "threads":
                result = self.service.create_conversation_thread(parts[3], payload)
                return self._json({"ok": True, "data": result}, 201)
            if len(parts) == 5 and parts[:3] == ["api", "v1", "works"] and parts[4] == "agent-jobs":
                result = self.service.enqueue_agent_operation(parts[3], payload)
                return self._json({"ok": True, "data": result}, 202)
            if len(parts) == 6 and parts[:3] == ["api", "v1", "works"] and parts[4] == "commit-projections" and parts[5].endswith(":ensure"):
                result = self.service.ensure_commit_projection(parts[3], parts[5][:-7])
                return self._json({"ok": True, "data": result})
            if len(parts) == 6 and parts[:3] == ["api", "v1", "works"] and parts[4] == "commit-projections" and parts[5].endswith(":run"):
                result = self.service.run_commit_projection(
                    parts[3], parts[5][:-4], payload.get("projection_kinds")
                )
                return self._json({"ok": True, "data": result})
            if len(parts) == 6 and parts[:3] == ["api", "v1", "works"] and parts[4] == "commit-projections" and parts[5].endswith(":retry"):
                result = self.service.retry_commit_projection(parts[3], parts[5][:-6])
                return self._json({"ok": True, "data": result})
            if (
                len(parts) == 8
                and parts[:3] == ["api", "v1", "works"]
                and parts[4] == "commit-projections"
                and parts[6] == "items"
                and parts[7].endswith(":skip")
            ):
                result = self.service.skip_commit_projection(
                    parts[3],
                    parts[5],
                    parts[7][:-5],
                    reason=str(payload.get("reason") or ""),
                )
                return self._json({"ok": True, "data": result})
            if len(parts) == 6 and parts[:3] == ["api", "v1", "works"] and parts[4] == "threads":
                result = self.service.update_conversation_thread(parts[3], parts[5], payload)
                return self._json({"ok": True, "data": result})
            if len(parts) == 7 and parts[:3] == ["api", "v1", "works"] and parts[4] == "threads" and parts[6] == "attachments":
                result = self.service.create_conversation_attachment(parts[3], parts[5], payload)
                return self._json({"ok": True, "data": result}, 201)
            if len(parts) == 7 and parts[:3] == ["api", "v1", "works"] and parts[4] == "threads" and parts[6] == "messages:enqueue":
                result = self.service.enqueue_conversation_message(parts[3], parts[5], payload)
                return self._json({"ok": True, "data": result}, 202)
            if len(parts) == 5 and parts[:3] == ["api", "v1", "works"] and parts[4] == "brief":
                result = self.service.save_brief(parts[3], payload)
            elif len(parts) == 5 and parts[:3] == ["api", "v1", "works"] and parts[4] == "blueprint:generate":
                result = self.service.generate_blueprint(parts[3], payload)
            elif len(parts) == 5 and parts[:3] == ["api", "v1", "works"] and parts[4] == "blueprint:confirm":
                result = self.service.confirm_blueprint(parts[3], payload)
            elif len(parts) == 5 and parts[:3] == ["api", "v1", "works"] and parts[4] == "canon":
                result = self.service.save_work_canon(parts[3], payload)
            elif len(parts) == 5 and parts[:3] == ["api", "v1", "works"] and parts[4] == "character-cards":
                result = self.service.save_character_card(parts[3], payload)
            elif len(parts) == 5 and parts[:3] == ["api", "v1", "works"] and parts[4] == "character-cards:validate":
                result = self.service.validate_character_card_import(parts[3], payload)
            elif len(parts) == 5 and parts[:3] == ["api", "v1", "works"] and parts[4] == "character-cards:import":
                result = self.service.import_character_card(parts[3], payload)
            elif len(parts) == 7 and parts[:3] == ["api", "v1", "works"] and parts[4] == "character-cards" and parts[6] == "archive":
                result = self.service.archive_character_card(parts[3], parts[5], payload)
            elif len(parts) == 7 and parts[:3] == ["api", "v1", "works"] and parts[4] == "character-cards" and parts[6] == "restore":
                result = self.service.restore_character_card(parts[3], parts[5], payload)
            elif len(parts) == 5 and parts[:3] == ["api", "v1", "works"] and parts[4] == "world-bible":
                result = self.service.save_world_bible(parts[3], payload)
            elif len(parts) == 5 and parts[:3] == ["api", "v1", "works"] and parts[4] == "world-bible:starter":
                result = self.service.apply_ba_world_starter(parts[3], payload)
            elif len(parts) == 5 and parts[:3] == ["api", "v1", "works"] and parts[4] == "world-bible:validate":
                result = self.service.validate_world_card_import(parts[3], payload)
            elif len(parts) == 5 and parts[:3] == ["api", "v1", "works"] and parts[4] == "world-bible:import":
                result = self.service.import_world_card(parts[3], payload)
            elif len(parts) == 5 and parts[:3] == ["api", "v1", "works"] and parts[4] == "reference-files":
                result = self.service.create_reference_file(parts[3], payload)
            elif len(parts) == 5 and parts[:3] == ["api", "v1", "works"] and parts[4] == "official-references:import":
                result = self.service.import_official_reference(parts[3], payload)
            elif len(parts) == 5 and parts[:3] == ["api", "v1", "works"] and parts[4] == "volumes":
                result = self.service.create_volume(parts[3], payload)
            elif len(parts) == 5 and parts[:3] == ["api", "v1", "works"] and parts[4] == "chapters":
                result = self.service.create_chapter(parts[3], payload)
            elif len(parts) == 5 and parts[:3] == ["api", "v1", "works"] and parts[4] == "structure:reorder":
                result = self.service.reorder_structure(parts[3], payload)
            elif len(parts) == 5 and parts[:3] == ["api", "v1", "works"] and parts[4] == "writing-target":
                result = self.service.set_writing_target(parts[3], payload)
            elif len(parts) == 7 and parts[:3] == ["api", "v1", "works"] and parts[4] == "chapters" and parts[6] == "scenes":
                result = self.service.create_scene(parts[3], parts[5], payload)
            elif len(parts) == 7 and parts[:3] == ["api", "v1", "works"] and parts[4] == "chapters" and parts[6] == "memory:sweep":
                result = self.service.sweep_chapter_memory(parts[3], parts[5], payload)
            elif len(parts) == 7 and parts[:3] == ["api", "v1", "works"] and parts[4] == "scenes" and parts[6] == "context:assemble":
                result = self.service.assemble_context(parts[3], parts[5])
            elif len(parts) == 7 and parts[:3] == ["api", "v1", "works"] and parts[4] == "scenes" and parts[6] == "context:configure":
                result = self.service.configure_scene_context(parts[3], parts[5], payload)
            elif len(parts) == 7 and parts[:3] == ["api", "v1", "works"] and parts[4] == "scenes" and parts[6] == "contract":
                result = self.service.update_scene_contract(parts[3], parts[5], payload)
            elif len(parts) == 7 and parts[:3] == ["api", "v1", "works"] and parts[4] == "scenes" and parts[6] == "asset-references":
                result = self.service.set_scene_asset_references(parts[3], parts[5], payload)
            elif len(parts) == 7 and parts[:3] == ["api", "v1", "works"] and parts[4] == "scenes" and parts[6] == "manuscript":
                result = self.service.save_scene_manuscript(parts[3], parts[5], payload)
            elif len(parts) == 7 and parts[:3] == ["api", "v1", "works"] and parts[4] == "scenes" and parts[6] == "candidate:generate":
                result = self.service.generate_scene_candidate(parts[3], parts[5], payload)
            elif len(parts) == 7 and parts[:3] == ["api", "v1", "works"] and parts[4] == "scenes" and parts[6] == "agent:run":
                result = self.service.run_scene_agent(parts[3], parts[5], payload)
            elif len(parts) == 7 and parts[:3] == ["api", "v1", "works"] and parts[4] == "scenes" and parts[6] == "agent:rewrite":
                result = self.service.run_scene_rewrite_agent(parts[3], parts[5], payload)
            elif len(parts) == 7 and parts[:3] == ["api", "v1", "works"] and parts[4] == "scenes" and parts[6] == "review":
                result = self.service.review_scene(parts[3], parts[5], payload)
            elif len(parts) == 7 and parts[:3] == ["api", "v1", "works"] and parts[4] == "scenes" and parts[6] == "memory-proposals:generate":
                result = self.service.generate_memory_proposal(parts[3], parts[5], payload)
            elif len(parts) == 7 and parts[:3] == ["api", "v1", "works"] and parts[4] == "scenes" and parts[6] == "memory:skip":
                result = self.service.skip_scene_memory_maintenance(parts[3], parts[5], payload)
            elif len(parts) == 7 and parts[:3] == ["api", "v1", "works"] and parts[4] == "memories" and parts[6] == "archive":
                result = self.service.archive_memory(parts[3], parts[5], payload)
            elif len(parts) == 7 and parts[:3] == ["api", "v1", "works"] and parts[4] == "memories" and parts[6] == "restore":
                result = self.service.restore_memory(parts[3], parts[5], payload)
            elif len(parts) == 7 and parts[:3] == ["api", "v1", "works"] and parts[4] == "threads" and parts[6] == "messages":
                result = self.service.post_conversation_message(parts[3], parts[5], payload)
            elif len(parts) == 7 and parts[:3] == ["api", "v1", "works"] and parts[4] == "threads" and parts[6] == "scene-proposal:generate":
                result = self.service.generate_scene_proposal_from_conversation(parts[3], parts[5], payload)
            elif len(parts) == 7 and parts[:3] == ["api", "v1", "works"] and parts[4] == "agent-runs" and parts[6] == "retry":
                result = self.service.retry_agent_run(parts[3], parts[5], payload)
            elif len(parts) == 6 and parts[:3] == ["api", "v1", "works"] and parts[4] == "agent-runs" and parts[5].endswith(":cancel"):
                result = self.service.cancel_agent_run(parts[3], parts[5][:-7])
            elif len(parts) == 6 and parts[:3] == ["api", "v1", "works"] and parts[4] == "agent-runs" and parts[5].endswith(":retry"):
                result = self.service.retry_agent_run(parts[3], parts[5][:-6], payload)
            elif len(parts) == 6 and parts[:3] == ["api", "v1", "works"] and parts[4] == "agent-runs" and parts[5].endswith(":redirect"):
                result = self.service.redirect_agent_run(parts[3], parts[5][:-9], payload)
            elif len(parts) == 6 and parts[:3] == ["api", "v1", "works"] and parts[4] == "agent-jobs" and parts[5].endswith(":cancel"):
                result = self.service.cancel_agent_job(parts[3], parts[5][:-7])
            elif len(parts) == 7 and parts[:3] == ["api", "v1", "works"] and parts[4] == "threads" and parts[6] == "settings":
                result = self.service.update_conversation_settings(parts[3], parts[5], payload)
            elif len(parts) == 7 and parts[:3] == ["api", "v1", "works"] and parts[4] == "threads" and parts[6] == "proposal:organize":
                result = self.service.organize_conversation_proposal(parts[3], parts[5], payload)
            elif len(parts) == 7 and parts[:3] == ["api", "v1", "works"] and parts[4] == "threads" and parts[6] == "knowledge:propose":
                result = self.service.propose_conversation_knowledge(parts[3], parts[5], payload)
            elif len(parts) == 7 and parts[:3] == ["api", "v1", "works"] and parts[4] == "findings" and parts[6] == "resolve":
                result = self.service.resolve_review_finding(parts[3], parts[5], payload)
            elif len(parts) == 7 and parts[:3] == ["api", "v1", "works"] and parts[4] == "proposals" and parts[6] == "accept":
                result = self.service.accept_proposal(parts[3], parts[5], payload)
            elif len(parts) == 7 and parts[:3] == ["api", "v1", "works"] and parts[4] == "proposals" and parts[6] == "reject":
                result = self.service.reject_proposal(parts[3], parts[5], payload)
            elif len(parts) == 5 and parts[:3] == ["api", "v1", "works"] and parts[4] == "releases:freeze":
                result = self.service.freeze_release(parts[3], payload)
            elif len(parts) == 5 and parts[:3] == ["api", "v1", "works"] and parts[4] == "release:review":
                result = self.service.review_release(parts[3], payload)
            elif len(parts) == 5 and parts[:3] == ["api", "v1", "works"] and parts[4] == "continuity:review":
                result = self.service.review_continuity(parts[3], payload)
            elif len(parts) == 5 and parts[:3] == ["api", "v1", "releases"] and parts[4] == "handoff":
                result = self.service.handoff_release(parts[3])
            elif len(parts) == 5 and parts[:3] == ["api", "v1", "releases"] and parts[4] == "production-assets:reconcile":
                result = self.service.reconcile_production_asset_copies(parts[3], payload or None)
            else:
                raise DomainError("route_not_found", "接口不存在。", status=404)
            return self._json({"ok": True, "data": result})
        except DomainError as exc:
            self._error(exc)
        except Exception as exc:
            self._error(DomainError("internal_error", "写作服务发生内部错误。", status=500, details={"type": type(exc).__name__}))

    def _error(self, exc: DomainError):
        self._json({"ok": False, "error": {"code": exc.code, "message": exc.message, "details": exc.details}}, exc.status)

    def _static(self, path: str):
        relative = "index.html" if path in ("", "/") else path.lstrip("/")
        target = (self.static_dir / relative).resolve()
        if self.static_dir not in target.parents or not target.is_file():
            raise DomainError("not_found", "页面不存在。", status=404)
        body = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in ("application/javascript", "application/json"):
            content_type += "; charset=utf-8"
        self._headers(200, content_type, len(body))
        self.wfile.write(body)


def make_handler(service: WritingService, static_dir: Path):
    service.start()

    class Handler(WritingRequestHandler):
        pass

    Handler.service = service
    Handler.static_dir = static_dir.resolve()
    return Handler
