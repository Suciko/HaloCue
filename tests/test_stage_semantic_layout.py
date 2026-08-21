# -*- coding: utf-8 -*-
from stage import Stage


def test_semantic_pair_distances_are_goals_not_one_fixed_pair():
    assert Stage().plan(["a", "b"], intent={"relation_distance": "normal"}) == {
        "a": 1, "b": 5,
    }
    distant = Stage().plan(["a", "b"], intent={"relation_distance": "distant"})
    remote = Stage().plan(["a", "b"], intent={"relation_distance": "remote"})
    close = Stage().plan(["a", "b"], intent={"relation_distance": "approaching"})

    assert abs(distant["a"] - distant["b"]) == 4
    assert set(remote.values()) == {1, 5}
    assert abs(close["a"] - close["b"]) == 2


def test_portrait_direction_can_override_default_left_right_order():
    stage = Stage(profiles={
        "a": {"face_direction": "left"},
        "b": {"face_direction": "right"},
    })

    target = stage.plan(["a", "b"], intent={"relation_distance": "normal"})

    assert target == {"a": 5, "b": 1}


def test_semantic_layout_keeps_continuity_until_intent_changes():
    stage = Stage()
    normal = stage.plan(["a", "b"], intent={"relation_distance": "normal"})
    stage.apply(normal)

    assert stage.plan(["a", "b"], intent={"relation_distance": "normal"}) == normal
    distant = stage.plan(["a", "b"], intent={"relation_distance": "distant"})
    assert abs(distant["a"] - distant["b"]) == 4


def test_semantic_layout_preserves_entering_slot_collision_invariant():
    stage = Stage()
    stage.pos = {"a": 2}

    target = stage.plan(
        ["a", "b"], entering={"b"}, intent={"relation_distance": "distant"}
    )

    assert target["b"] != 2
    starts = [stage.pos.get(ident, target[ident]) for ident in target]
    assert len(starts) == len(set(starts))


def test_relation_distance_never_changes_single_or_three_person_standard_layouts():
    stage = Stage()

    assert stage.plan(["a"], intent={"relation_distance": "distant"}) == {"a": 3}
    assert stage.plan(
        ["a", "b", "c"],
        intent={
            "relation_distance": "intimate",
            "focus_character": "a",
            "reaction_target": "b",
        },
    ) == {"a": 1, "b": 3, "c": 5}


def test_stale_offscreen_relationship_does_not_affect_the_visible_pair():
    stage = Stage()

    target = stage.plan(
        ["a", "b"],
        intent={
            "relation_distance": "intimate",
            "focus_character": "a",
            "reaction_target": "offscreen",
        },
    )

    assert target == {"a": 1, "b": 5}


def test_wide_portraits_never_use_adjacent_slots_even_for_close_intent():
    stage = Stage(profiles={
        "momoi": {"min_slot_gap": 2},
        "midori": {"min_slot_gap": 2},
    })

    target = stage.plan(
        ["momoi", "midori"],
        intent={"relation_distance": "approaching"},
    )

    assert abs(target["momoi"] - target["midori"]) >= 2


def test_wide_portrait_entry_is_safe_before_and_after_existing_actor_moves():
    profiles = {
        "momoi": {"min_slot_gap": 2},
        "midori": {"min_slot_gap": 2},
    }
    stage = Stage(profiles=profiles)
    stage.pos = {"momoi": 3}

    target = stage.plan(
        ["momoi", "midori"],
        entering={"midori"},
    )
    starts = {
        ident: target[ident] if ident == "midori" else stage.pos[ident]
        for ident in target
    }

    assert abs(starts["momoi"] - starts["midori"]) >= 2
    assert abs(target["momoi"] - target["midori"]) >= 2


def test_third_actor_enters_without_crossing_wide_portrait_footprints():
    profiles = {
        "momoi": {"min_slot_gap": 2},
        "midori": {"min_slot_gap": 2},
    }
    stage = Stage(profiles=profiles)
    stage.pos = {"momoi": 3, "midori": 5}

    target = stage.plan(
        ["momoi", "midori", "aris"],
        entering={"aris"},
        intent={
            "relation_distance": "intimate",
            "focus_character": "momoi",
            "reaction_target": "midori",
        },
    )
    starts = {
        ident: target[ident] if ident == "aris" else stage.pos[ident]
        for ident in target
    }

    assert set(target.values()) == {1, 3, 5}
    assert stage._portrait_spacing_is_safe(list(target), starts)
    assert stage._portrait_spacing_is_safe(list(target), target)


def test_camera_composition_fit_uses_portrait_geometry_as_a_hard_constraint():
    fitting = Stage(profiles={
        "momoi": {"min_slot_gap": 2},
        "midori": {"min_slot_gap": 2},
    })
    impossible = Stage(profiles={
        "a": {"min_slot_gap": 3},
        "b": {"min_slot_gap": 3},
        "c": {"min_slot_gap": 3},
    })

    assert fitting.can_fit_composition(["momoi", "midori", "aris"])
    assert not impossible.can_fit_composition(["a", "b", "c"])


def test_wide_pair_allows_either_authored_left_right_order():
    profiles = {
        "momoi": {"min_slot_gap": 2},
        "midori": {"min_slot_gap": 2},
    }

    first = Stage(profiles=profiles).plan(
        ["momoi", "midori"], intent={"relation_distance": "normal"}
    )
    reversed_pair = Stage(profiles=profiles).plan(
        ["midori", "momoi"], intent={"relation_distance": "normal"}
    )

    assert first["momoi"] < first["midori"]
    assert reversed_pair["midori"] < reversed_pair["momoi"]
