"""Evidence-based quality checks for staged AA direction.

These checks deliberately avoid quotas. They reject contradictions between a
director plan and its execution, not a particular number of cuts, faces, or
actions.
"""

from __future__ import annotations

import json
import re
import copy
import sys
from typing import Any, Mapping, Sequence


def _issue(code: str, message: str, **extra: Any) -> dict[str, Any]:
    result = {"code": code, "message": message}
    result.update(extra)
    result.setdefault(
        "resolution",
        issue_resolution(
            code,
            severity=str(result.get("severity") or result.get("level") or ""),
        ),
    )
    return result


# Quality gates describe a contradiction; they must not silently become an
# art-direction policy.  This table only says who owns the *repair* after a
# contradiction is found.  The semantic choices (face, framing, cut style,
# action) remain with the model unless the issue is a pure geometry/protocol
# violation.
_DETERMINISTIC_REPAIR_CODES = frozenset({
    "compiler_annotation_auto_repaired",
})
_RESOURCE_REQUIRED_CODES = frozenset({
    "unresolved_background_request",
})
_BLOCKING_CODES = frozenset({
    "visible_over_three",
    "unsafe_spacing",
    "compiled_visible_over_three",
})

# A scene plan is an AI hypothesis about the source text, not an official
# answer. Keep these findings in the audit, but do not automatically trigger
# a repair that forces G2 to obey a possibly wrong G1 shot or beat choice.
_PLAN_ADVISORY_CODES = frozenset({
    "compiler_warning",
    "compiler_annotation_offscreen",
    "opening_arrival_event_missing",
    "enter_without_arrival_evidence",
    "missing_planned_silent_phase",
    "planned_shot_span_unfulfilled",
    "unplanned_camera_change_inside_shot_span",
    "release_owner_not_visible",
    "performance_intent_unfulfilled",
    "performance_layer_collapsed",
    "face_stage_change_unfulfilled",
    "face_stage_no_readable_change",
    "face_stage_reused_same_face",
    "peak_composition_mismatch",
    "solo_emphasis_not_solo_center",
    "solo_emphasis_performance_unfulfilled",
    "solo_emphasis_closeup_unfulfilled",
    "heavy_fx_unjustified",
    "repeated_static_camera_pivot",
    "speaker_chasing_camera_relay",
    "compiled_speaker_chasing_camera_relay",
    "group_reaction_stimulus_mismatch",
})


def is_automatic_repairable_quality_issue(issue: Mapping[str, Any]) -> bool:
    """Return whether a finding may start an automatic G2 repair.

    Plan-derived art-direction findings remain visible for human review and
    official comparison, but a mistaken first-stage hypothesis must not
    overwrite a valid second-stage camera or performance decision.
    """
    if str(issue.get("code") or "") in _PLAN_ADVISORY_CODES:
        return False
    severity = str(issue.get("severity") or issue.get("level") or "high").lower()
    return severity in {"critical", "high"}


def issue_resolution(code: str, *, severity: str = "") -> str:
    """Return the repair owner without changing the quality decision.

    ``deterministic`` is reserved for lossless syntax/lifecycle/geometry
    cleanup.  ``ai_repair`` means the model must reconsider a local semantic
    choice.  ``block`` is used where continuing would produce an invalid or
    misleading AAP and no safe artistic default exists.
    """
    normalized = str(code or "")
    if normalized in _PLAN_ADVISORY_CODES:
        return "advisory"
    if normalized in _DETERMINISTIC_REPAIR_CODES:
        return "deterministic"
    if normalized in _RESOURCE_REQUIRED_CODES:
        return "resource_required"
    if normalized in _BLOCKING_CODES or str(severity).lower() == "critical":
        return "block"
    return "ai_repair"


def classify_quality_issue(issue: Mapping[str, Any]) -> dict[str, Any]:
    """Copy an issue and attach its repair owner for reports and telemetry."""
    classified = dict(issue)
    code = str(classified.get("code") or "")
    severity = str(classified.get("severity") or classified.get("level") or "")
    canonical = issue_resolution(code, severity=severity)
    # Old audit artifacts may carry policy labels that predate the current
    # ownership table. Reclassify known codes while preserving explicit
    # owners for unknown extension codes.
    known_code = (
        code in _PLAN_ADVISORY_CODES
        or code in _DETERMINISTIC_REPAIR_CODES
        or code in _RESOURCE_REQUIRED_CODES
        or code in _BLOCKING_CODES
    )
    if known_code or "resolution" not in classified:
        classified["resolution"] = canonical
    if "needs_review" in classified:
        resolution = str(classified.get("resolution") or "ai_repair")
        classified["needs_review"] = (
            resolution == "block"
            or (
                resolution == "ai_repair"
                and is_automatic_repairable_quality_issue(classified)
            )
        )
    return classified


def classify_quality_issues(issues: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [classify_quality_issue(issue) for issue in issues if isinstance(issue, Mapping)]


def quality_resolution_summary(issues: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    summary = {
        "deterministic": 0, "ai_repair": 0,
        "resource_required": 0, "block": 0, "advisory": 0,
    }
    for issue in classify_quality_issues(issues):
        resolution = str(issue.get("resolution") or "ai_repair")
        if resolution not in summary:
            resolution = "ai_repair"
        summary[resolution] += 1
    return summary


def _ordered_shots(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    shots: list[dict[str, Any]] = []
    for chain_index, chain in enumerate(plan.get("event_chains") or []):
        for shot_index, shot in enumerate(chain.get("shot_steps") or []):
            row = dict(shot)
            row["_chain_index"] = chain_index
            row["_shot_index"] = shot_index
            shots.append(row)
    return sorted(shots, key=lambda row: (int(row.get("anchor_line") or 0), row["_chain_index"], row["_shot_index"]))


def validate_director_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Validate semantic consistency without imposing density budgets."""
    if "events" in plan and "event_chains" not in plan:
        return validate_plan_quality(plan)
    issues: list[dict[str, Any]] = []
    shots = _ordered_shots(plan)
    previous: dict[str, Any] | None = None

    for shot in shots:
        visible = tuple(str(value) for value in shot.get("visible_characters") or [])
        signature = (
            visible,
            str(shot.get("focus") or ""),
            str(shot.get("framing") or ""),
            str(shot.get("continuity") or ""),
        )
        if previous is not None:
            previous_signature = (
                tuple(str(value) for value in previous.get("visible_characters") or []),
                str(previous.get("focus") or ""),
                str(previous.get("framing") or ""),
                str(previous.get("continuity") or ""),
            )
            if signature == previous_signature and shot.get("operation") == "continue_group":
                issues.append(_issue(
                    "redundant_shot_step",
                    "连续镜头重复声明同一可见组、焦点和景别；应保持镜头而不是逐句重写。",
                    anchor_line=shot.get("anchor_line"),
                ))
            old_visible = set(previous.get("visible_characters") or [])
            new_visible = set(visible)
            if len(old_visible) == len(new_visible) == 2 and len(old_visible & new_visible) == 1:
                operation = str(shot.get("operation") or "")
                cut_motivation = str(shot.get("cut_motivation") or "").strip()
                allowed_match_cut = (
                    operation in {"anchor_match_cut", "switch_group", "impact_insert"}
                    and bool(cut_motivation)
                )
                if operation not in {"shrink_group", "expand_group"} and not allowed_match_cut:
                    issues.append(_issue(
                        "stationary_pair_swap",
                        "双人组发生单人替换，但没有连续镜头过渡或有动机的完整硬切。",
                        anchor_line=shot.get("anchor_line"),
                        previous=list(previous.get("visible_characters") or []),
                        current=list(visible),
                    ))
        previous = shot

    shot_by_line = {int(shot.get("anchor_line") or 0): shot for shot in shots}
    performance_by_line: dict[int, list[dict[str, Any]]] = {}
    for chain in plan.get("event_chains") or []:
        for beat in chain.get("performance_beats") or []:
            try:
                anchor = int(beat.get("anchor_line") or 0)
            except (TypeError, ValueError):
                continue
            performance_by_line.setdefault(anchor, []).append(beat)

        for impact in chain.get("impact_lines") or []:
            try:
                line = int(impact.get("line") or 0)
            except (TypeError, ValueError):
                line = 0
            subject = str(impact.get("subject") or "")
            shot = shot_by_line.get(line)
            emphasis = str(impact.get("emphasis") or "")
            if not shot:
                issues.append(_issue("impact_without_shot", "爆点没有对应镜头步骤。", line=line))
                continue
            visible = [str(value) for value in shot.get("visible_characters") or []]
            if emphasis != "none" and (visible != [subject] or shot.get("framing") != "close"):
                issues.append(_issue(
                    "impact_not_solo_close",
                    "强情绪爆点必须是主体单人居中特写。",
                    line=line,
                    subject=subject,
                    visible=visible,
                ))
            if emphasis == "focusline" and visible != [subject]:
                issues.append(_issue(
                    "focusline_not_solo",
                    "FocusLine 只能用于爆点主体的单人镜头。",
                    line=line,
                ))
            if emphasis in {"closeup+action", "closeup+emoticon", "focusline"}:
                beats = performance_by_line.get(line, [])
                if not any(
                    str(beat.get("action_intent") or "none") != "none"
                    or str(beat.get("emoticon_intent") or "none") != "none"
                    for beat in beats
                ):
                    issues.append(_issue(
                        "impact_performance_missing",
                        "计划要求动作或表情符号承载爆点，但没有对应 performance beat。",
                        line=line,
                    ))

        for beat in chain.get("silent_beats") or []:
            if not beat.get("inherit_face", True):
                continue
            phase = str(beat.get("phase") or "")
            purpose = str(beat.get("visual_purpose") or "").strip()
            related = performance_by_line.get(int(beat.get("anchor_line") or 0), [])
            has_change = any(
                str(item.get("action_intent") or "none") != "none"
                or str(item.get("emoticon_intent") or "none") != "none"
                for item in related
            )
            if not purpose and not has_change and phase not in {"await_response", "decision_pause"}:
                issues.append(_issue(
                    "empty_silent_purpose",
                    "无对白节点没有继承表情以外的画面目的。",
                    anchor_line=beat.get("anchor_line"),
                ))

    return {
        "result": "pass" if not issues else "fail",
        "issues": issues,
        "statistics": {
            "shot_steps": len(shots),
            "impact_lines": sum(len(chain.get("impact_lines") or []) for chain in plan.get("event_chains") or []),
            "performance_beats": sum(len(chain.get("performance_beats") or []) for chain in plan.get("event_chains") or []),
        },
    }


_CONCRETE_PLAN_ASSET_RE = re.compile(
    r"focus\s*line|focusline|集中线|\b(?:jump|hophop|stiff|shake|greeting)\b",
    re.IGNORECASE,
)
_OPENING_ARRIVAL_RE = re.compile(
    r"(?:刚到|刚来|走进|进入|到达|抵达|推门|开门|赶来|跑进|回来了|回到)"
)

# Event kinds are descriptive labels, not templates. Only phases the planner
# explicitly selected are checked for ordering or execution.
_EVENT_REQUIRED_PHASES: dict[str, set[str]] = {}
_EVENT_REQUIRED_SILENT_PHASES: dict[str, set[str]] = {}
_REACTION_DRIVEN_EVENT_KINDS = {
    "group_escalation", "discovery", "inference", "invitation", "decision",
    "aftermath",
}
_VISIBLE_PERFORMANCE_CARRIERS = {"face_change", "emoticon", "action"}
_EVENT_PHASE_DEPENDENCIES = (
    ("cue", "reveal"),
    ("reveal", "group_reaction"),
    ("group_reaction", "focus_handoff"),
    ("object_action", "feedback"),
    ("feedback", "verification"),
    ("verification", "result"),
    ("object_action", "result"),
    ("decision_pause", "result"),
    ("time_bridge", "aftershock"),
    ("time_bridge", "relay"),
)


def _plan_result(issues: Sequence[Mapping[str, Any]]) -> str:
    return "fail" if any(
        str(issue.get("severity") or "high") in {"critical", "high"}
        for issue in issues
    ) else "pass"


def _event_source_order(event: Mapping[str, Any]) -> dict[str, int]:
    return {
        str(source_id): index
        for index, source_id in enumerate(event.get("source_ids") or [])
        if str(source_id)
    }


def _ordered_event_groups(event: Mapping[str, Any]) -> list[dict[str, Any]]:
    order = _event_source_order(event)
    groups = [
        dict(group) for group in event.get("shot_groups") or []
        if isinstance(group, Mapping)
    ]
    return sorted(
        groups,
        key=lambda group: (
            order.get(str(group.get("anchor_id") or ""), len(order)),
            str(group.get("group_id") or ""),
        ),
    )


def _cast_member_is_displayable(
    name: str, cast: Mapping[str, Any] | None,
) -> bool:
    if not name or not isinstance(cast, Mapping):
        return True
    value = cast.get(name)
    return bool(
        isinstance(value, Mapping)
        and value.get("portrait")
        and not value.get("narrator")
    )


def _plan_group_covering_anchor(
    plan: Mapping[str, Any] | None, anchor_id: str,
) -> Mapping[str, Any] | None:
    for event in (plan or {}).get("events") or []:
        if not isinstance(event, Mapping):
            continue
        order = _event_source_order(event)
        anchor_at = order.get(str(anchor_id))
        if anchor_at is None:
            continue
        covering = None
        for group in _ordered_event_groups(event):
            start_at = order.get(str(group.get("anchor_id") or ""))
            end_at = order.get(str(group.get("hold_until_id") or group.get("anchor_id") or ""))
            if start_at is None or end_at is None or not start_at <= anchor_at <= end_at:
                continue
            covering = group
        if covering is not None:
            return covering
    return None


def _displayable_group_contract(
    group: Mapping[str, Any] | None, cast: Mapping[str, Any] | None,
) -> tuple[list[str], list[str]]:
    members = [str(value) for value in (group or {}).get("members") or [] if str(value)]
    visible = [name for name in members if _cast_member_is_displayable(name, cast)]
    offscreen = [name for name in members if name not in visible]
    offscreen.extend(
        str(value) for value in (group or {}).get("_offscreen_members") or []
        if str(value) and str(value) not in offscreen
    )
    return visible, offscreen


def validate_plan_quality(
    plan: Mapping[str, Any], *, targets: Sequence[Mapping[str, Any]] = (),
    cast: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate Plan IR v2 without imposing shot or performance quotas."""
    if not isinstance(plan, Mapping):
        return {
            "result": "fail",
            "issues": [_issue(
                "invalid_plan", "计划必须是对象。", severity="critical",
            )],
            "statistics": {},
        }
    if "events" not in plan and "event_chains" in plan:
        return validate_director_plan(plan)

    raw_events = [event for event in plan.get("events") or [] if isinstance(event, Mapping)]
    legacy_events = [
        event for event in raw_events
        if "peak_character" in event
        and any(not isinstance(group, Mapping) for group in event.get("shot_groups") or [])
    ]
    if raw_events and len(legacy_events) == len(raw_events):
        return {
            "result": "pass",
            "issues": [_issue(
                "legacy_plan_v1",
                "旧 checkpoint 计划保持可读，但不具备 Plan IR v2 的质量保证。",
                severity="info",
            )],
            "statistics": {"events": len(raw_events), "legacy_events": len(raw_events)},
        }

    issues: list[dict[str, Any]] = []
    event_count = 0
    shot_group_count = 0
    peak_count = 0
    silent_count = 0

    scene_targets = [target for target in targets if isinstance(target, Mapping)]
    if scene_targets:
        first_target = scene_targets[0]
        first_id = str(first_target.get("annotation_id") or "")
        first_text = str(first_target.get("text") or "")
        arrival_planned = any(
            isinstance(event, Mapping)
            and str(event.get("kind") or "") == "arrival"
            and (
                not first_id
                or first_id in {str(value) for value in event.get("source_ids") or []}
            )
            for event in plan.get("events") or []
        )
        if _OPENING_ARRIVAL_RE.search(first_text) and not arrival_planned:
            issues.append(_issue(
                "opening_arrival_event_missing",
                "场景开头有明确的物理到场动作，但事件计划没有 arrival；记录供导演复核，不自动补入场。",
                severity="warning", anchor_id=first_id,
                speaker=str(first_target.get("who") or ""),
            ))

    for event in plan.get("events") or []:
        if not isinstance(event, Mapping):
            issues.append(_issue(
                "invalid_event", "事件计划项必须是对象。", severity="critical",
            ))
            continue
        event_count += 1
        event_id = str(event.get("event_id") or f"event-{event_count}")
        if event.get("overlaps_previous"):
            issues.append(_issue(
                "overlapping_events",
                "事件区间与前一事件重叠；返修边界和状态归属会产生歧义。",
                severity="high", event_id=event_id,
            ))

        kind = str(event.get("kind") or "")
        phase_order = [
            str(value) for value in event.get("phase_order") or [] if str(value)
        ]
        phase_index = {phase: index for index, phase in enumerate(phase_order)}
        if len(phase_index) != len(phase_order):
            issues.append(_issue(
                "duplicate_event_phase", "事件 phase_order 重复声明同一阶段。",
                severity="high", event_id=event_id, phase_order=phase_order,
            ))
        missing_phases = sorted(_EVENT_REQUIRED_PHASES.get(kind, set()) - set(phase_order))
        if missing_phases:
            issues.append(_issue(
                "event_required_phase_missing",
                f"{kind} 事件未采用建议阶段：{'/'.join(missing_phases)}；事件类型不能替代当前文本的因果判断。",
                severity="warning", event_id=event_id, missing=missing_phases,
            ))
        for earlier, later in _EVENT_PHASE_DEPENDENCIES:
            if earlier in phase_index and later in phase_index and phase_index[earlier] >= phase_index[later]:
                issues.append(_issue(
                    "event_phase_dependency_reversed",
                    f"事件阶段没有采用常见顺序：{earlier} -> {later}；请按当前文本确认是否有意如此。",
                    severity="warning", event_id=event_id,
                    earlier=earlier, later=later,
                ))

        groups = _ordered_event_groups(event)
        shot_group_count += len(groups)
        previous: dict[str, Any] | None = None
        previous_hold_index = -1
        source_order = _event_source_order(event)
        for group in groups:
            members = [str(value) for value in group.get("members") or [] if str(value)]
            focus = str(group.get("focus") or "")
            operation = str(group.get("operation") or "")
            cut_motivation = str(group.get("cut_motivation") or "").strip()
            anchor_id = str(group.get("anchor_id") or "")
            hold_until_id = str(group.get("hold_until_id") or anchor_id)
            anchor_index = source_order.get(anchor_id, -1)
            hold_index = source_order.get(hold_until_id, -1)
            if anchor_index < 0 or hold_index < anchor_index:
                issues.append(_issue(
                    "invalid_shot_hold_range",
                    "连续镜头区间的 hold_until 必须位于开始锚点之后，并属于同一事件。",
                    severity="high", event_id=event_id, anchor_id=anchor_id,
                    hold_until_id=hold_until_id,
                ))
            elif anchor_index <= previous_hold_index:
                issues.append(_issue(
                    "overlapping_shot_hold_ranges",
                    "连续镜头区间互相重叠，第二阶段无法确定应保持哪幅构图。",
                    severity="high", event_id=event_id, anchor_id=anchor_id,
                    hold_until_id=hold_until_id,
                ))
            previous_hold_index = max(previous_hold_index, hold_index)
            if len(members) > 3:
                issues.append(_issue(
                    "plan_visible_over_three", "计划镜头超过三名可见人物。",
                    severity="critical", event_id=event_id, anchor_id=anchor_id,
                    members=members,
                ))
            if focus and focus not in members:
                issues.append(_issue(
                    "plan_focus_not_visible", "计划焦点不在镜头成员中。",
                    severity="high", event_id=event_id, anchor_id=anchor_id,
                    focus=focus, members=members,
                ))
            if previous is not None:
                signature = (
                    tuple(members), focus, str(group.get("framing") or ""),
                )
                previous_signature = (
                    tuple(str(value) for value in previous.get("members") or []),
                    str(previous.get("focus") or ""),
                    str(previous.get("framing") or ""),
                )
                if signature == previous_signature and operation in {"hold", "reframe"}:
                    issues.append(_issue(
                        "shot_step_redundant",
                        "连续镜头重复声明同组、同焦点和同景别；应保持上一镜。",
                        severity="high", event_id=event_id, anchor_id=anchor_id,
                    ))
                old_members = {
                    str(value) for value in previous.get("members") or [] if str(value)
                }
                new_members = set(members)
                if (
                    len(old_members) > 1
                    and len(new_members) == 1
                    and str(group.get("framing") or "") in {"close", "medium_close"}
                    and operation not in {"switch", "anchor_match_cut"}
                ):
                    issues.append(_issue(
                        "closeup_requires_hard_cut",
                        "多人镜头进入单人近景必须完整硬切，不能用 hold/reframe/shrink 模拟软推近。",
                        severity="high", event_id=event_id, anchor_id=anchor_id,
                        previous=sorted(old_members), current=members,
                        operation=operation,
                    ))
                if len(old_members) == len(new_members) == 2 and len(old_members & new_members) == 1:
                    allowed_anchor_cut = (
                        operation in {
                            "anchor_match_cut", "switch", "switch_group", "impact_insert",
                        }
                        and bool(cut_motivation)
                    )
                    if not allowed_anchor_cut:
                        issues.append(_issue(
                            "plan_stationary_pair_swap",
                            "双人镜头只替换一人，但没有收镜/扩镜或有理由的 anchor match cut。",
                            severity="high", event_id=event_id, anchor_id=anchor_id,
                            previous=sorted(old_members), current=members,
                        ))
            previous = group

        group_by_anchor = {
            str(group.get("anchor_id") or ""): group for group in groups
            if str(group.get("anchor_id") or "")
        }

        def group_covering_anchor(anchor_id: str) -> Mapping[str, Any] | None:
            """Resolve a peak to the shot that covers its held range.

            Peaks are attached to an exact target anchor, while a shot group
            may begin earlier and hold through that anchor.  Prefer the exact
            start for backwards compatibility, then use the declared
            ``hold_until`` range instead of treating a valid held relation
            shot as an empty group.
            """
            exact = group_by_anchor.get(anchor_id)
            if exact is not None:
                return exact
            peak_index = source_order.get(anchor_id, -1)
            if peak_index < 0:
                return None
            for candidate in groups:
                start = source_order.get(str(candidate.get("anchor_id") or ""), -1)
                end = source_order.get(
                    str(candidate.get("hold_until_id") or candidate.get("anchor_id") or ""),
                    start,
                )
                if start <= peak_index <= end:
                    return candidate
            return None
        performance_by_anchor: dict[str, list[Mapping[str, Any]]] = {}
        for intent in event.get("performance_intents") or []:
            if not isinstance(intent, Mapping):
                continue
            intent_anchor = str(intent.get("anchor_id") or "")
            performance_by_anchor.setdefault(intent_anchor, []).append(intent)

        event_performance_carriers = {
            str(carrier)
            for intents in performance_by_anchor.values()
            for intent in intents
            for carrier in intent.get("carriers") or []
            if str(carrier)
        }
        if (
            kind in _REACTION_DRIVEN_EVENT_KINDS
            and not event_performance_carriers & _VISIBLE_PERFORMANCE_CARRIERS
        ):
            issues.append(_issue(
                "reaction_event_without_performance_intent",
                f"{kind} 事件依赖人物反应，但没有规划 face/body/emoticon 表演载体。",
                severity="high", event_id=event_id,
            ))

        stimulus_targets = {
            str(value) for value in event.get("stimulus_targets") or [] if str(value)
        }
        result_owner = str(event.get("result_owner") or "")
        aftershock_owner = str(event.get("aftershock_owner") or "")
        release_owner = str(event.get("release_owner") or "")
        for owner_field, owner, phase in (
            ("result_owner", result_owner, "result"),
            ("aftershock_owner", aftershock_owner, "aftershock"),
        ):
            if owner and phase not in phase_index:
                issues.append(_issue(
                    "event_owner_phase_missing",
                    f"{owner_field} 声明了 {owner}，但事件没有命名为 {phase} 的阶段；保留所有权并按文本因果执行。",
                    severity="warning", event_id=event_id, owner_field=owner_field,
                    owner=owner, phase=phase,
                ))
        if release_owner and not any(
            isinstance(peak, Mapping) for peak in event.get("peaks") or []
        ):
            issues.append(_issue(
                "release_owner_without_peak",
                f"release_owner 声明了 {release_owner}，但事件没有显式 peak；保留该余波提示，不据此制造峰值。",
                severity="warning", event_id=event_id, owner=release_owner,
            ))
        # ``stimulus_targets`` describes everyone directly touched by an event;
        # it does not imply a synchronous group reaction or a shared
        # aftershock. Those are staging choices: the text may support a
        # staggered relay, a single owner of the consequence, or an observer
        # who only reacts later. Validate participants when the plan declares
        # a group phase, but do not force one merely because the set has size 2+.
        silent_timeline = []
        planned_silent_phases: set[str] = set()
        source_order = _event_source_order(event)
        for beat_ordinal, beat in enumerate(event.get("silent_beats") or []):
            if not isinstance(beat, Mapping):
                continue
            silent_count += 1
            phase = str(beat.get("phase") or "")
            if phase:
                planned_silent_phases.add(phase)
            anchor_id = str(beat.get("anchor_id") or "")
            position = str(beat.get("position") or "after")
            silent_timeline.append((
                source_order.get(anchor_id, len(source_order)),
                0 if position == "before" else 2,
                beat_ordinal,
                phase,
                anchor_id,
            ))
            carrier = beat.get("carrier_requirement")
            any_of = (
                [str(value) for value in carrier.get("any_of") or [] if str(value)]
                if isinstance(carrier, Mapping) else []
            )
            if not any_of:
                issues.append(_issue(
                    "silent_phase_no_carrier",
                    "无对话框计划没有声明可读载体。",
                    severity="high", event_id=event_id,
                    anchor_id=str(beat.get("anchor_id") or ""),
                ))
            if phase and phase not in phase_index:
                issues.append(_issue(
                    "silent_phase_not_declared",
                    f"无对话框阶段 {phase} 没有出现在事件 phase_order 中。",
                    severity="high", event_id=event_id, anchor_id=anchor_id,
                ))
            participants = {
                str(value) for value in beat.get("participants") or [] if str(value)
            }
            if phase == "group_reaction" and (
                len(participants) < 2
                or (stimulus_targets and not participants <= stimulus_targets)
            ):
                issues.append(_issue(
                    "group_reaction_stimulus_mismatch",
                    "共同反应者必须是同一刺激真正作用到的两至三人，不能取邻近说话者或当前镜头全员。",
                    severity="warning", event_id=event_id, anchor_id=anchor_id,
                    participants=sorted(participants),
                    stimulus_targets=sorted(stimulus_targets),
                ))
            phase_owner = (
                result_owner if phase == "result" else
                aftershock_owner if phase == "aftershock" else ""
            )
            if phase_owner and participants and phase_owner not in participants:
                issues.append(_issue(
                    "event_owner_participant_mismatch",
                    f"{phase} 的所有权已交给 {phase_owner}，但对应无对话框拍没有包含该人物。",
                    severity="high", event_id=event_id, anchor_id=anchor_id,
                    phase=phase, owner=phase_owner,
                    participants=sorted(participants),
                ))
            if kind == "arrival" and phase == "reveal" and "entry_exit" not in any_of:
                issues.append(_issue(
                    "arrival_without_entry_carrier",
                    "arrival 事件的 reveal 阶段必须要求真实入场载体，不能只靠普通切镜。",
                    severity="high", event_id=event_id, anchor_id=anchor_id,
                ))
            if phase != "decision_pause" and set(any_of) == {"pose_hold"}:
                issues.append(_issue(
                    "silent_pose_hold_without_pause",
                    "只有有明确目的的 decision_pause 可以只依赖 pose hold。",
                    severity="high", event_id=event_id, anchor_id=anchor_id,
                ))

        missing_silent_phases = sorted(
            _EVENT_REQUIRED_SILENT_PHASES.get(kind, set()) - planned_silent_phases
        )
        # A semantic phase can be carried by dialogue. Only object-test
        # feedback/verification are silent requirements because their causal
        # state must be observable between action and result.
        required_silent_phases = ["group_reaction"]
        if kind == "object_test":
            required_silent_phases.extend(("feedback", "verification"))
        for optional_silent_phase in required_silent_phases:
                if (
                    optional_silent_phase in phase_index
                    and optional_silent_phase not in planned_silent_phases
                ):
                    missing_silent_phases.append(optional_silent_phase)
        missing_silent_phases = sorted(set(missing_silent_phases))
        if missing_silent_phases:
            issues.append(_issue(
                "event_required_silent_phase_missing",
                f"{kind} 事件未把建议阶段实现为无对话框拍：{'/'.join(missing_silent_phases)}；仅在它承载对白无法表达的新信息时补拍。",
                severity="warning", event_id=event_id, missing=missing_silent_phases,
            ))

        previous_phase_rank = -1
        for _line, _position, _ordinal, phase, anchor_id in sorted(silent_timeline):
            rank = phase_index.get(phase)
            if rank is None:
                continue
            if rank < previous_phase_rank:
                issues.append(_issue(
                    "silent_phase_timeline_reversed",
                    "无对话框执行阶段的锚点顺序与事件因果顺序相反。",
                    severity="high", event_id=event_id, anchor_id=anchor_id,
                    phase=phase,
                ))
            previous_phase_rank = max(previous_phase_rank, rank)

        for peak in event.get("peaks") or []:
            if not isinstance(peak, Mapping):
                continue
            peak_count += 1
            peak_id = str(peak.get("peak_id") or "")
            subject = str(peak.get("subject") or "")
            peak_type = str(peak.get("peak_type") or "")
            group = group_covering_anchor(peak_id)
            members = [
                str(value) for value in (group or {}).get("members") or [] if str(value)
            ]
            displayable_members, offscreen_members = _displayable_group_contract(group, cast)
            framing = str((group or {}).get("framing") or "")
            if peak_type == "solo_emphasis":
                if displayable_members != [subject] or framing not in {"close", "medium_close"}:
                    issues.append(_issue(
                        "solo_emphasis_not_solo",
                        "solo_emphasis 必须在同一锚点建立主体单人近景。",
                        severity="high", event_id=event_id, anchor_id=peak_id,
                        subject=subject, members=members, framing=framing,
                    ))
            elif peak_type == "relationship_peak":
                valid_offscreen_pair = (
                    displayable_members == [subject] and bool(offscreen_members)
                )
                if not valid_offscreen_pair and (
                    len(displayable_members) != 2 or subject not in displayable_members
                ):
                    issues.append(_issue(
                        "relationship_peak_bad_group",
                        "relationship_peak 必须保留包含主体的双人关系构图。",
                        severity="high", event_id=event_id, anchor_id=peak_id,
                        subject=subject, members=members,
                    ))
            elif peak_type == "group_reaction":
                valid_offscreen_group = (
                    displayable_members == [subject] and bool(offscreen_members)
                )
                if not valid_offscreen_group and (
                    not 2 <= len(displayable_members) <= 3
                    or subject not in displayable_members
                ):
                    issues.append(_issue(
                        "group_reaction_bad_group",
                        "group_reaction 必须是包含主体的二至三人共同反应构图。",
                        severity="high", event_id=event_id, anchor_id=peak_id,
                        subject=subject, members=members,
                    ))
            else:
                issues.append(_issue(
                    "invalid_peak_type", "峰值类型无效。", severity="high",
                    event_id=event_id, anchor_id=peak_id, peak_type=peak_type,
                ))

            release_position = str(peak.get("release_position") or "")
            release_id = str(peak.get("release_id") or "")
            if release_position not in {"next_event", "scene_end"} and not release_id:
                issues.append(_issue(
                    "peak_without_release", "峰值没有可定位的释放点。",
                    severity="high", event_id=event_id, anchor_id=peak_id,
                ))

            intents = performance_by_anchor.get(peak_id, [])
            explicit_carriers = {
                str(carrier)
                for intent in intents
                for carrier in intent.get("carriers") or []
                if str(carrier)
            }
            has_camera_carrier = bool(group and str(group.get("operation") or "") != "hold")
            if not explicit_carriers and not has_camera_carrier:
                issues.append(_issue(
                    "impact_performance_missing",
                    "峰值没有 face/body/emoticon/camera 等可读承载意图。",
                    severity="high", event_id=event_id, anchor_id=peak_id,
                ))
            if (
                peak_type == "solo_emphasis"
                and not explicit_carriers & {"face_change", "emoticon", "action"}
            ):
                issues.append(_issue(
                    "solo_emphasis_without_performance_carrier",
                    "solo_emphasis 不能只有镜头变化；必须规划 face/body/emoticon 中至少一种可读表演。",
                    severity="high", event_id=event_id, anchor_id=peak_id,
                ))
            if _CONCRETE_PLAN_ASSET_RE.search(str(peak.get("visual_intent") or "")):
                issues.append(_issue(
                    "concrete_asset_in_plan",
                    "第一阶段只能描述视觉意图，不能指定具体 AA 效果或动作。",
                    severity="high", event_id=event_id, anchor_id=peak_id,
                ))

        for arc in event.get("face_arcs") or []:
            if not isinstance(arc, Mapping):
                continue
            who = str(arc.get("who") or "")
            previous_stage: Mapping[str, Any] | None = None
            for stage in arc.get("stages") or []:
                if not isinstance(stage, Mapping):
                    continue
                anchor_id = str(stage.get("anchor_id") or "")
                if not str(stage.get("semantic_state") or "").strip() or not str(
                    stage.get("change_reason") or ""
                ).strip():
                    issues.append(_issue(
                        "face_stage_without_reason",
                        "表情阶段必须同时说明语义状态与变化原因。",
                        severity="high", event_id=event_id,
                        anchor_id=anchor_id,
                    ))
                semantic_changed = bool(
                    previous_stage is not None
                    and str(previous_stage.get("semantic_state") or "")
                    != str(stage.get("semantic_state") or "")
                )
                if semantic_changed:
                    position = str(stage.get("position") or "on")
                    matching_intents = [
                        intent for intent in performance_by_anchor.get(anchor_id, [])
                        if str(intent.get("position") or "on") == position
                        and who in {
                            str(subject) for subject in intent.get("subjects") or []
                            if str(subject)
                        }
                    ]
                    if not any(
                        _VISIBLE_PERFORMANCE_CARRIERS & {
                            str(carrier) for carrier in intent.get("carriers") or []
                        }
                        for intent in matching_intents
                    ):
                        issues.append(_issue(
                            "face_stage_change_without_intent",
                            f"{who} 的表情语义阶段发生变化，但对应锚点没有可读表演意图。",
                            severity="high", event_id=event_id,
                            anchor_id=anchor_id, who=who,
                        ))
                previous_stage = stage

    return {
        "result": _plan_result(issues),
        "issues": issues,
        "statistics": {
            "events": event_count,
            "shot_groups": shot_group_count,
            "peaks": peak_count,
            "silent_beats": silent_count,
        },
    }


_ARRIVAL_RE = re.compile(
    r"(?:刚到|刚来|来到|我来了|赶来|前来|走进|进入|到达|抵达|推门|开门|跑进|回来了|回到|欢迎回来)"
)
_HEAVY_FX_RE = re.compile(r"(?:集中线|FocusLine|BG_FocusLine|闪白|BG_Flash)", re.IGNORECASE)


def sanitize_execution_beats(
    beats: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Copy validated beats without reinterpreting legal face IDs as placeholders."""
    return [copy.deepcopy(dict(beat)) for beat in beats], []


def _planned_shot_spans(
    plan: Mapping[str, Any] | None,
) -> tuple[dict[str, dict[str, Any]], set[tuple[str, str]]]:
    """Expand planned shot intervals to source ids for deterministic G2 checks."""
    spans: dict[str, dict[str, Any]] = {}
    silent_camera_changes: set[tuple[str, str]] = set()
    for event in (plan or {}).get("events") or []:
        if not isinstance(event, Mapping):
            continue
        source_ids = [str(value) for value in event.get("source_ids") or [] if str(value)]
        order = {source_id: index for index, source_id in enumerate(source_ids)}
        for group in event.get("shot_groups") or []:
            if not isinstance(group, Mapping):
                continue
            anchor_id = str(group.get("anchor_id") or "")
            hold_until_id = str(group.get("hold_until_id") or anchor_id)
            start = order.get(anchor_id)
            end = order.get(hold_until_id)
            if start is None or end is None or end < start:
                continue
            descriptor = {
                **dict(group),
                "event_id": str(event.get("event_id") or ""),
                "anchor_id": anchor_id,
                "hold_until_id": hold_until_id,
            }
            for source_id in source_ids[start:end + 1]:
                spans[source_id] = descriptor
        for beat in event.get("silent_beats") or []:
            if not isinstance(beat, Mapping):
                continue
            requirement = beat.get("carrier_requirement")
            carriers = {
                str(value) for value in (requirement or {}).get("any_of") or []
                if str(value)
            } if isinstance(requirement, Mapping) else set()
            if "camera_change" in carriers:
                silent_camera_changes.add((
                    str(beat.get("anchor_id") or ""),
                    str(beat.get("position") or "after"),
                ))
    return spans, silent_camera_changes


def _execution_carriers(value: Mapping[str, Any], *, camera_changed: bool = False) -> set[str]:
    reactions = [
        reaction for reaction in value.get("reactions") or []
        if isinstance(reaction, Mapping)
    ]
    carriers: set[str] = set()
    if value.get("face") or any(reaction.get("face") for reaction in reactions):
        carriers.add("face_change")
    if value.get("emo") or any(reaction.get("emo") for reaction in reactions):
        carriers.add("emoticon")
    if value.get("act") or any(reaction.get("act") for reaction in reactions):
        carriers.add("action")
    if value.get("se"):
        carriers.add("sound")
    direction = value.get("direction") if isinstance(value.get("direction"), Mapping) else {}
    intent = value.get("direction_intent") if isinstance(value.get("direction_intent"), Mapping) else {}
    if camera_changed or any(
        key in intent for key in ("visible_characters", "positions", "shot_transition", "shot_operation")
    ) or any(value.get(key) for key in ("visible_characters", "positions", "shot_transition", "shot_operation")):
        carriers.add("camera_change")
    if value.get("move") or value.get("reveal") or value.get("conceal") or value.get("enter") or value.get("exit"):
        carriers.add("movement")
    if value.get("reveal") or value.get("conceal") or value.get("enter") or value.get("exit"):
        carriers.add("entry_exit")
    if value.get("bg") or value.get("bgfx") or value.get("trans") or value.get("place"):
        carriers.add("background_change")
    if int(value.get("wait_ms") or 0) > 0:
        carriers.add("pose_hold")
    if direction and not intent:
        # A normalized default director object is not evidence of an authored camera change.
        carriers.discard("camera_change")
    return carriers


def _planned_anchor_maps(plan: Mapping[str, Any] | None) -> tuple[dict[str, list[Mapping[str, Any]]], dict[str, list[Mapping[str, Any]]]]:
    peaks: dict[str, list[Mapping[str, Any]]] = {}
    intents: dict[str, list[Mapping[str, Any]]] = {}
    for event in (plan or {}).get("events") or []:
        if not isinstance(event, Mapping):
            continue
        event_id = str(event.get("event_id") or "")
        for peak in event.get("peaks") or []:
            if isinstance(peak, Mapping):
                anchor = str(peak.get("peak_id") or "")
                peaks.setdefault(anchor, []).append({**dict(peak), "_event_id": event_id})
        for intent in event.get("performance_intents") or []:
            if isinstance(intent, Mapping):
                anchor = str(intent.get("anchor_id") or "")
                intents.setdefault(anchor, []).append({**dict(intent), "_event_id": event_id})
    return peaks, intents


def validate_execution_quality(
    plan: Mapping[str, Any] | None,
    targets: Sequence[Mapping[str, Any]],
    lines_by_id: Mapping[str, Mapping[str, Any]],
    beats: Sequence[Mapping[str, Any]],
    *, memory: Mapping[str, Any] | None = None,
    cast: Mapping[str, Any] | None = None,
    constraints: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate concrete chunk execution against Plan IR v2 and prior state."""
    from annotation_scene_planner import event_plan_fulfillment_errors

    cast = cast or {}
    constraints = constraints or {}
    target_ids = [str(item.get("annotation_id") or "") for item in targets]
    target_by_id = {str(item.get("annotation_id") or ""): item for item in targets}
    issues: list[dict[str, Any]] = []
    planned_spans, planned_silent_camera_changes = _planned_shot_spans(plan)
    reported_span_mismatches: set[tuple[str, str]] = set()
    for detail in event_plan_fulfillment_errors(
        plan, target_ids, beats, cast=cast,
    ):
        match = re.search(r"@([^/]+)/", detail)
        issues.append(_issue(
            "missing_planned_silent_phase", detail, severity="high",
            anchor_id=match.group(1) if match else "",
        ))

    beats_by_anchor: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for beat in beats:
        beats_by_anchor.setdefault((
            str(beat.get("anchor_id") or ""), str(beat.get("position") or "after"),
        ), []).append(beat)

    direction = (memory or {}).get("direction") if isinstance(memory, Mapping) else {}
    direction = direction if isinstance(direction, Mapping) else {}
    camera = [str(name) for name in direction.get("shot_visible_characters") or direction.get("visible_characters") or [] if str(name)]
    positions = dict(direction.get("positions") or {})
    presence = {
        str(name): str(status) for name, status in dict(direction.get("scene_presence") or {}).items()
        if status in {"unknown", "present", "absent"}
    }
    snapshots: dict[tuple[str, str], dict[str, Any]] = {}
    carriers_by_anchor: dict[tuple[str, str], set[str]] = {}
    carriers_by_subject: dict[tuple[str, str, str], set[str]] = {}
    face_state = {
        str(name): str(face)
        for name, face in dict(direction.get("last_faces") or {}).items()
        if str(name) and str(face)
    }
    initial_camera = tuple(camera)
    initial_positions = tuple(sorted(positions.items()))
    initial_faces = dict(face_state)
    performance_signatures: dict[tuple[str, str, str], tuple[Any, ...]] = {}
    explicit_faces: dict[tuple[str, str, str], str] = {}
    previous_camera = tuple(camera)
    # This is a director-quality signal, not a compiler correction.  A full
    # hard cut is legal, but repeatedly holding one person in the same slot
    # while rotating their partner creates the "fixed host / flashing guest"
    # pattern the next G2 call needs to reconsider.
    camera_cut_history: list[dict[str, Any]] = []
    target_position = {source_id: index for index, source_id in enumerate(target_ids)}

    def equivalent_timeline_keys(anchor_id: str, position: str) -> list[tuple[str, str]]:
        """Treat previous-after and next-before as the same dialogue boundary."""
        keys = [(anchor_id, position)]
        index = target_position.get(anchor_id, -1)
        if position == "before" and index > 0:
            keys.append((target_ids[index - 1], "after"))
        elif position == "after" and 0 <= index < len(target_ids) - 1:
            keys.append((target_ids[index + 1], "before"))
        return keys

    def boundary_carriers(anchor_id: str, position: str) -> set[str]:
        observed: set[str] = set()
        for key in equivalent_timeline_keys(anchor_id, position):
            observed.update(carriers_by_anchor.get(key, set()))
        return observed

    def boundary_subject_carriers(anchor_id: str, position: str, who: str) -> set[str]:
        observed: set[str] = set()
        keys = equivalent_timeline_keys(anchor_id, position)
        anchor_speaker = str((target_by_id.get(anchor_id) or {}).get("who") or "")
        if position == "after" and who and who != anchor_speaker:
            # A line-level reaction belongs to the same visible beat as the
            # dialogue/narration stimulus.  It may therefore realize G1's
            # "after the information lands" listener intent without forcing
            # an otherwise unnecessary silent node.
            keys.append((anchor_id, "on"))
        for key_anchor, key_position in keys:
            observed.update(carriers_by_subject.get((key_anchor, key_position, who), set()))
        return observed

    def boundary_value(
        values: Mapping[tuple[str, str, str], Any],
        anchor_id: str, position: str, who: str,
    ) -> Any:
        for key_anchor, key_position in equivalent_timeline_keys(anchor_id, position):
            key = (key_anchor, key_position, who)
            if key in values:
                return values[key]
        return None

    def arrival_evidence(anchor_id: str) -> bool:
        index = target_position.get(anchor_id, -1)
        candidates = (
            targets[max(0, index - 1):min(len(targets), index + 2)]
            if index >= 0 else []
        )
        for event in (plan or {}).get("events") or []:
            if not isinstance(event, Mapping) or str(event.get("kind") or "") != "arrival":
                continue
            source_ids = [str(value) for value in event.get("source_ids") or []]
            if anchor_id not in source_ids:
                continue
            candidates = [
                target_by_id[source_id]
                for source_id in source_ids if source_id in target_by_id
            ]
            break
        return any(
            _ARRIVAL_RE.search(str(item.get("text") or ""))
            for item in candidates
        )

    def apply_event(value: Mapping[str, Any], anchor_id: str, position: str, *, speaker: str = "") -> None:
        nonlocal camera, positions, previous_camera
        before_camera = tuple(camera)
        before_positions = dict(positions)
        before_faces = dict(face_state)
        intent = value.get("direction_intent") if isinstance(value.get("direction_intent"), Mapping) else {}
        authored_direction = value.get("direction") if isinstance(value.get("direction"), Mapping) else {}
        if "visible_characters" in intent:
            camera = [str(name) for name in authored_direction.get("visible_characters") or [] if str(name)][:3]
        elif "visible_characters" in value:
            camera = [str(name) for name in value.get("visible_characters") or [] if str(name)][:3]
        if "positions" in intent:
            positions = dict(authored_direction.get("positions") or {})
        elif "positions" in value:
            positions = dict(value.get("positions") or {})

        line_reveal = str(value.get("reveal") or "")
        reveals = list(value.get("reveal") or []) if isinstance(value.get("reveal"), list) else []
        if line_reveal and speaker:
            reveals.append({"who": speaker})
        enters = list(value.get("enter") or [])
        conceals = list(value.get("conceal") or [])
        exits = list(value.get("exit") or [])
        for entry in reveals:
            name = str(entry.get("who") or "") if isinstance(entry, Mapping) else ""
            if not name:
                continue
            if presence.get(name) == "absent":
                issues.append(_issue(
                    "reveal_person_not_present",
                    f"{name} 已明确离场，不能只用 reveal 重新出现。",
                    severity="high", anchor_id=anchor_id,
                ))
            presence[name] = "present"
            if name not in camera:
                camera.append(name)
        for entry in enters:
            name = str(entry.get("who") or "") if isinstance(entry, Mapping) else ""
            if not name:
                continue
            if presence.get(name) == "present":
                issues.append(_issue(
                    "enter_person_already_present", f"{name} 已在当前场景中，不能再次 enter。",
                    severity="high", anchor_id=anchor_id,
                ))
            elif not arrival_evidence(anchor_id):
                issues.append(_issue(
                    "enter_without_arrival_evidence",
                    f"{name} 的 enter 缺少文本中的真实到场证据；首次建镜应使用 reveal/cut。",
                    severity="high", anchor_id=anchor_id,
                ))
            presence[name] = "present"
            if name not in camera:
                camera.append(name)
        for entry in conceals:
            name = str(entry.get("who") or "") if isinstance(entry, Mapping) else ""
            if not name:
                continue
            if name not in before_camera:
                issues.append(_issue(
                    "conceal_person_not_visible",
                    f"{name} 不在当前镜头中，不能执行 conceal。",
                    severity="high", anchor_id=anchor_id,
                ))
            # Visual-only departure: remove the portrait and its slot while
            # retaining physical scene presence for a later reveal or cut.
            presence[name] = "present"
            camera = [visible for visible in camera if visible != name]
            positions.pop(name, None)
        for entry in exits:
            name = str(entry.get("who") or "") if isinstance(entry, Mapping) else ""
            if name:
                presence[name] = "absent"
                camera = [visible for visible in camera if visible != name]
                positions.pop(name, None)

        if len(camera) > 3:
            issues.append(_issue(
                "visible_over_three", "执行镜头超过三名可见人物。",
                severity="critical", anchor_id=anchor_id, visible=list(camera),
            ))
        if len(set(positions.values())) != len(positions):
            issues.append(_issue(
                "unsafe_spacing", "执行镜头存在重复槽位。",
                severity="critical", anchor_id=anchor_id, positions=dict(positions),
            ))
        profiles = constraints.get("portrait_profiles_by_name") or {}
        positioned = list(positions)
        for index, first in enumerate(positioned):
            for second in positioned[index + 1:]:
                required = max(
                    int((profiles.get(first) or {}).get("min_slot_gap") or 1),
                    int((profiles.get(second) or {}).get("min_slot_gap") or 1),
                )
                if abs(int(positions[first]) - int(positions[second])) < required:
                    issues.append(_issue(
                        "unsafe_spacing", f"{first} 与 {second} 的立绘会重叠。",
                        severity="critical", anchor_id=anchor_id, positions=dict(positions),
                    ))

        operation = str(authored_direction.get("shot_operation") or value.get("shot_operation") or "")
        transition = str(authored_direction.get("shot_transition") or value.get("shot_transition") or "")
        if len(previous_camera) == len(camera) == 2 and len(set(previous_camera) & set(camera)) == 1:
            if not (enters or reveals or conceals or exits) and operation not in {"expand_group", "shrink_group", "switch_group"}:
                issues.append(_issue(
                    "unmotivated_single_occupant_swap",
                    "双人镜头只替换了一人，但没有移动/显现/入退场或完整切组动机。",
                    severity="high", anchor_id=anchor_id,
                    previous=list(previous_camera), current=list(camera), transition=transition,
                ))
        camera_intent_fields = {
            "visible_characters", "positions", "shot_transition", "shot_operation",
        }
        declared_camera_change = bool(camera_intent_fields & set(intent))
        if declared_camera_change and transition == "cut" and camera:
            shot = {
                "anchor_id": anchor_id,
                "position": position,
                "speaker": speaker,
                "visible": list(camera),
                "positions": {
                    name: int(slot) for name, slot in positions.items()
                    if name in camera and isinstance(slot, int)
                },
                "operation": operation,
            }
            history = [*camera_cut_history, shot]
            for pivot in camera:
                # A pivot chain must be uninterrupted.  A single cutaway to a
                # different subject is already a new screen direction, so it
                # intentionally clears the pattern instead of being counted.
                pivot_chain: list[dict[str, Any]] = []
                for previous_shot in reversed(history):
                    if pivot not in previous_shot["visible"]:
                        break
                    pivot_chain.append(previous_shot)
                pivot_chain.reverse()
                distinct_anchors = {
                    str(previous_shot["anchor_id"])
                    for previous_shot in pivot_chain
                }
                if len(distinct_anchors) < 3 or not all(
                    len(previous_shot["visible"]) >= 2 for previous_shot in pivot_chain
                ):
                    continue
                pivot_slots = {
                    previous_shot["positions"].get(pivot)
                    for previous_shot in pivot_chain
                    if pivot in previous_shot["positions"]
                }
                co_stars = {
                    name
                    for previous_shot in pivot_chain
                    for name in previous_shot["visible"]
                    if name != pivot
                }
                if len(pivot_slots) != 1 or len(co_stars) < 2:
                    continue
                issues.append(_issue(
                    "repeated_static_camera_pivot",
                    (
                        f"{pivot} 在连续硬切中始终停在同一槽位，"
                        "其余对话对象轮换；应改为单人正反打或完整重建新的关系组。"
                    ),
                    severity="high", anchor_id=anchor_id, pivot=pivot,
                    pivot_slot=next(iter(pivot_slots)),
                    history=[
                        {
                            "anchor_id": previous_shot["anchor_id"],
                            "position": previous_shot["position"],
                            "visible": list(previous_shot["visible"]),
                            "positions": dict(previous_shot["positions"]),
                        }
                        for previous_shot in pivot_chain
                    ],
                ))
                break
            # This catches a different mechanical failure: every dialogue
            # line hard-cuts to a pair containing the current speaker and a
            # leftover listener, so the pair is relayed one person at a time.
            # It deliberately excludes single reverse shots, held groups and
            # silent beats; none of those are evidence of speaker chasing.
            relay_chain: list[dict[str, Any]] = []
            for previous_shot in reversed(history):
                if (
                    previous_shot["position"] != "on"
                    or not previous_shot["speaker"]
                    or len(previous_shot["visible"]) < 2
                    or previous_shot["speaker"] not in previous_shot["visible"]
                ):
                    break
                relay_chain.append(previous_shot)
            relay_chain.reverse()
            relay_anchors = {
                str(previous_shot["anchor_id"])
                for previous_shot in relay_chain
            }
            relay_speakers = {
                str(previous_shot["speaker"])
                for previous_shot in relay_chain
            }
            is_relay = (
                len(relay_anchors) >= 4
                and len(relay_speakers) >= 3
                and all(
                    set(left["visible"]) != set(right["visible"])
                    and bool(set(left["visible"]) & set(right["visible"]))
                    for left, right in zip(relay_chain, relay_chain[1:])
                )
            )
            if is_relay:
                issues.append(_issue(
                    "speaker_chasing_camera_relay",
                    (
                        "连续对白硬切把当前说话者逐句塞入交叠双人组，"
                        "形成镜头随 speaker 接力的机械轮换；应选择持镜、单人正反打或新的关系组。"
                    ),
                    severity="high", anchor_id=anchor_id,
                    history=[
                        {
                            "anchor_id": previous_shot["anchor_id"],
                            "speaker": previous_shot["speaker"],
                            "visible": list(previous_shot["visible"]),
                            "positions": dict(previous_shot["positions"]),
                        }
                        for previous_shot in relay_chain
                    ],
                ))
            camera_cut_history.append(shot)
        elif (position == "on" and speaker) or value.get("beat_id"):
            # The pattern is specifically consecutive hard-cut composition.
            # A held dialogue line or a real silent beat gives the audience a
            # readable pause, so later cuts must start a fresh chain.
            camera_cut_history.clear()
        if transition == "reframe":
            added = set(camera) - set(before_camera)
            removed = set(before_camera) - set(camera)
            revealed_or_entered = {
                str(entry.get("who") or "")
                for entry in [*reveals, *enters]
                if isinstance(entry, Mapping) and str(entry.get("who") or "")
            }
            missing_reveal = sorted(added - revealed_or_entered)
            if missing_reveal:
                issues.append(_issue(
                    "reframe_adds_character_without_reveal",
                    "连续 reframe 增加画外人物时必须显式 reveal/enter；完整换镜应使用 cut。",
                    severity="high", anchor_id=anchor_id,
                    previous=list(before_camera), current=list(camera),
                    missing_reveal=missing_reveal, operation=operation,
                ))
            concealed_or_exited = {
                str(entry.get("who") or "")
                for entry in [*conceals, *exits]
                if isinstance(entry, Mapping) and str(entry.get("who") or "")
            }
            missing_conceal = sorted(removed - concealed_or_exited)
            if missing_conceal:
                issues.append(_issue(
                    "reframe_removes_character_without_conceal",
                    "连续 reframe 减少镜内人物时必须显式 conceal/exit；完整换镜应使用 cut。",
                    severity="high", anchor_id=anchor_id,
                    previous=list(before_camera), current=list(camera),
                    missing_conceal=missing_conceal, operation=operation,
                ))
        if (
            len(before_camera) > 1
            and len(camera) == 1
            and "特写" in str(value.get("fx") or "")
            and transition != "cut"
        ):
            issues.append(_issue(
                "closeup_requires_hard_cut",
                "多人镜头进入单人特写必须使用 cut 重建镜头，不能以 reframe/hold/move 软推近。",
                severity="high", anchor_id=anchor_id,
                previous=list(before_camera), current=list(camera),
                operation=operation, transition=transition,
            ))
        planned_span = planned_spans.get(anchor_id)
        explicit_cut_override = bool(
            transition == "cut"
            and operation in {
                "switch_group", "impact_insert", "anchor_match_cut",
                "replace_center_subject",
            }
            and tuple(camera) != before_camera
        )
        at_planned_start = bool(
            planned_span and anchor_id == str(planned_span.get("anchor_id") or "")
            and position == "on"
        )
        planned_silent_change = (anchor_id, position) in planned_silent_camera_changes
        if (
            planned_span and declared_camera_change
            and not at_planned_start and not planned_silent_change
            and (
                tuple(camera) != before_camera or positions != before_positions
                or transition in {"cut", "reframe"}
                or operation not in {"", "continue_group"}
            )
        ):
            issues.append(_issue(
                "unplanned_camera_change_inside_shot_span",
                (
                    "第二阶段用显式完整硬切覆盖了第一阶段的首选连续范围；保留该导演决定并进入事后对照。"
                    if explicit_cut_override else
                    "第一阶段要求保持连续镜头，但第二阶段在区间内部用非完整硬切方式改变了构图。"
                ),
                severity="warning" if explicit_cut_override else "high",
                anchor_id=anchor_id,
                event_id=str(planned_span.get("event_id") or ""),
                span_start=str(planned_span.get("anchor_id") or ""),
                hold_until_id=str(planned_span.get("hold_until_id") or ""),
                operation=operation, transition=transition,
                explicit_cut_override=explicit_cut_override,
            ))
        scale_reframe = bool(
            transition == "reframe"
            and "fx" in value
            and str(value.get("fx") or "") in {"特写", "无"}
        )
        if (
            declared_camera_change
            and tuple(camera) == before_camera
            and positions == before_positions
            and not scale_reframe
            and (transition in {"cut", "reframe"} or operation not in {"", "continue_group"})
        ):
            issues.append(_issue(
                "redundant_camera_declaration",
                "镜头名单与站位没有变化，却再次声明切镜/重构；应保持当前互动组。",
                severity="warning", anchor_id=anchor_id,
                visible=list(camera), operation=operation, transition=transition,
            ))
        for name in camera:
            if presence.get(name, "unknown") in {"unknown", "present"}:
                presence[name] = "present"
        camera = camera[:3]
        primary = speaker or str(value.get("who") or "")
        if value.get("beat_id"):
            beat_id = str(value.get("beat_id") or "")
            beat_performers = [(primary, "primary")]
            beat_performers.extend(
                (str(reaction.get("who") or ""), "reaction")
                for reaction in value.get("reactions") or []
                if isinstance(reaction, Mapping)
            )
            checked: set[str] = set()
            for performer, role in beat_performers:
                if not performer or performer in checked:
                    continue
                checked.add(performer)
                if performer not in camera:
                    issues.append(_issue(
                        "beat_performer_not_visible",
                        f"无对白 beat 的表演者 {performer} 不在当前镜头。",
                        severity="high", anchor_id=anchor_id,
                        beat_id=beat_id, who=performer, role=role,
                        visible=list(camera),
                    ))
        if primary and value.get("face"):
            face_state[primary] = str(value.get("face") or "")
            explicit_faces[(anchor_id, position, primary)] = str(value.get("face") or "")
        reactions = [
            reaction for reaction in value.get("reactions") or []
            if isinstance(reaction, Mapping)
        ]
        for reaction in reactions:
            reaction_who = str(reaction.get("who") or "")
            if reaction_who and reaction.get("face"):
                face_state[reaction_who] = str(reaction.get("face") or "")
                explicit_faces[(anchor_id, position, reaction_who)] = str(
                    reaction.get("face") or ""
                )
        camera_changed = tuple(camera) != before_camera
        observed = _execution_carriers(value, camera_changed=camera_changed)
        observed.discard("face_change")
        personal: dict[str, set[str]] = {}

        def add_personal(name: str, carrier: str) -> None:
            if name:
                personal.setdefault(name, set()).add(carrier)

        if primary:
            explicit_face = str(value.get("face") or "")
            if explicit_face and explicit_face != before_faces.get(primary, ""):
                add_personal(primary, "face_change")
            if value.get("emo"):
                add_personal(primary, "emoticon")
            if value.get("act"):
                add_personal(primary, "action")
        for reaction in reactions:
            reaction_who = str(reaction.get("who") or "")
            explicit_face = str(reaction.get("face") or "")
            if explicit_face and explicit_face != before_faces.get(reaction_who, ""):
                add_personal(reaction_who, "face_change")
            if reaction.get("emo"):
                add_personal(reaction_who, "emoticon")
            if reaction.get("act"):
                add_personal(reaction_who, "action")

        def movement_people(field: str) -> set[str]:
            payload = value.get(field)
            if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
                return {
                    str(item.get("who") or "")
                    for item in payload if isinstance(item, Mapping) and str(item.get("who") or "")
                }
            return {primary} if payload and primary else set()

        for field in ("move", "reveal", "conceal", "enter", "exit"):
            for name in movement_people(field):
                add_personal(name, "movement")
                if field in {"reveal", "conceal", "enter", "exit"}:
                    add_personal(name, "entry_exit")
        for name, subject_carriers in personal.items():
            observed.update(subject_carriers)
            carriers_by_subject.setdefault((anchor_id, position, name), set()).update(
                subject_carriers
            )
        carriers_by_anchor.setdefault((anchor_id, position), set()).update(observed)
        snapshots[(anchor_id, position)] = {
            "visible": list(camera), "positions": dict(positions),
            "presence": dict(presence), "value": value,
        }
        if planned_span and position == "on":
            expected = {
                str(value)
                for value in planned_span.get("members") or []
                if str(value)
                and isinstance(cast.get(str(value)), Mapping)
                and cast[str(value)].get("portrait")
                and not cast[str(value)].get("narrator")
            }
            actual = set(camera)
            mismatch_key = (str(planned_span.get("anchor_id") or ""), anchor_id)
            if expected and actual != expected and mismatch_key not in reported_span_mismatches:
                reported_span_mismatches.add(mismatch_key)
                issues.append(_issue(
                    "planned_shot_span_unfulfilled",
                    (
                        "执行层以显式完整硬切重新选择了镜头组；不自动改回第一阶段构图。"
                        if explicit_cut_override else
                        "执行结果没有保持第一阶段规划的完整镜头组。"
                    ),
                    severity="warning" if explicit_cut_override else "high",
                    anchor_id=anchor_id,
                    event_id=str(planned_span.get("event_id") or ""),
                    expected=sorted(expected), actual=sorted(actual),
                    span_start=str(planned_span.get("anchor_id") or ""),
                    hold_until_id=str(planned_span.get("hold_until_id") or ""),
                    explicit_cut_override=explicit_cut_override,
                ))
        participants = {primary} if primary else set()
        participants.update(
            str(reaction.get("who") or "") for reaction in reactions
            if str(reaction.get("who") or "")
        )
        participants.update(camera)
        for name in participants:
            reaction = next((
                item for item in reactions if str(item.get("who") or "") == name
            ), {})
            own_payload = value if name == primary else reaction
            performance_signatures[(anchor_id, position, name)] = (
                face_state.get(name, ""), str(own_payload.get("emo") or ""),
                str(own_payload.get("act") or ""), str(value.get("fx") or ""),
                tuple(camera), tuple(sorted(positions.items())),
            )
        previous_camera = tuple(camera)

    for item in targets:
        anchor_id = str(item.get("annotation_id") or "")
        for beat in beats_by_anchor.get((anchor_id, "before"), []):
            apply_event(beat, anchor_id, "before", speaker=str(beat.get("who") or ""))
        row = lines_by_id.get(anchor_id) or {}
        speaker = str(item.get("who") or "")
        displayable = cast.get(speaker) if isinstance(cast, Mapping) else None
        if not camera and isinstance(displayable, Mapping) and displayable.get("portrait") and not displayable.get("narrator"):
            camera = [speaker]
            presence[speaker] = "present"
        apply_event(row, anchor_id, "on", speaker=speaker)
        for beat in beats_by_anchor.get((anchor_id, "after"), []):
            apply_event(beat, anchor_id, "after", speaker=str(beat.get("who") or ""))

    peaks_by_anchor, intents_by_anchor = _planned_anchor_maps(plan)
    for anchor_id, peaks in peaks_by_anchor.items():
        if anchor_id not in target_by_id:
            continue
        for peak in peaks:
            position = str(peak.get("position") or "on")
            snapshot = snapshots.get((anchor_id, position)) or snapshots.get((anchor_id, "on")) or {}
            visible = list(snapshot.get("visible") or [])
            subject = str(peak.get("subject") or "")
            peak_type = str(peak.get("peak_type") or "")
            planned_group = _plan_group_covering_anchor(plan, anchor_id)
            expected_visible, offscreen_members = _displayable_group_contract(
                planned_group, cast,
            )
            if not expected_visible and _cast_member_is_displayable(subject, cast):
                expected_visible = [subject]
            bad = (
                peak_type == "solo_emphasis" and visible != [subject]
                or peak_type == "relationship_peak" and (
                    visible != expected_visible
                    if offscreen_members
                    else len(visible) != 2 or subject not in visible
                )
                or peak_type == "group_reaction" and (
                    visible != expected_visible
                    if offscreen_members
                    else not 2 <= len(visible) <= 3 or subject not in visible
                )
            )
            if bad:
                issues.append(_issue(
                    "solo_emphasis_not_solo_center" if peak_type == "solo_emphasis" else "peak_composition_mismatch",
                    f"{peak_type} 没有兑现计划构图。",
                    severity="high", anchor_id=anchor_id, event_id=peak.get("_event_id"),
                    subject=subject, visible=visible,
                ))
            if peak_type == "solo_emphasis":
                observed = carriers_by_anchor.get((anchor_id, position), set())
                if not observed & {"face_change", "emoticon", "action"}:
                    issues.append(_issue(
                        "solo_emphasis_performance_unfulfilled",
                        "solo_emphasis 已建立单人近景，但没有兑现 face/body/emoticon 表演变化。",
                        severity="high", anchor_id=anchor_id,
                        event_id=peak.get("_event_id"), subject=subject,
                        observed=sorted(observed),
                    ))
                if position == "on":
                    closeup_values = [lines_by_id.get(anchor_id) or {}]
                else:
                    closeup_values = beats_by_anchor.get((anchor_id, position), [])
                if not any("特写" in str(value.get("fx") or "") for value in closeup_values):
                    issues.append(_issue(
                        "solo_emphasis_closeup_unfulfilled",
                        "solo_emphasis 规划了 close 景别，但执行结果没有在峰值锚点启动角色特写。",
                        severity="high", anchor_id=anchor_id,
                        event_id=peak.get("_event_id"), subject=subject,
                    ))

    for anchor_id, intents in intents_by_anchor.items():
        if anchor_id not in target_by_id:
            continue
        for intent in intents:
            position = str(intent.get("position") or "on")
            expected = {str(value) for value in intent.get("carriers") or [] if str(value)}
            subjects = {str(value) for value in intent.get("subjects") or [] if str(value)}
            aggregate = boundary_carriers(anchor_id, position)
            personal_carriers = {"face_change", "emoticon", "action", "movement", "entry_exit"}
            observed = aggregate - personal_carriers
            if subjects:
                for subject in subjects:
                    observed.update(boundary_subject_carriers(anchor_id, position, subject))
            else:
                observed = aggregate
            require_all = bool(intent.get("require_all"))
            missing = expected - observed if require_all else (expected if not expected & observed else set())
            if missing:
                issues.append(_issue(
                    "performance_intent_unfulfilled",
                    (
                        "第一阶段声明的组合表演载体没有在对应人物的执行结果中全部出现。"
                        if require_all else
                        "第一阶段声明的可替代表演载体没有在对应人物的执行结果中出现。"
                    ),
                    severity="high", anchor_id=anchor_id,
                    event_id=str(intent.get("_event_id") or ""),
                    subjects=sorted(subjects), expected=sorted(expected),
                    observed=sorted(observed), missing=sorted(missing),
                    require_all=require_all,
                ))

    # A plan may contain several explicitly staged body/emoticon moments in
    # one chunk.  The per-intent alternative-carrier rule intentionally keeps
    # a single intent flexible, but it must not let an entire performance
    # layer collapse into face-only substitutions.  This is a diagnostic
    # signal, not an action quota: only a chunk-wide all-zero result with
    # several planned non-face intents is actionable.
    planned_non_face_intents: list[dict[str, Any]] = []
    observed_non_face_intents: list[dict[str, Any]] = []
    for anchor_id, intents in intents_by_anchor.items():
        if anchor_id not in target_by_id:
            continue
        for ordinal, intent in enumerate(intents):
            non_face = {
                str(carrier) for carrier in intent.get("carriers") or []
                if str(carrier) in {"action", "emoticon"}
            }
            if not non_face:
                continue
            entry = {
                "anchor_id": anchor_id,
                "position": str(intent.get("position") or "on"),
                "event_id": str(intent.get("_event_id") or ""),
                "ordinal": ordinal,
                "planned": sorted(non_face),
            }
            planned_non_face_intents.append(entry)
            position = str(intent.get("position") or "on")
            aggregate = boundary_carriers(anchor_id, position)
            subjects = {
                str(value) for value in intent.get("subjects") or [] if str(value)
            }
            observed = set(aggregate)
            if subjects:
                observed = set()
                for subject in subjects:
                    observed.update(boundary_subject_carriers(anchor_id, position, subject))
            actual_non_face = observed & non_face
            if actual_non_face:
                observed_non_face_intents.append({
                    **entry,
                    "observed": sorted(actual_non_face),
                })
    if len(planned_non_face_intents) >= 3 and not observed_non_face_intents:
        issues.append(_issue(
            "performance_layer_collapsed",
            (
                "本 chunk 规划了多个动作/表情符号表演意图，但执行结果全部只改变了 face；"
                "请保留少量真正有语义作用的 action 或 emoticon，不要整段塌缩为换脸。"
            ),
            severity="high",
            planned_non_face_intents=len(planned_non_face_intents),
            observed_non_face_intents=0,
            planned_anchors=[
                item["anchor_id"] for item in planned_non_face_intents
            ],
        ))

    for event in (plan or {}).get("events") or []:
        if not isinstance(event, Mapping):
            continue
        release_owner = str(event.get("release_owner") or "")
        if release_owner:
            concrete_releases = {
                (
                    str(peak.get("release_id") or ""),
                    str(peak.get("release_position") or "on"),
                )
                for peak in event.get("peaks") or []
                if isinstance(peak, Mapping)
                and str(peak.get("release_position") or "") not in {"next_event", "scene_end"}
                and str(peak.get("release_id") or "") in target_by_id
            }
            if concrete_releases and not any(
                release_owner in set(
                    (snapshots.get((anchor_id, position)) or {}).get("visible") or []
                )
                for anchor_id, position in concrete_releases
            ):
                first_release = sorted(concrete_releases)[0]
                issues.append(_issue(
                    "release_owner_not_visible",
                    f"计划把释放拍交给 {release_owner}，但该人物没有在具体释放锚点出现。",
                    severity="high", event_id=str(event.get("event_id") or ""),
                    anchor_id=first_release[0], owner=release_owner,
                    releases=sorted(concrete_releases),
                ))
        for arc in event.get("face_arcs") or []:
            if not isinstance(arc, Mapping):
                continue
            who = str(arc.get("who") or "")
            previous_stage: Mapping[str, Any] | None = None
            previous_signature: tuple[Any, ...] | None = None
            active_stage_seen = False
            for stage in arc.get("stages") or []:
                if not isinstance(stage, Mapping):
                    continue
                anchor_id = str(stage.get("anchor_id") or "")
                if anchor_id not in target_by_id:
                    if not active_stage_seen:
                        previous_stage = stage
                        previous_signature = (
                            initial_faces.get(who, ""), "", "", "",
                            initial_camera, initial_positions,
                        )
                    continue
                active_stage_seen = True
                position = str(stage.get("position") or "on")
                signature = boundary_value(
                    performance_signatures, anchor_id, position, who,
                )
                if signature is None and position != "on":
                    signature = performance_signatures.get((anchor_id, "on", who))
                semantic_changed = bool(
                    previous_stage is not None
                    and str(previous_stage.get("semantic_state") or "")
                    != str(stage.get("semantic_state") or "")
                )
                if semantic_changed:
                    explicit_face = boundary_value(
                        explicit_faces, anchor_id, position, who,
                    ) or ""
                    previous_face = (
                        str(previous_signature[0] or "") if previous_signature else ""
                    )
                    readable_changed = bool(
                        signature is not None
                        and previous_signature is not None
                        and signature != previous_signature
                    )
                    if not explicit_face and not readable_changed:
                        issues.append(_issue(
                            "face_stage_change_unfulfilled",
                            f"{who} 的表情语义阶段已变化，但执行结果既未换脸也没有其他可读表演。",
                            severity="high", anchor_id=anchor_id,
                            event_id=str(event.get("event_id") or ""), who=who,
                        ))
                    elif previous_face and explicit_face == previous_face:
                        issues.append(_issue(
                            "face_stage_reused_same_face",
                            (
                                f"{who} 保持了上一阶段同一张脸，并由其他表演载体承载变化。"
                                if readable_changed else
                                f"{who} 的表情语义阶段已变化，但仍显式选择上一张脸且没有其他可读变化。"
                            ),
                            severity="warning" if readable_changed else "high",
                            anchor_id=anchor_id,
                            event_id=str(event.get("event_id") or ""), who=who,
                            face=explicit_face,
                        ))
                if semantic_changed and signature is not None and signature == previous_signature:
                    issues.append(_issue(
                        "face_stage_no_readable_change",
                        f"{who} 的表情语义阶段已变化，但 face/气泡/动作/特效/构图均未产生可读差异。",
                        severity="high", anchor_id=anchor_id,
                        event_id=str(event.get("event_id") or ""), who=who,
                    ))
                previous_stage = stage
                if signature is not None:
                    previous_signature = signature

    authorized_heavy = {
        anchor_id for anchor_id, peaks in peaks_by_anchor.items()
        if any(str(peak.get("peak_type") or "") == "solo_emphasis" for peak in peaks)
    }
    for anchor_id, row in lines_by_id.items():
        heavy = " ".join(str(row.get(field) or "") for field in ("fx", "bgfx"))
        if _HEAVY_FX_RE.search(heavy) and anchor_id not in authorized_heavy:
            issues.append(_issue(
                "heavy_fx_unjustified", "重视觉效果没有对应的 solo_emphasis 计划授权。",
                severity="high", anchor_id=anchor_id,
            ))
        if "特写" in str(row.get("fx") or ""):
            visible = list((snapshots.get((anchor_id, "on")) or {}).get("visible") or [])
            if len(visible) != 1:
                issues.append(_issue(
                    "closeup_with_multiple_characters", "单人特写仍保留多人构图。",
                    severity="high", anchor_id=anchor_id, visible=visible,
                ))
    for beat in beats:
        heavy = " ".join(str(beat.get(field) or "") for field in ("fx", "bgfx"))
        anchor_id = str(beat.get("anchor_id") or "")
        if _HEAVY_FX_RE.search(heavy) and anchor_id not in authorized_heavy:
            issues.append(_issue(
                "heavy_fx_unjustified", "无对话框节点的重视觉效果没有 solo_emphasis 计划授权。",
                severity="high", anchor_id=anchor_id,
                beat_id=str(beat.get("beat_id") or ""),
            ))

    result = _plan_result(issues)
    return {
        "result": result,
        "needs_review": result == "fail",
        "issues": issues,
        "statistics": {
            "targets": len(targets), "beats": len(beats),
            "high_or_critical": sum(
                1 for issue in issues if issue.get("severity") in {"high", "critical"}
            ),
        },
        "final_state": {
            "visible_characters": list(camera), "positions": dict(positions),
            "scene_presence": dict(presence),
        },
    }


def validate_compiled_staging(
    scripts: Sequence[Mapping[str, Any]],
    *, plan: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Inspect the real post-rule ScriptData sequence before AAP wrapping."""
    issues: list[dict[str, Any]] = []
    def origins(script: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        return [
            origin for origin in script.get("_trace") or []
            if isinstance(origin, Mapping)
        ]

    def provenance(script: Mapping[str, Any], index: int) -> dict[str, Any]:
        traced = origins(script)
        source_ids = list(dict.fromkeys(
            str(origin.get("source_id") or "") for origin in traced
            if str(origin.get("source_id") or "")
        ))
        beat_ids = list(dict.fromkeys(
            str(origin.get("beat_id") or "") for origin in traced
            if str(origin.get("beat_id") or "")
        ))
        event_ids = list(dict.fromkeys(
            str(event_id)
            for origin in traced
            for event_id in origin.get("plan_event_ids") or []
            if str(event_id)
        ))
        return {
            "script_index": index,
            "source_id": source_ids[-1] if source_ids else "",
            "beat_id": beat_ids[-1] if beat_ids else "",
            "plan_event_ids": event_ids,
            "origins": traced,
        }

    def character_signature(script: Mapping[str, Any]) -> dict[str, tuple[Any, ...]]:
        values = (script.get("characters") or {}).get("$values") or []
        return {
            str(character.get("name")): (
                int(character.get("endingPos") or 0),
                str(character.get("faceId") or ""),
                int(character.get("shapeOverride") or 0),
                int(character.get("emoticon") if character.get("emoticon") is not None else -1),
                int(character.get("action") or 0),
            )
            for character in values
            if isinstance(character, Mapping)
            and str(character.get("name") or "")
            and int(character.get("endingPos") or 0) > 0
        }

    previous_signature: dict[str, tuple[Any, ...]] | None = None
    previous_bg = ""
    explicitly_absent: set[str] = set()
    compiled_camera_relay: list[dict[str, Any]] = []
    for index, script in enumerate(scripts):
        signature = character_signature(script)
        visible = list(signature)
        prov = provenance(script, index)
        traced = origins(script)
        # Keep compiler provenance (including deterministic no-op drops) in
        # the report, but do not count a camera command that the compiler has
        # explicitly marked as an exact duplicate as a second visual shot.
        # The marker is intentionally narrow and cannot hide an ordinary
        # authored hard cut.
        semantic_traced = [
            origin for origin in traced
            if not str(origin.get("dedup_reason") or "")
        ]
        commands = {
            str(origin.get("command") or "") for origin in semantic_traced
        }
        character_values = (script.get("characters") or {}).get("$values") or []
        speaker_slot = int(script.get("speakerSlotNum") or 0)
        speaker = (
            str(character_values[speaker_slot].get("name") or "")
            if 0 < speaker_slot < len(character_values)
            and isinstance(character_values[speaker_slot], Mapping)
            else ""
        )
        entered = {
            str(origin.get("target") or origin.get("who") or "")
            for origin in traced
            if str(origin.get("command") or "") in {"enter", "reveal"}
        }
        exited = {
            str(origin.get("target") or origin.get("who") or "")
            for origin in traced
            if str(origin.get("command") or "") == "exit"
        }
        if len(visible) > 3:
            issues.append(_issue(
                "compiled_visible_over_three", "编译后的 ScriptData 同镜超过三名角色。",
                severity="critical", visible=visible, **prov,
            ))
        shaped = [name for name, value in signature.items() if int(value[2] or 0) != 0]
        if shaped and len(visible) > 1:
            issues.append(_issue(
                "compiled_closeup_leaked_into_group",
                "角色特写状态进入了多人镜头；切镜不会自动释放特写，必须先显式清除。",
                severity="high", visible=visible, shaped=shaped, **prov,
            ))
        if (
            "camera_cut" in commands
            and bool(script.get("isDialogScript"))
            and speaker in signature
            and len(visible) >= 2
        ):
            compiled_camera_relay.append({
                "speaker": speaker,
                "visible": list(visible),
                "source_id": prov["source_id"],
                "script_index": index,
            })
            relay_speakers = {
                str(entry["speaker"]) for entry in compiled_camera_relay
            }
            is_relay = (
                len(compiled_camera_relay) >= 4
                and len(relay_speakers) >= 3
                and all(
                    set(left["visible"]) != set(right["visible"])
                    and bool(set(left["visible"]) & set(right["visible"]))
                    for left, right in zip(
                        compiled_camera_relay, compiled_camera_relay[1:],
                    )
                )
            )
            if is_relay:
                issues.append(_issue(
                    "compiled_speaker_chasing_camera_relay",
                    (
                        "最终 ScriptData 仍形成逐句追随说话者的交叠双人硬切接力；"
                        "需由 AI 返修为持镜、单人正反打或新的关系组。"
                    ),
                    severity="high", speaker=speaker,
                    history=[dict(entry) for entry in compiled_camera_relay], **prov,
                ))
        else:
            # A held shot, a single reverse shot or a no-dialogue beat breaks
            # the mechanical per-speaker relay in the real rendered timeline.
            compiled_camera_relay.clear()
        if previous_signature is not None:
            previous_visible = set(previous_signature)
            current_visible = set(signature)
            trace_commands = {
                str(origin.get("command") or "")
                for origin in traced
                if isinstance(origin, Mapping)
            }
            # A silent wait may carry a camera_hold/move restatement from the
            # planning layer even when the compiled ScriptData is byte-for-
            # byte the same shot.  Those metadata commands do not create a
            # second visual camera operation; only treat a no-op as a real
            # duplicate when it contains an authored camera change beyond the
            # wait/hold/move bookkeeping.
            no_op_wait_camera = bool(
                trace_commands
                and trace_commands <= {"wait", "nodialog", "camera_hold", "move", "layout"}
                and "camera_hold" in trace_commands
            )
            if (
                previous_signature == signature
                and commands & {"camera", "camera_cut", "camera_hold"}
                and not no_op_wait_camera
            ):
                issues.append(_issue(
                    "compiled_redundant_camera_declaration",
                    "编译后镜头人物、站位和表演完全未变，却仍重复声明镜头。",
                    severity="high", visible=visible, **prov,
                ))
            if (
                len(previous_visible) == len(current_visible) == 2
                and len(previous_visible & current_visible) == 1
            ):
                retained = next(iter(previous_visible & current_visible))
                retained_record = next((
                    character
                    for character in (script.get("characters") or {}).get("$values") or []
                    if isinstance(character, Mapping)
                    and str(character.get("name") or "") == retained
                ), {})
                changed_slot = previous_signature[retained][0] != signature[retained][0]
                visible_move = (
                    int(retained_record.get("startingPos") or signature[retained][0])
                    != int(retained_record.get("endingPos") or signature[retained][0])
                )
                explicit_transition = bool(
                    commands & {"camera_cut", "reveal", "conceal", "enter", "exit"}
                )
                if not changed_slot and not visible_move and not explicit_transition:
                    issues.append(_issue(
                        "compiled_stationary_layer_swap",
                        "编译后双人镜头在没有完整硬切或镜内过渡时只原位替换一人。",
                        severity="high", retained=retained,
                        before_signature={name: list(value) for name, value in previous_signature.items()},
                        after_signature={name: list(value) for name, value in signature.items()},
                        **prov,
                    ))

        for name in visible:
            if name in explicitly_absent and name not in entered:
                issues.append(_issue(
                    "compiled_presence_resurrection",
                    f"{name} 退场后未经过 enter/reveal 就重新出现在镜头。",
                    severity="warning", character=name, **prov,
                ))
                explicitly_absent.discard(name)
        explicitly_absent.difference_update(entered)
        explicitly_absent.update(exited)
        for name in exited:
            if name in signature:
                issues.append(_issue(
                    "compiled_exit_still_visible", f"{name} 执行 exit 后仍留在最终可见状态。",
                    severity="critical", character=name, **prov,
                ))

        background = str(script.get("bgFriendlyName") or "")
        if index and script.get("transition") and background == previous_bg:
            issues.append(_issue(
                "compiled_trans_without_bg_change", "转场存在但背景没有变化。",
                severity="warning", background=background, **prov,
            ))
        previous_bg = background
        previous_signature = signature

    return {
        "result": _plan_result(issues),
        "needs_review": _plan_result(issues) == "fail",
        "issues": issues,
        "statistics": {"scripts": len(scripts), "issues": len(issues)},
    }


_CAMERA_RE = re.compile(r"^@camera(?:_cut|_hold)?\s+(.+?)\s*$")


def _camera_group(argument: str) -> tuple[str, ...]:
    if argument.strip() in {"", "-", "auto"}:
        return tuple()
    return tuple(value for value in re.split(r"[,，、\s]+", argument.strip()) if value)


def validate_annotated_source(source: str) -> dict[str, Any]:
    """Check source-level contradictions before compiling an AAP."""
    issues: list[dict[str, Any]] = []
    lines = str(source or "").splitlines()
    previous_camera: tuple[str, ...] | None = None
    pending_camera: tuple[str, ...] | None = None
    pending_camera_command = ""
    pending_fx: set[str] = set()
    pending_focusline = False
    pending_reveal_or_move = False
    pending_move_line = 0
    pending_move_command = ""
    pending_nodialog = False
    active_closeups: set[str] = set()
    reported_closeup_leaks: set[str] = set()

    for line_number, line in enumerate(lines, 1):
        stripped = line.strip()
        camera = _CAMERA_RE.match(stripped)
        if camera:
            camera_command = stripped.split(None, 1)[0].lower()
            if pending_move_line and camera_command == "@camera_cut":
                issues.append(_issue(
                    "overwritten_move_before_camera",
                    "move 后还没有任何可见节点就硬切，移动只会变成新镜头的静态落位，不会在成片中播放。",
                    severity="high", line=line_number,
                    move_line=pending_move_line,
                    move_command=pending_move_command,
                    camera_command=camera_command,
                ))
                pending_move_line = 0
                pending_move_command = ""
                pending_reveal_or_move = False
            next_camera = _camera_group(camera.group(1))
            leaking_closeups = active_closeups - reported_closeup_leaks
            if (
                leaking_closeups
                and previous_camera is not None
                and next_camera != previous_camera
            ):
                issues.append(_issue(
                    "unreleased_closeup_before_camera_change",
                    "角色特写尚未显式释放就切换镜头；该放大状态会泄漏到后续画面。",
                    severity="high", line=line_number,
                    active_characters=sorted(leaking_closeups),
                    previous=list(previous_camera), current=list(next_camera),
                ))
                reported_closeup_leaks.update(leaking_closeups)
            if pending_camera is not None:
                issues.append(_issue(
                    "overwritten_camera_declaration",
                    "连续镜头指令之间没有画面节点，前一条不会生效；应只保留真正落地的镜头声明。",
                    severity="high", line=line_number,
                    previous_command=pending_camera_command,
                    current_command=stripped.split(None, 1)[0].lower(),
                ))
            pending_camera = _camera_group(camera.group(1))
            pending_camera_command = camera_command
            continue
        if stripped.startswith("@fx "):
            parts = stripped.split()
            if len(parts) >= 3 and parts[-1] in {"特写", "closeup"}:
                pending_fx.add(parts[1])
                active_closeups.add(parts[1])
            elif len(parts) >= 3 and parts[-1].casefold() in {"无", "none", "off"}:
                active_closeups.discard(parts[1])
                reported_closeup_leaks.discard(parts[1])
            continue
        if stripped.startswith("@bgfx 集中线"):
            pending_focusline = True
            continue
        if stripped.startswith(("@reveal ", "@conceal ", "@move ", "@enter ")):
            pending_reveal_or_move = True
            if stripped.startswith("@move "):
                pending_move_line = line_number
                pending_move_command = stripped
            continue
        if stripped == "@nodialog":
            pending_nodialog = True
            continue
        if not stripped or stripped.startswith("@") or stripped.startswith("##"):
            continue

        current_camera = pending_camera if pending_camera is not None else previous_camera or tuple()
        inline_closeups = set()
        inline_match = re.match(r"^([^(:\[]+).*<[^>]*(?:特写|closeup)[^>]*>\s*:", stripped, re.IGNORECASE)
        if inline_match:
            inline_closeups.add(inline_match.group(1).strip())
        if (pending_fx or inline_closeups) and len(current_camera) > 1:
            issues.append(_issue(
                "closeup_with_multiple_characters",
                "特写节点仍保留多人构图；强情绪特写应先切为主体单人镜头。",
                line=line_number,
                visible=list(current_camera),
            ))
        active_closeups.update(inline_closeups)
        if pending_focusline and len(current_camera) != 1:
            issues.append(_issue(
                "focusline_with_multiple_characters",
                "集中线节点不是单人镜头。",
                line=line_number,
                visible=list(current_camera),
            ))
        if previous_camera is not None and pending_camera is not None:
            if (
                previous_camera == current_camera
                and pending_camera_command in {"@camera", "@camera_cut", "@camera_hold"}
            ):
                issues.append(_issue(
                    "redundant_camera_declaration",
                    "同一人物名单重复声明 @camera；连续互动应保持当前镜头。",
                    severity="high", line=line_number, visible=list(current_camera),
                ))
            if (
                pending_camera_command != "@camera_cut"
                and len(previous_camera) == len(current_camera) == 2
                and len(set(previous_camera) & set(current_camera)) == 1
            ):
                if not pending_reveal_or_move:
                    issues.append(_issue(
                        "stationary_layer_swap",
                        "相邻双人镜头只替换一人且没有 reveal/move 过渡。",
                        line=line_number,
                        previous=list(previous_camera),
                        current=list(current_camera),
                    ))
        previous_camera = current_camera
        pending_camera = None
        pending_camera_command = ""
        pending_fx.clear()
        pending_focusline = False
        pending_reveal_or_move = False
        pending_move_line = 0
        pending_move_command = ""
        pending_nodialog = False

    return {
        "result": "pass" if not issues else "fail",
        "issues": issues,
    }


def quality_report(source: str, plan: Mapping[str, Any] | None = None) -> dict[str, Any]:
    report = {"source": validate_annotated_source(source)}
    if plan is not None:
        report["plan"] = validate_director_plan(plan)
    all_issues = [
        issue
        for section in report.values()
        if isinstance(section, Mapping)
        for issue in section.get("issues") or ()
        if isinstance(issue, Mapping)
    ]
    for section in report.values():
        if isinstance(section, dict) and isinstance(section.get("issues"), list):
            section["issues"] = classify_quality_issues(section["issues"])
    report["resolution_summary"] = quality_resolution_summary(all_issues)
    report["result"] = "pass" if all(
        section.get("result") == "pass"
        for section in report.values()
        if isinstance(section, Mapping) and "result" in section
    ) else "fail"
    return report


def main() -> int:
    import argparse
    from pathlib import Path

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Validate staged AA direction quality")
    parser.add_argument("source", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--output", type=Path, help="同时把 UTF-8 JSON 报告写入文件")
    args = parser.parse_args()
    source = args.source.read_text(encoding="utf-8-sig")
    plan = json.loads(args.plan.read_text(encoding="utf-8-sig")) if args.plan else None
    report = quality_report(source, plan)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0 if report["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
