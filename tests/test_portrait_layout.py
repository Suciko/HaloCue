# -*- coding: utf-8 -*-
import json

import portrait_layout


def write_catalog(path, characters):
    path.write_text(
        json.dumps({"version": 1, "source": "test", "characters": characters}),
        encoding="utf-8",
    )


def test_enrichment_uses_only_conservative_consensus_fields(tmp_path):
    catalog = tmp_path / "layout.json"
    write_catalog(catalog, {
        "爱丽丝": {
            "face_direction": None,
            "framing": "closeup",
            "has_weapon": False,
            "has_wings": None,
            "hint_count": 3,
        }
    })

    enriched = portrait_layout.enrich_resource_index(
        {"characters": [{"identifier": "alice", "name": "爱丽丝"}]},
        catalog_path=str(catalog),
    )

    hint = enriched["characters"][0]["portrait_layout"]
    assert hint["framing"] == "closeup"
    assert hint["has_weapon"] is False
    assert "face_direction" not in hint
    assert "has_wings" not in hint
    assert hint["confidence"] == "coarse_name_consensus"
    assert enriched["portrait_layout_catalog"] == {"version": 1, "source": "test"}


def test_exact_existing_variant_metadata_wins_over_community_hint(tmp_path):
    catalog = tmp_path / "layout.json"
    write_catalog(catalog, {"爱丽丝": {"face_direction": "right", "hint_count": 1}})
    exact = {"face_direction": "left", "confidence": "exact_variant"}

    enriched = portrait_layout.enrich_resource_index(
        {"characters": [{
            "identifier": "alice", "name": "爱丽丝", "portrait_layout": exact,
        }]},
        catalog_path=str(catalog),
    )

    assert enriched["characters"][0]["portrait_layout"] == exact


def test_cast_profiles_are_bound_by_exact_resource_identifier():
    index = {"characters": [{
        "identifier": "alice", "portrait_layout": {"face_direction": "right"},
    }]}
    cast = {
        "爱丽丝": {"id": "alice", "portrait": True},
        "旁白": {"narrator": True},
    }

    assert portrait_layout.profiles_for_cast(index, cast) == {
        "alice": {"face_direction": "right"}
    }


def test_enrichment_keeps_visual_spacing_metadata(tmp_path):
    catalog = tmp_path / "layout.json"
    write_catalog(catalog, {
        "桃井": {
            "face_direction": "center",
            "min_slot_gap": 2,
            "visual_width": "wide",
            "hint_count": 1,
        }
    })

    enriched = portrait_layout.enrich_resource_index(
        {"characters": [{"identifier": "momoi", "name": "桃井"}]},
        catalog_path=str(catalog),
    )

    hint = enriched["characters"][0]["portrait_layout"]
    assert hint["min_slot_gap"] == 2
    assert hint["visual_width"] == "wide"
