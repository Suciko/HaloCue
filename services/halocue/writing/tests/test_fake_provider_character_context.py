import pytest

from halocue_writing.errors import DomainError
from halocue_writing.providers import FakeWritingProvider


def test_fake_blueprint_uses_confirmed_work_character_cards():
    proposal = FakeWritingProvider().generate_blueprint(
        {"idea": "露奈在雨后的走廊调查线索", "characters": []},
        {"character_cards": [
            {"id": "pending", "name": "爱丽丝", "trust_status": "open"},
            {"id": "confirmed", "name": "露奈", "trust_status": "confirmed"},
        ]},
    )
    assert proposal["characters"] == ["露奈"]
    assert proposal["recommendations"]["character_card_ids"] == ["confirmed"]
    assert "露奈" in proposal["central_conflict"]


def test_fake_blueprint_waits_for_a_named_unconfirmed_work_character():
    with pytest.raises(DomainError) as failure:
        FakeWritingProvider().generate_blueprint(
            {"idea": "露奈在雨后的走廊调查线索", "characters": []},
            {"character_cards": [
                {"id": "pending", "name": "露奈", "trust_status": "open"},
            ]},
        )
    assert failure.value.code == "character_card_unconfirmed"
