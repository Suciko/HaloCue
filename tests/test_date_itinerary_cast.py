import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_date_itinerary_official_portraits_use_registered_identifiers():
    cast = json.loads(
        (ROOT / "cast-AA_本日行程_凯伊约会服_20260728.json").read_text(encoding="utf-8")
    )["cast"]

    assert {
        name: cast[name]["id"]
        for name in ("桃井", "绿", "柚子", "爱丽丝")
    } == {
        "桃井": "모모이",
        "绿": "미도리",
        "柚子": "유즈",
        "爱丽丝": "아리스N",
    }
