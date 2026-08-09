from script2aap import load_cast


def test_date_itinerary_official_portraits_use_registered_identifiers(
    synthetic_cast_path,
):
    _, cast, _ = load_cast(synthetic_cast_path)

    assert {
        name: cast[name]["id"]
        for name in ("桃井", "绿", "柚子", "爱丽丝")
    } == {
        "桃井": "모모이",
        "绿": "미도리",
        "柚子": "유즈",
        "爱丽丝": "아리스N",
    }
