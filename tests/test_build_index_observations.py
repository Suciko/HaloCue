from build_index import keep_known_character_observations


def test_known_character_observations_exclude_unmapped_aap_fields():
    observations = {
        "1113": [{"id": "00"}],
        "native-id": [{"id": "03"}],
    }

    assert keep_known_character_observations(observations, [{
        "identifier": "native-id",
    }]) == {"native-id": [{"id": "03"}]}
