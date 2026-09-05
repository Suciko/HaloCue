"""Deterministic background completion for the opt-in conservative preset."""

from __future__ import annotations

import re

from annotation_chunks import build_scene_map
from resource_retrieval import rank_background_candidates


class BackgroundSelectionError(ValueError):
    def __init__(self, code: str):
        super().__init__("Frozen backgrounds are missing or contain an unresolved reference")
        self.code = code


class ConservativeBackgroundPolicy:
    def __init__(self, items, index, config, usage_chain):
        self.index = index
        self.available = set(index.get("bg") or {})
        self.default = str(config.get("default_bg") or "")
        self.contexts = {}
        scenes = build_scene_map(items, usage_chain)
        if scenes and not self.available:
            raise BackgroundSelectionError("background_catalog_empty")
        previous_end = -1
        title = ""
        for scene in scenes:
            indices = scene["target_indices"]
            prefix = "\n".join(
                str(i.get("raw") or "") for i in items[previous_end + 1 : indices[0]]
            )
            matches = re.findall(r"(?im)^\s*@bg\s+(.+?)\s*$", prefix)
            authored = matches[-1] if matches else ""
            headings = re.findall(r"(?m)^\s*#{1,6}\s+(.+?)\s*$", prefix)
            if headings:
                title = headings[-1]
            chain_index = scene.get("usage_chain_index")
            plan = usage_chain[chain_index] if chain_index is not None else {}
            confirmed = next(
                (
                    str(need.get("aa_key") or "")
                    for need in plan.get("needs", [])
                    if isinstance(need, dict)
                    and need.get("kind") in {"bg", "background"}
                    and need.get("status") in {"builtin", "registered", "confirmed"}
                    and need.get("aa_key")
                ),
                "",
            )
            pinned = authored or str((config.get("scene_bg") or {}).get(title) or "") or confirmed
            if pinned and pinned not in self.available:
                raise BackgroundSelectionError("background_not_in_manifest")
            query = " ".join(
                (
                    scene.get("location", ""),
                    scene.get("time", ""),
                    prefix,
                    " ".join(str(items[i].get("text") or "") for i in indices[:5]),
                )
            )
            for position, i in enumerate(indices):
                self.contexts[items[i]["annotation_id"]] = {
                    "opening": position == 0,
                    "query": query,
                    "pinned": pinned,
                    "authored": bool(authored),
                    "inherited": bool(plan.get("inherited") or plan.get("inherits_from")),
                }
            previous_end = indices[-1]

    def apply(self, rows_by_id, targets, previous_background=""):
        rows = {
            key: {field: data for field, data in value.items() if not field.startswith("_")}
            for key, value in rows_by_id.items()
        }
        current = previous_background if previous_background in self.available else ""
        for item in targets:
            source_id = item["annotation_id"]
            row = rows.get(source_id)
            context = self.contexts.get(source_id)
            if row is None or context is None:
                continue
            selected = str(row.get("bg") or "")
            request = str(row.get("bg_request") or "")
            pinned = context["pinned"]
            if pinned:
                selected = pinned
            elif selected and selected not in self.available:
                raise BackgroundSelectionError("background_not_in_manifest")
            elif context["inherited"] and current:
                selected = current
            elif not selected and (context["opening"] or request):
                ranked = rank_background_candidates(self.index, request or context["query"])
                score, best = ranked[0]
                selected = (
                    best
                    if score > 0
                    else (
                        current
                        or (
                            self.default
                            if self.default in self.available and self.default != "BG_Black"
                            else ""
                        )
                        or next((key for _, key in ranked if key != "BG_Black"), best)
                    )
                )
                row["_background_origin"] = "deterministic_fallback"
                row["_background_review"] = {
                    "code": "background_approximate_match",
                    "level": "warning",
                    "source_id": source_id,
                    "field": "bg",
                    "background_key": selected,
                    "message": "已选择可用背景，可在审查中更换；匹配分数不是置信概率。",
                }
            if selected and request and not pinned and "_background_review" not in row:
                row["_background_review"] = {
                    "code": "background_approximate_match",
                    "level": "warning",
                    "source_id": source_id,
                    "field": "bg",
                    "background_key": selected,
                    "message": "已采用模型选择的可用近似背景，可在审查中更换。",
                }
            if selected:
                row["_background_effective"] = selected
                row["bg"] = "" if selected == current or context["authored"] else selected
                current = selected
            row["bg_request"] = ""
        return rows

    def inherits_scene(self, targets):
        return bool(targets and self.contexts.get(targets[0]["annotation_id"], {}).get("inherited"))
