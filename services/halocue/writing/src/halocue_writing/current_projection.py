from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from .errors import NotFound
from .repository import Repository, canonical_json, sha256_text


CURRENT_PROJECTION_KINDS = (
    "character_card",
    "world_bible",
    "work_canon",
    "story_structure",
)


class CurrentWorkProjection:
    """Build disposable work views from current immutable Revisions only."""

    def __init__(self, repository: Repository):
        self.repository = repository

    def get(self, work_id: str) -> dict[str, Any]:
        with self.repository.connect() as connection:
            if not connection.execute(
                "SELECT 1 FROM works WHERE id=?", (work_id,)
            ).fetchone():
                raise NotFound("work", work_id)
            placeholders = ",".join("?" for _ in CURRENT_PROJECTION_KINDS)
            rows = connection.execute(
                f"""SELECT artifact.id AS artifact_id,artifact.kind AS artifact_kind,
                           artifact.scope_type,artifact.scope_id,artifact.current_revision_id,
                           revision.id AS revision_id,revision.content_uri,revision.content_hash,
                           revision.schema_version AS revision_schema_version,
                           revision.ordinal AS revision_ordinal
                    FROM artifacts AS artifact
                    LEFT JOIN revisions AS revision
                      ON revision.id=artifact.current_revision_id
                    WHERE artifact.work_id=?
                      AND artifact.kind IN ({placeholders})
                      AND artifact.current_revision_id IS NOT NULL
                    ORDER BY artifact.kind,artifact.scope_id,artifact.id""",
                (work_id, *CURRENT_PROJECTION_KINDS),
            ).fetchall()

        declared_sources = [self._declared_source(row) for row in rows]
        source_set_digest = sha256_text(canonical_json(declared_sources))
        source_revisions: list[dict[str, Any]] = []
        unavailable_sources: list[dict[str, Any]] = []
        loaded: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for row in rows:
            source = self._public_source(row)
            try:
                if not row["revision_id"] or not row["content_uri"]:
                    raise _Unavailable("revision_missing")
                text = self.repository.read_text(row["content_uri"])
                actual_hash = sha256_text(text)
                if actual_hash != row["content_hash"]:
                    raise _Unavailable("content_hash_mismatch", actual_hash=actual_hash)
                content = json.loads(text)
                if not isinstance(content, dict):
                    raise _Unavailable("content_contract_invalid")
            except _Unavailable as exc:
                unavailable = {**source, "reason": exc.reason}
                if exc.actual_hash:
                    unavailable["actual_hash"] = exc.actual_hash
                unavailable_sources.append(unavailable)
                source_revisions.append({**source, "available": False, "reason": exc.reason})
            except json.JSONDecodeError:
                unavailable_sources.append({**source, "reason": "content_json_invalid"})
                source_revisions.append({**source, "available": False, "reason": "content_json_invalid"})
            except (OSError, UnicodeError, ValueError, TypeError):
                unavailable_sources.append({**source, "reason": "content_unreadable"})
                source_revisions.append({**source, "available": False, "reason": "content_unreadable"})
            else:
                source_revisions.append({**source, "available": True})
                loaded.append((source, content))

        graph, timeline = self._knowledge_views(loaded)
        structure = self._structure_view(loaded)
        return {
            "schema_version": "current-work-projection/1.0",
            "work_id": work_id,
            "knowledge_graph": graph,
            "timeline": timeline,
            "story_structure": structure,
            "source_revisions": source_revisions,
            "source_set_digest": source_set_digest,
            "complete": not unavailable_sources,
            "unavailable_sources": unavailable_sources,
        }

    @staticmethod
    def _declared_source(row) -> dict[str, Any]:
        return {
            "artifact_id": row["artifact_id"],
            "artifact_kind": row["artifact_kind"],
            "scope_type": row["scope_type"],
            "scope_id": row["scope_id"],
            "revision_id": row["current_revision_id"],
            "content_hash": row["content_hash"],
        }

    @staticmethod
    def _public_source(row) -> dict[str, Any]:
        return {
            "artifact_id": row["artifact_id"],
            "artifact_kind": row["artifact_kind"],
            "scope_type": row["scope_type"],
            "scope_id": row["scope_id"],
            "revision_id": row["current_revision_id"],
            "content_hash": row["content_hash"],
            "schema_version": row["revision_schema_version"],
            "ordinal": row["revision_ordinal"],
        }

    @staticmethod
    def _item_source(source: dict[str, Any], item_id: str) -> dict[str, Any]:
        return {
            "artifact_id": source["artifact_id"],
            "artifact_kind": source["artifact_kind"],
            "scope_type": source["scope_type"],
            "scope_id": source["scope_id"],
            "revision_id": source["revision_id"],
            "content_hash": source["content_hash"],
            "item_id": item_id,
        }

    def _knowledge_views(
        self, loaded: list[tuple[dict[str, Any], dict[str, Any]]]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        characters: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        world_sources: list[tuple[dict[str, Any], dict[str, Any]]] = []
        canon_sources: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for source, content in loaded:
            if source["artifact_kind"] == "character_card":
                characters[source["scope_id"]] = (source, content)
            elif source["artifact_kind"] == "world_bible":
                world_sources.append((source, content))
            elif source["artifact_kind"] == "work_canon":
                canon_sources.append((source, content))

        active_characters = {
            card_id: value
            for card_id, value in characters.items()
            if value[1].get("status", "active") != "archived"
        }
        name_index: dict[str, set[str]] = defaultdict(set)
        for card_id, (_source, card) in active_characters.items():
            for value in (
                card.get("name"),
                card.get("canonical_name"),
                *(card.get("aliases") if isinstance(card.get("aliases"), list) else []),
            ):
                normalized = self._identity(value)
                if normalized:
                    name_index[normalized].add(card_id)

        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []

        for card_id, (source, card) in active_characters.items():
            node_id = f"character:{card_id}"
            nodes.append(
                {
                    "id": node_id,
                    "type": "character",
                    "label": str(card.get("name") or card_id),
                    "summary": str(card.get("role") or ""),
                    "status": str(card.get("trust_status") or "open"),
                    "source_ref": self._item_source(source, card_id),
                }
            )

        world_items: dict[str, tuple[str, dict[str, Any], dict[str, Any]]] = {}
        for source, world in world_sources:
            for collection, node_type in (
                ("entities", "world_entity"),
                ("rules", "world_rule"),
                ("timeline", "timeline_event"),
            ):
                items = world.get(collection)
                if not isinstance(items, list):
                    continue
                for index, item in enumerate(items):
                    if not isinstance(item, dict) or item.get("status", "active") == "archived":
                        continue
                    item_id = str(item.get("id") or f"{collection}-{index + 1}")
                    node_id = f"{node_type}:{item_id}"
                    label = str(item.get("name") or item.get("text") or item_id)
                    world_items[item_id] = (node_id, source, item)
                    nodes.append(
                        {
                            "id": node_id,
                            "type": node_type,
                            "label": label,
                            "summary": str(item.get("summary") or item.get("category") or ""),
                            "status": str(item.get("confidence_status") or "open"),
                            "source_ref": self._item_source(source, item_id),
                        }
                    )
                    if collection == "timeline":
                        events.append(
                            {
                                "id": item_id,
                                "ordinal": len(events) + 1,
                                "text": str(item.get("text") or ""),
                                "category": str(item.get("category") or "general"),
                                "participants": self._string_list(item.get("participants")),
                                "participant_character_ids": self._string_list(
                                    item.get("participant_character_ids")
                                ),
                                "confidence_status": str(
                                    item.get("confidence_status") or "open"
                                ),
                                "status": str(item.get("status") or "active"),
                                "source_ref": self._item_source(source, item_id),
                            }
                        )

        for source, canon in canon_sources:
            facts = canon.get("facts")
            if not isinstance(facts, list):
                continue
            for index, fact in enumerate(facts):
                if not isinstance(fact, dict) or fact.get("status", "active") == "archived":
                    continue
                fact_id = str(fact.get("id") or f"fact-{index + 1}")
                node_id = f"canon_fact:{fact_id}"
                nodes.append(
                    {
                        "id": node_id,
                        "type": "canon_fact",
                        "label": str(fact.get("text") or fact_id),
                        "summary": str(fact.get("source") or ""),
                        "status": str(fact.get("confidence_status") or "open"),
                        "source_ref": self._item_source(source, fact_id),
                    }
                )

        for card_id, (source, card) in active_characters.items():
            relationships = card.get("relationships")
            if not isinstance(relationships, list):
                continue
            for index, relationship in enumerate(relationships):
                if not isinstance(relationship, dict):
                    continue
                relation_id = str(relationship.get("id") or f"relationship-{index + 1}")
                resolution = self._resolve_character(
                    relationship.get("target_character_id"),
                    relationship.get("target"),
                    active_characters,
                    name_index,
                )
                if resolution["status"] in {"resolved", "legacy_name_resolved"}:
                    target_id = resolution["character_id"]
                    edges.append(
                        {
                            "id": self._edge_id(source, relation_id, card_id, target_id),
                            "type": "character_relationship",
                            "from": f"character:{card_id}",
                            "to": f"character:{target_id}",
                            "label": str(relationship.get("kind") or "关系待定"),
                            "summary": str(relationship.get("summary") or ""),
                            "resolution": resolution["status"],
                            "source_ref": self._item_source(source, relation_id),
                        }
                    )
                else:
                    unresolved.append(
                        {
                            "id": self._edge_id(source, relation_id, card_id, "unresolved"),
                            "type": "character_relationship",
                            "from": f"character:{card_id}",
                            "target_character_id": str(
                                relationship.get("target_character_id") or ""
                            ),
                            "target_name": str(relationship.get("target") or ""),
                            "label": str(relationship.get("kind") or "关系待定"),
                            "resolution": resolution["status"],
                            "candidate_character_ids": resolution.get("candidate_character_ids", []),
                            "source_ref": self._item_source(source, relation_id),
                        }
                    )

        for item_id, (node_id, source, item) in world_items.items():
            participant_ids = self._string_list(item.get("participant_character_ids"))
            participant_names = self._string_list(item.get("participants"))
            linked_characters: set[str] = set()
            for participant_id in participant_ids:
                resolution = self._resolve_character(
                    participant_id, "", active_characters, name_index
                )
                self._append_world_character_link(
                    edges, unresolved, linked_characters, resolution,
                    source, item_id, node_id, participant_id, "",
                )
            for participant_name in participant_names:
                resolution = self._resolve_character(
                    "", participant_name, active_characters, name_index
                )
                self._append_world_character_link(
                    edges, unresolved, linked_characters, resolution,
                    source, item_id, node_id, "", participant_name,
                )
            for target_id in self._string_list(item.get("related_world_ids")):
                target = world_items.get(target_id)
                if target:
                    edges.append(
                        {
                            "id": self._edge_id(source, item_id, node_id, target[0]),
                            "type": "world_relationship",
                            "from": node_id,
                            "to": target[0],
                            "label": "设定关联",
                            "summary": "",
                            "resolution": "resolved",
                            "source_ref": self._item_source(source, item_id),
                        }
                    )
                else:
                    unresolved.append(
                        {
                            "id": self._edge_id(source, item_id, node_id, target_id),
                            "type": "world_relationship",
                            "from": node_id,
                            "target_world_id": target_id,
                            "resolution": "unresolved",
                            "candidate_character_ids": [],
                            "source_ref": self._item_source(source, item_id),
                        }
                    )

        type_order = {
            "character": 1,
            "world_entity": 2,
            "world_rule": 3,
            "timeline_event": 4,
            "canon_fact": 5,
        }
        nodes.sort(key=lambda item: (type_order.get(item["type"], 99), item["id"]))
        edges.sort(key=lambda item: item["id"])
        unresolved.sort(key=lambda item: item["id"])
        return (
            {
                "schema_version": "knowledge-graph-projection/1.0",
                "nodes": nodes,
                "edges": edges,
                "unresolved_relationships": unresolved,
            },
            {
                "schema_version": "work-timeline-projection/1.0",
                "events": events,
            },
        )

    def _append_world_character_link(
        self,
        edges: list[dict[str, Any]],
        unresolved: list[dict[str, Any]],
        linked_characters: set[str],
        resolution: dict[str, Any],
        source: dict[str, Any],
        item_id: str,
        node_id: str,
        target_character_id: str,
        target_name: str,
    ) -> None:
        if resolution["status"] in {"resolved", "legacy_name_resolved"}:
            character_id = resolution["character_id"]
            if character_id in linked_characters:
                return
            linked_characters.add(character_id)
            edges.append(
                {
                    "id": self._edge_id(source, item_id, character_id, node_id),
                    "type": "participation",
                    "from": f"character:{character_id}",
                    "to": node_id,
                    "label": "参与",
                    "summary": "",
                    "resolution": resolution["status"],
                    "source_ref": self._item_source(source, item_id),
                }
            )
            return
        unresolved.append(
            {
                "id": self._edge_id(source, item_id, node_id, target_character_id or target_name),
                "type": "participation",
                "from": node_id,
                "target_character_id": target_character_id,
                "target_name": target_name,
                "resolution": resolution["status"],
                "candidate_character_ids": resolution.get("candidate_character_ids", []),
                "source_ref": self._item_source(source, item_id),
            }
        )

    @staticmethod
    def _resolve_character(
        target_character_id: Any,
        target_name: Any,
        active_characters: dict[str, tuple[dict[str, Any], dict[str, Any]]],
        name_index: dict[str, set[str]],
    ) -> dict[str, Any]:
        stable_id = str(target_character_id or "").strip()
        if stable_id:
            if stable_id in active_characters:
                return {"status": "resolved", "character_id": stable_id}
            return {"status": "unresolved", "candidate_character_ids": []}
        normalized = CurrentWorkProjection._identity(target_name)
        candidates = sorted(name_index.get(normalized, set())) if normalized else []
        if len(candidates) == 1:
            return {"status": "legacy_name_resolved", "character_id": candidates[0]}
        if len(candidates) > 1:
            return {"status": "ambiguous", "candidate_character_ids": candidates}
        return {"status": "unresolved", "candidate_character_ids": []}

    @staticmethod
    def _structure_view(
        loaded: list[tuple[dict[str, Any], dict[str, Any]]]
    ) -> dict[str, Any]:
        structures = [item for item in loaded if item[0]["artifact_kind"] == "story_structure"]
        if not structures:
            return {
                "schema_version": "story-structure-projection/1.0",
                "source_revision_id": None,
                "source_content_hash": None,
                "summary": "",
                "status": "not_available",
                "volumes": [],
            }
        source, content = structures[0]
        volumes = content.get("volumes")
        return {
            "schema_version": "story-structure-projection/1.0",
            "source_revision_id": source["revision_id"],
            "source_content_hash": source["content_hash"],
            "summary": str(content.get("summary") or ""),
            "status": str(content.get("status") or "accepted"),
            "volumes": volumes if isinstance(volumes, list) else [],
        }

    @staticmethod
    def _identity(value: Any) -> str:
        return " ".join(str(value or "").strip().casefold().split())

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [text for text in (str(item).strip() for item in value) if text]

    @staticmethod
    def _edge_id(source: dict[str, Any], item_id: str, start: str, end: str) -> str:
        digest = sha256_text(
            canonical_json(
                {
                    "revision_id": source["revision_id"],
                    "item_id": item_id,
                    "from": start,
                    "to": end,
                }
            )
        )
        return "edge-" + digest.removeprefix("sha256:")[:20]


class _Unavailable(Exception):
    def __init__(self, reason: str, *, actual_hash: str | None = None):
        super().__init__(reason)
        self.reason = reason
        self.actual_hash = actual_hash
