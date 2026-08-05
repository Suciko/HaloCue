from direction_rules import infer_direction_cues, supplement_directions


def test_requested_examples_receive_balanced_direction_cues():
    assert infer_direction_cues(
        "全身上下就嘴巴最灵光……走了！再不出发，才真的要偏离计划了。所有人都跟上。"
    )["emo"] == "冒烟"
    assert infer_direction_cues(
        "……你为什么要把「普通」说得那么不普通。"
    )["emo"] == "沉默"
    assert infer_direction_cues("……！")["emo"] == "惊叹"
    assert infer_direction_cues("那就更不行了！！")["act"] == "jump"


def test_punctuation_alone_does_not_over_direct_ordinary_dialogue():
    assert infer_direction_cues("好的！") == {}
    assert infer_direction_cues("那么……我们继续说明下一项。") == {}
    assert infer_direction_cues("现在出发！") == {}
    assert infer_direction_cues("今天的折扣很大！！") == {}


def test_supplement_only_fills_empty_portrait_fields():
    items = [
        {"kind": "line", "who": "凯伊", "text": "……！", "emo": None},
        {"kind": "line", "who": "老师", "text": "……！", "emo": None},
        {
            "kind": "line",
            "who": "凯伊",
            "text": "那就更不行了！！",
            "act": "stiff",
        },
    ]
    cast = {
        "凯伊": {"portrait": True, "narrator": False},
        "老师": {"portrait": False, "narrator": False},
    }

    changes = supplement_directions(items, cast)

    assert items[0]["emo"] == "惊叹"
    assert not items[1].get("emo")
    assert items[2]["act"] == "stiff"
    assert changes == [
        {
            "item_index": 0,
            "field": "emo",
            "before": None,
            "after": "惊叹",
            "rule": "punctuation_only_exclaim",
        }
    ]
    assert items[0]["_direction_origins"] == {
        "emo": "deterministic_supplement"
    }
