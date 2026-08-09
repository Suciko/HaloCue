import pytest

from build_index import ACTION, ACTION_CN, APPEAR_CN, EMOTICON, SHAPE
from script2aap import resolve_act, resolve_emo, resolve_shape
from stage import APPEAR
from tables import resolve_bgeffect


def _lookup_tables():
    emo_sym = {value: key for key, value in EMOTICON.items()}
    act = {value: key for key, value in ACTION.items() if value}
    return emo_sym, act


def test_chat_is_the_confirmed_emoticon_and_jump_is_action_six():
    emo_sym, act = _lookup_tables()

    assert resolve_emo(EMOTICON[1], emo_sym, {}, 12) == 1
    assert resolve_act("jump", act, {}, 12) == 6
    assert EMOTICON[1] == "[재잘]"
    assert ACTION[6] == "jump"


@pytest.mark.parametrize(
    ("resolver", "token", "args", "line"),
    [
        (resolve_emo, "20", ({}, {}), 31),
        (resolve_act, "8", ({}, {}), 32),
        (resolve_act, "-1", ({}, {}), 33),
        (resolve_shape, "8", (), 34),
        (resolve_shape, "-1", (), 35),
    ],
)
def test_unknown_numeric_enum_is_rejected_with_its_line_number(resolver, token, args, line):
    with pytest.raises(ValueError, match=rf"line {line}"):
        resolver(token, *args, line)


@pytest.mark.parametrize("value", range(8))
def test_confirmed_shape_ids_remain_available(value):
    assert resolve_shape(str(value), 41) == value


def test_shape_dataset_supports_all_user_confirmed_bit_combinations():
    assert set(SHAPE) == set(range(8))


def test_shape_names_combine_as_bit_flags():
    assert resolve_shape("通讯+特写", 42) == 5
    assert resolve_shape("黑屏剪影+特写", 42) == 6
    assert resolve_shape("通讯+黑屏剪影+特写", 42) == 7


def test_calibrated_action_and_entrance_labels_match_aa_preview():
    assert ACTION_CN[4] == "小颤抖"
    assert ACTION_CN[5] == "大颤抖"
    assert APPEAR_CN[1] == "从右入场"
    assert APPEAR_CN[2] == "从左入场"
    assert APPEAR["右"] == 1
    assert APPEAR["左"] == 2


def test_mist_background_effect_is_labeled_as_smoke_like():
    value, error = resolve_bgeffect("烟雾")

    assert error is None
    assert value
