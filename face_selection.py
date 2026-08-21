# -*- coding: utf-8 -*-
"""Backend shortlisting for semantically labelled portrait faces.

The label model describes each rendered face once.  At story time this module
does not invent a face meaning and does not make the final acting decision; it
removes unsafe candidates and ranks the remaining labelled faces for the
current line.  The director model then chooses from a small relevant set.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from face_label_backend import is_persona_face_blocked


_FREQUENCY_SCORE = {"default": 2.0, "common": 1.0, "conditional": -1.0, "rare": -3.0}
_DELIVERY_NEIGHBORS = {
    "soft_speech": {"normal_speech"},
    "normal_speech": {"soft_speech", "emphatic_speech"},
    "emphatic_speech": {"normal_speech", "shout"},
    "shout": {"emphatic_speech"},
}

_PLAN_SEMANTIC_SIGNALS = (
    (("好奇", "疑惑", "困惑", "追问"), ("question",), ("curious",)),
    (("认真", "严肃", "专注", "坚定", "郑重"), ("exposition",), ("serious", "focused", "determined")),
    (("开心", "高兴", "兴奋", "喜悦", "期待", "热切", "雀跃", "欣喜", "欢呼"), ("celebration",), ("joyful",)),
    (("惊讶", "意外", "震惊", "愣住"), ("reaction", "reveal"), ("surprised",)),
    (("生气", "恼怒", "不满", "抗议"), ("conflict",), ("angry",)),
    (("难过", "委屈", "沮丧", "吃瘪", "失落"), ("setback",), ("sad", "distressed", "resigned")),
    (("害怕", "恐惧", "慌张", "紧张"), ("reaction", "setback"), ("afraid", "distressed")),
    (("害羞", "尴尬", "心虚"), ("embarrassment",), ("embarrassed", "distressed")),
    (("温柔", "感谢", "安心", "释然"), ("comfort",), ("gentle",)),
    (("无奈", "迟疑", "犹豫"), ("hesitation", "listening"), ("resigned",)),
)


def infer_face_intent(text: object, *, emo: object = "", act: object = "") -> dict:
    """Extract a small semantic query without pretending to understand a face."""
    raw = str(text or "").strip()
    compact = re.sub(r"\s+", "", raw)
    beats = ["dialogue"]
    tags = []
    intensity = 1
    delivery = "normal_speech"

    punctuation_only = bool(compact) and not any(char.isalnum() or "\u4e00" <= char <= "\u9fff" for char in compact)
    if punctuation_only or compact in {"……", "...", "…", "嗯……", "唔……"}:
        delivery, intensity = "soft_speech", 0
        beats.extend(("hesitation", "listening"))
        tags.extend(("blank", "resigned"))
    elif compact.count("！") + compact.count("!") >= 2:
        delivery, intensity = "shout", 3
    elif "！" in compact or "!" in compact:
        delivery, intensity = "emphatic_speech", 2

    def add_beat(value):
        if value not in beats:
            beats.append(value)

    def add_tag(value):
        if value not in tags:
            tags.append(value)

    if any(token in compact for token in ("？", "?", "为什么", "怎么", "哪里", "哪儿", "什么", "奇怪")):
        add_beat("question")
        add_tag("curious")
    if any(token in compact for token in ("报告", "确认", "检查结果", "记录", "结论", "任务开始", "开始行动")):
        add_beat("exposition")
        add_tag("focused")
        add_tag("serious")

    # These are semantic delivery signals rather than keyword-to-face rules.
    # They make the existing full candidate set distinguish a defensive
    # explanation, a command-like peak, and a thought that fails to come out.
    # The director still chooses the final face; this only improves recall and
    # ranking context for all characters and does not force a resource.
    if any(token in compact for token in (
        "强装客观", "客观辩解", "嘴硬", "硬撑", "强行解释", "掩饰", "装作",
    )):
        add_beat("denial")
        add_beat("hesitation")
        add_tag("resigned")
        add_tag("assertive")
    if any(token in compact for token in (
        "改掉", "删掉", "不许", "立即", "立刻", "现在就",
    )):
        add_beat("conflict")
        add_beat("denial")
        add_tag("angry")
        add_tag("assertive")
        intensity = max(intensity, 2)
    if any(token in compact for token in (
        "说不出口", "说不出来", "吞回", "闭口", "欲言又止", "开不了口",
        "被戳穿",
    )) or compact.endswith(("——", "…", "...")):
        add_beat("hesitation")
        add_tag("embarrassed")
        add_tag("resigned")
    if "被戳穿" in compact:
        add_beat("embarrassment")
    if any(token in compact for token in ("认真", "我是认真的", "听我说", "我说了", "郑重")):
        add_beat("exposition")
        add_tag("serious")
        add_tag("assertive")
        add_tag("determined")
    if any(token in compact for token in ("太好了", "成功", "完成了", "赢了", "做到了")):
        add_beat("celebration")
        add_tag("joyful")
        intensity = max(intensity, 2)
    if any(token in compact for token in ("探索任务开始", "开始探索", "开始行动")):
        add_beat("celebration")
        add_beat("action")
        add_tag("joyful")
        add_tag("determined")
        intensity = max(intensity, 2)
    negative_discovery = any(token in compact for token in ("没有发现", "未发现", "没有找到", "没找到"))
    if not negative_discovery and any(
        token in compact for token in ("发现", "找到了", "原来", "竟然", "没想到")
    ):
        add_beat("reveal")
        add_beat("reaction")
        add_tag("surprised")
    if any(token in compact for token in ("荒谬", "离谱", "怎么可能", "不可能吧", "开什么玩笑")):
        add_beat("reaction")
        add_beat("comedy")
        add_tag("surprised")
        add_tag("distressed")
    if any(token in compact for token in ("谢谢", "多谢", "抱歉", "对不起", "没关系", "辛苦了")):
        add_beat("comfort")
        add_tag("gentle")
    distressed_refusal = any(
        token in compact
        for token in ("不要啊", "不要呀", "拜托不要", "不要……", "不要...")
    ) or (
        "不要" in compact
        and any(token in compact for token in ("怎么会", "为什么会这样", "呜哇", "呜呜"))
    )
    angry_conflict = any(
        token in compact for token in ("不行", "才不是", "闭嘴", "可恶", "生气", "胡说")
    ) or ("不要" in compact and not distressed_refusal)
    if angry_conflict:
        add_beat("conflict")
        add_tag("angry")
        intensity = max(intensity, 2)
    if distressed_refusal:
        add_beat("setback")
        add_tag("afraid")
        add_tag("distressed")
    if any(token in compact for token in ("害羞", "难为情", "别看", "丢脸", "尴尬")):
        add_beat("embarrassment")
        add_tag("embarrassed")
    shock_distress = any(
        token in compact
        for token in ("怎么会这样", "怎么会变成", "这不可能", "不可能啊")
    )
    if shock_distress:
        add_beat("reaction")
        add_beat("setback")
        add_tag("surprised")
        add_tag("afraid")
        add_tag("distressed")
        intensity = max(intensity, 2)
    if re.search(r"([\u4e00-\u9fff])、\1", compact):
        if not shock_distress:
            add_beat("embarrassment")
            add_tag("embarrassed")
        add_tag("distressed")
    if any(token in compact for token in ("糟了", "失败", "没办法", "难过", "对不起……")):
        add_beat("setback")
        add_tag("sad")
    if any(token in compact for token in ("呜哇", "呜呜", "不要啊", "为什么会这样")):
        add_beat("setback")
        add_tag("sad")
        add_tag("distressed")
    if str(emo or "") in {"闪亮", "星星", "音符"} or str(act or "") == "hophop":
        add_beat("celebration")
        add_tag("joyful")
        intensity = max(intensity, 2)

    for keywords, semantic_beats, semantic_tags in _PLAN_SEMANTIC_SIGNALS:
        if not any(keyword in compact for keyword in keywords):
            continue
        for beat in semantic_beats:
            add_beat(beat)
        for tag in semantic_tags:
            add_tag(tag)

    return {
        "delivery": delivery,
        "beats": beats,
        "semantic_tags": tags,
        "intensity": intensity,
        "ordinary_dialogue": beats == ["dialogue"],
        "nonlexical": punctuation_only or compact in {"……", "...", "…", "嗯……", "唔……"},
        "surface_text": compact,
    }


def _semantic_text(face: Mapping) -> str:
    semantic = str(face.get("semantic_cn") or "").strip()
    if semantic:
        return semantic
    return "｜".join(dict.fromkeys(
        str(value or "").strip()
        for value in (
            face.get("primary_emotion"), face.get("usage_hint_cn"),
            face.get("cn"), face.get("label"),
        )
        if str(value or "").strip()
    ))


def _semantic_token(face: Mapping, modes: Sequence[Mapping], intent: Mapping) -> str:
    """Choose one natural alias while keeping the real clip id backend-only."""
    desired_delivery = str(intent.get("delivery") or "")
    desired_beats = set(intent.get("beats") or ())
    desired_tags = set(intent.get("semantic_tags") or ())
    scored_modes = []
    for mode in modes:
        score = 0
        if desired_delivery in set(mode.get("delivery_fit") or ()):
            score += 3
        score += 2 * len(desired_beats & set(mode.get("beat_fit") or ()))
        score += 2 * len(desired_tags & set(mode.get("semantic_tags") or ()))
        scored_modes.append((-score, str(mode.get("label_cn") or "").strip()))
    label = min(scored_modes)[1] if scored_modes else ""
    if not label:
        label = _semantic_text(face).split("｜", 1)[0].strip()
    return f"[Emo:{label}]"


def rank_face_candidates(
    records: Sequence[Mapping], intent: Mapping, *, current_face: object = "",
    character_id: object = "", limit: int | None = None,
    previous_face_record: Mapping | None = None, stage_change: bool = False,
    include_all: bool = False,
) -> list[dict]:
    """Hard-filter unsafe rows, then return ranked semantic face options.

    Normal callers can request a compact ranked shortlist.  Stateful model
    prompts use ``include_all`` so ranking remains useful guidance without
    turning an aesthetic suggestion into a hidden resource allowlist.
    """
    desired_delivery = str(intent.get("delivery") or "normal_speech")
    desired_beats = set(intent.get("beats") or ())
    desired_tags = set(intent.get("semantic_tags") or ())
    desired_intensity = int(intent.get("intensity") or 0)
    current = str(current_face or "")
    ranked = []

    for face in records or ():
        face_id = str(face.get("id") or face.get("face_id") or "").strip()
        semantic = _semantic_text(face)
        if not face_id or not semantic or face.get("backend_selection_ready") is False:
            continue
        if is_persona_face_blocked(character_id, face_id):
            continue
        if face.get("near_duplicate_of"):
            continue

        modes = [mode for mode in face.get("semantic_modes") or () if isinstance(mode, Mapping)]
        token = _semantic_token(face, modes, intent)
        score = _FREQUENCY_SCORE.get(str(face.get("usage_frequency") or "common"), 0.0)
        reasons = []
        if face.get("backend_review_required"):
            score -= 1.5
            reasons.append("review_pending")
        delivery_fit = {str(value) for value in face.get("delivery_fit") or () if str(value)}
        delivery_fit.update(
            str(value)
            for mode in modes
            for value in mode.get("delivery_fit") or ()
            if str(value)
        )
        if intent.get("nonlexical") and delivery_fit & {"silent_reaction", "listening"}:
            score += 4.0
            reasons.append("delivery")
        elif desired_delivery in delivery_fit:
            score += 6.0
            reasons.append("delivery")
        elif delivery_fit & _DELIVERY_NEIGHBORS.get(desired_delivery, set()):
            score += 1.5
        elif delivery_fit:
            score -= 2.0

        beat_fit = {str(value) for value in face.get("beat_fit") or () if str(value)}
        beat_fit.update(
            str(value)
            for mode in modes
            for value in mode.get("beat_fit") or ()
            if str(value)
        )
        specific_beats = desired_beats - {"dialogue"}
        beat_matches = specific_beats & beat_fit
        if beat_matches:
            score += min(12.0, 4.0 * len(beat_matches))
            reasons.append("beat")
        elif not specific_beats and "dialogue" in beat_fit:
            score += 2.0
            reasons.append("beat")
        tags = {str(value) for value in face.get("semantic_tags") or () if str(value)}
        tags.update(
            str(value)
            for mode in modes
            for value in mode.get("semantic_tags") or ()
            if str(value)
        )
        tag_matches = desired_tags & tags
        if tag_matches:
            score += min(12.0, 4.0 * len(tag_matches))
            reasons.append("meaning")
        if "serious" in desired_tags:
            if "serious" in tags:
                score += 5.0
            elif (
                {"assertive", "determined"} <= tags
                and not ({"joyful", "playful"} & tags)
            ):
                score += 4.0
            else:
                score -= 2.0

        intensities = [face.get("intensity"), *(mode.get("intensity") for mode in modes)]
        intensity_scores = [
            max(-2.0, 2.0 - abs(value - desired_intensity) * 1.5)
            for value in intensities
            if isinstance(value, int) and not isinstance(value, bool)
        ]
        if intensity_scores:
            score += max(intensity_scores)

        expression_class = str(face.get("expression_class") or "base")
        strong_match = bool(beat_matches or tag_matches)
        if expression_class == "special" and not strong_match:
            score -= 7.0
        if expression_class == "peak" and desired_intensity < 3 and not strong_match:
            score -= 4.0

        profile = face.get("official_usage_profile")
        if isinstance(profile, Mapping):
            total = int(profile.get("total_count") or profile.get("examples") or 0)
            lexical = int(profile.get("lexical_dialogue_count") or 0)
            nonlexical = int(profile.get("nonlexical_dialogue_count") or 0)
            if total >= 5:
                if intent.get("nonlexical"):
                    score += 14.0 if nonlexical / total >= 0.4 else 0.0
                    score += 3.0 if lexical == 0 and nonlexical > 0 else 0.0
                    score -= 2.0 if lexical / total >= 0.9 else 0.0
                elif desired_delivery in {"soft_speech", "normal_speech", "emphatic_speech", "shout"}:
                    score += 2.0 if lexical / total >= 0.6 else (-4.0 if lexical == 0 else 0.0)
                elif nonlexical / total >= 0.5:
                    score += 2.0

        avoid = str(face.get("avoid_when_cn") or "")
        if intent.get("ordinary_dialogue") and any(token in avoid for token in ("普通对话", "日常对话", "鲜活反应")):
            score -= 8.0
        if "exposition" in desired_beats and any(token in avoid for token in ("正式报告", "汇报", "客观陈述")):
            score -= 10.0
        surface_text = str(intent.get("surface_text") or "")
        if (
            any(token in semantic for token in ("开怀大笑", "开怀欢笑", "大笑", "狂笑"))
            and not any(token in surface_text for token in ("笑", "哈哈", "呵呵"))
        ):
            score -= 6.0
        if face_id == current:
            score -= 1.25
        if stage_change and face_id != current:
            previous_signature = _face_component_signature(previous_face_record or {})
            candidate_signature = _face_component_signature(face)
            if previous_signature and candidate_signature:
                if previous_signature != candidate_signature:
                    score += 2.5
                    reasons.append("stage_change")
            else:
                score += 0.75

        ranked.append((
            -score, face_id,
            {
                "id": face_id,
                "token": token,
                "semantic": semantic,
                "delivery_fit": sorted(delivery_fit),
                "frequency": str(face.get("usage_frequency") or "common"),
                "match": reasons,
                "modes": [
                    str(mode.get("label_cn") or "")
                    for mode in modes
                    if str(mode.get("label_cn") or "").strip()
                ],
            },
        ))

    ordered = sorted(ranked)
    if include_all:
        selected_count = len(ordered)
    elif limit is None:
        if len(ordered) <= 3:
            selected_count = len(ordered)
        else:
            top_score = -ordered[0][0]
            near_top = sum((-row[0]) >= top_score - 3.0 for row in ordered)
            selected_count = min(6, max(3, near_top))
    else:
        selected_count = max(1, int(limit))
    selected = [row[2] for row in ordered[:selected_count]]
    token_counts = {}
    for candidate in selected:
        token = str(candidate.get("token") or "")
        token_counts[token] = token_counts.get(token, 0) + 1
        if token_counts[token] <= 1:
            continue
        suffix = f"·{token_counts[token]}"
        candidate["token"] = token[:-1] + suffix + "]" if token.endswith("]") else token + suffix
    return selected


def _face_component_signature(face: Mapping) -> tuple[str, ...]:
    """Return ordinary eye/brow/mouth facts; persona-only signals stay excluded."""
    if not isinstance(face, Mapping):
        return ()
    facts = next((
        face.get(key) for key in ("effective_observation", "observation", "visual_facts")
        if isinstance(face.get(key), Mapping)
    ), {})
    values = tuple(
        str(facts.get(key) or face.get(key) or "").strip()
        for key in ("eye_openness", "gaze", "brow_shape", "mouth_openness", "mouth_shape")
    )
    if any(values):
        return values
    fallback = tuple(str(face.get(key) or "").strip() for key in ("eyes", "brows", "mouth"))
    return fallback if any(fallback) else ()


def _merge_intents(primary: Mapping, secondary: Mapping, *, peak: bool = False) -> dict:
    merged = dict(primary)
    merged["beats"] = list(dict.fromkeys([
        *primary.get("beats", ()), *secondary.get("beats", ()),
    ]))
    merged["semantic_tags"] = list(dict.fromkeys([
        *primary.get("semantic_tags", ()), *secondary.get("semantic_tags", ()),
    ]))
    merged["intensity"] = max(
        int(primary.get("intensity") or 0),
        int(secondary.get("intensity") or 0),
        3 if peak else 0,
    )
    merged["ordinary_dialogue"] = (
        bool(primary.get("ordinary_dialogue"))
        and not (set(secondary.get("beats") or ()) - {"dialogue"})
    )
    return merged


def _planned_face_context(
    scene_event_plan: Mapping | None, anchor_id: str, who: str,
) -> dict:
    """Retrieve the active face stage and exact-anchor performance signals."""
    context = {"semantic_state": "", "change_reason": "", "stage_change": False,
               "peak": False, "evidence": []}
    for event in (scene_event_plan or {}).get("events") or ():
        if not isinstance(event, Mapping):
            continue
        source_ids = [str(value) for value in event.get("source_ids") or ()]
        if anchor_id not in source_ids:
            continue
        order = {source_id: index for index, source_id in enumerate(source_ids)}
        current_order = order[anchor_id]
        for arc in event.get("face_arcs") or ():
            if not isinstance(arc, Mapping) or str(arc.get("who") or "") != who:
                continue
            applicable = [
                stage for stage in arc.get("stages") or ()
                if isinstance(stage, Mapping)
                and str(stage.get("anchor_id") or "") in order
                and order[str(stage.get("anchor_id") or "")] <= current_order
            ]
            if applicable:
                stage = max(applicable, key=lambda value: order[str(value.get("anchor_id") or "")])
                context["semantic_state"] = str(stage.get("semantic_state") or "")
                context["change_reason"] = str(stage.get("change_reason") or "")
                if str(stage.get("anchor_id") or "") == anchor_id:
                    context["stage_change"] = True
                    context["evidence"].append("face_arc")
        for intent in event.get("performance_intents") or ():
            if not isinstance(intent, Mapping):
                continue
            if str(intent.get("anchor_id") or "") != anchor_id:
                continue
            if who not in {str(value) for value in intent.get("subjects") or ()}:
                continue
            if "face_change" in {str(value) for value in intent.get("carriers") or ()}:
                context["stage_change"] = True
                context["evidence"].append("performance_intent")
            context["evidence"].append(str(intent.get("purpose") or ""))
        for peak in event.get("peaks") or ():
            if not isinstance(peak, Mapping):
                continue
            if str(peak.get("peak_id") or "") == anchor_id and str(peak.get("subject") or "") == who:
                context["peak"] = True
                context["evidence"].extend((
                    str(peak.get("visual_intent") or ""), str(peak.get("why") or ""),
                ))
    context["evidence"] = [value for value in dict.fromkeys(context["evidence"]) if value]
    return context


def target_face_shortlists(
    items: Sequence[Mapping], target_indices: Sequence[int], *, cast: Mapping,
    constraints: Mapping, last_faces: Mapping | None = None, limit: int | None = None,
    scene_event_plan: Mapping | None = None, include_all: bool = False,
) -> list[dict]:
    """Build one shortlist per portrait-bearing TARGET line."""
    records_by_id = constraints.get("face_records_by_id") or {}
    previous = dict(last_faces or {})
    result = []
    for position, item_index in enumerate(target_indices, 1):
        item = items[item_index]
        who = str(item.get("who") or "")
        character = cast.get(who) or {}
        if not character.get("portrait") or character.get("narrator"):
            continue
        intent = infer_face_intent(item.get("text"), emo=item.get("emo"), act=item.get("act"))
        plan_context = _planned_face_context(
            scene_event_plan, str(item.get("annotation_id") or ""), who,
        )
        # semantic_state describes the face we want.  change_reason and
        # performance evidence describe what caused it and can mention another
        # character's reaction (for example, "the listener was surprised").
        # Feeding all of that into the semantic ranker transfers the listener's
        # emotion onto the speaker and makes the prompt shortlist disagree with
        # the planned arc.  Only fall back to contextual evidence when the plan
        # did not provide an explicit face state.
        plan_text = str(plan_context.get("semantic_state") or "").strip()
        if not plan_text:
            plan_text = " ".join((
                str(plan_context.get("change_reason") or ""),
                *plan_context.get("evidence", ()),
            ))
        if plan_text.strip():
            intent = _merge_intents(
                intent, infer_face_intent(plan_text), peak=bool(plan_context.get("peak")),
            )
        records = records_by_id.get(str(character.get("id") or ""), ())
        previous_record = next((
            record for record in records
            if str(record.get("id") or record.get("face_id") or "") == str(previous.get(who) or "")
        ), None)
        candidates = rank_face_candidates(
            records,
            intent,
            current_face=previous.get(who),
            character_id=character.get("id"),
            limit=limit,
            previous_face_record=previous_record,
            stage_change=bool(plan_context.get("stage_change")),
            include_all=include_all,
        )
        if candidates:
            result.append({
                "i": position,
                "who": who,
                "previous_face": str(previous.get(who) or ""),
                "intent": {
                    "delivery": intent["delivery"],
                    "beats": intent["beats"],
                    "semantic_tags": intent["semantic_tags"],
                    "intensity": intent["intensity"],
                    "nonlexical": intent["nonlexical"],
                },
                "plan": plan_context,
                "candidates": candidates,
            })
    return result


_SILENT_FACE_PHASES = {
    "reveal", "group_reaction", "focus_handoff", "result",
    "decision_pause", "aftershock",
}


def _silent_face_intent(event: Mapping, beat: Mapping) -> dict:
    text = " ".join(
        str(value or "").strip()
        for value in (
            event.get("stimulus"), beat.get("purpose"), event.get("outcome"),
            event.get("peak_reason"),
        )
        if str(value or "").strip()
    )
    intent = infer_face_intent(text)
    phase = str(beat.get("phase") or "")
    kind = str(event.get("kind") or "")
    beats = list(intent.get("beats") or ())
    tags = list(intent.get("semantic_tags") or ())

    def add(values: list[str], value: str) -> None:
        if value and value not in values:
            values.append(value)

    add(beats, "reaction")
    if phase == "decision_pause":
        add(beats, "hesitation")
        add(beats, "listening")
    if phase in {"reveal", "result"} or kind in {"reveal", "discovery"}:
        add(beats, "reveal")
        add(tags, "surprised")
    if kind in {"disturbance", "group_escalation"}:
        add(beats, "tension")
    return {
        **intent,
        "delivery": "silent_reaction",
        "beats": beats,
        "semantic_tags": tags,
        "ordinary_dialogue": False,
        "nonlexical": True,
    }


def silent_reaction_shortlists(
    items: Sequence[Mapping], target_indices: Sequence[int], *, cast: Mapping,
    constraints: Mapping, scene_event_plan: Mapping | None,
    last_faces: Mapping | None = None, limit: int | None = None,
    include_all: bool = False,
) -> list[dict]:
    """Shortlist faces only for planned, readable no-dialogue reaction beats."""
    local_index = {
        str(items[item_index].get("annotation_id") or ""): position
        for position, item_index in enumerate(target_indices, 1)
    }
    records_by_id = constraints.get("face_records_by_id") or {}
    previous = dict(last_faces or {})
    result = []
    for event in (scene_event_plan or {}).get("events") or ():
        if not isinstance(event, Mapping):
            continue
        for beat in event.get("silent_beats") or ():
            if not isinstance(beat, Mapping):
                continue
            anchor_id = str(beat.get("anchor_id") or "")
            anchor_i = local_index.get(anchor_id)
            phase = str(beat.get("phase") or "")
            if anchor_i is None or phase not in _SILENT_FACE_PHASES:
                continue
            participants = list(dict.fromkeys(
                str(value or "").strip()
                for value in beat.get("participants") or ()
                if str(value or "").strip()
            ))[:3]
            faces = {}
            intent = _silent_face_intent(event, beat)
            for who in participants:
                character = cast.get(who) or {}
                if not character.get("portrait") or character.get("narrator"):
                    continue
                candidates = rank_face_candidates(
                    records_by_id.get(str(character.get("id") or ""), ()),
                    intent,
                    current_face=previous.get(who),
                    character_id=character.get("id"),
                    limit=limit,
                    include_all=include_all,
                )
                if candidates:
                    faces[who] = candidates
            if faces:
                result.append({
                    "anchor_i": anchor_i,
                    "anchor_id": anchor_id,
                    "position": str(beat.get("position") or "after"),
                    "phase": phase,
                    "purpose": str(beat.get("purpose") or ""),
                    "faces": faces,
                })
    return result
