from stage import Stage


def test_default_layout_keeps_five_visible_slots_and_outer_two_person_shot():
    stage = Stage()

    assert stage.plan(["solo"]) == {"solo": 3}
    assert stage.plan(["left", "right"]) == {"left": 1, "right": 5}
    assert stage.plan(["a", "b", "c"]) == {"a": 1, "b": 3, "c": 5}


def test_explicit_manual_positions_can_still_use_inner_slots():
    stage = Stage()
    stage.pin("left", 2)
    stage.pin("right", 4)

    assert stage.plan(["left", "right"]) == {"left": 2, "right": 4}
