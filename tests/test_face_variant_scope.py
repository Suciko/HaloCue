# -*- coding: utf-8 -*-
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pytest
from spine_face_analysis import make_variant_key
from annotate import annotation_constraints


def test_face_variant_key_isolation():
    # 精确变体隔离键必须同时结合 ident, spine_signature, outfit_key, face_id
    key1 = make_variant_key(
        ident="626652156",
        spine_signature="fe379325cea919914570515506a2a8d8be2e506e14e7e8a7dcdce99160724040",
        outfit_key="Kei_Date_Outfit",
        face_id="00",
    )
    key2 = make_variant_key(
        ident="626652156",
        spine_signature="fe379325cea919914570515506a2a8d8be2e506e14e7e8a7dcdce99160724040",
        outfit_key="Kei_Default",
        face_id="00",
    )
    # outfit_key 不同，生成的变体隔离键必须完全不同
    assert key1 != key2
    assert "Kei_Date_Outfit" in key1 or "fe379325" in key1


def test_annotation_face_evidence_is_scoped_to_exact_outfit_and_spine():
    index = {
        "bg": {}, "sounds": [], "enums": {"emoticon": {}, "action": {}},
        "characters": [{"identifier": "kai", "faces": []}],
        "face_capabilities": {"kai": [
            {
                "spine_signature": "sig-date", "outfit_key": "date",
                "faces": [{
                    "id": "07", "sources": ["vision:model-a"],
                    "visual_evidence": "visual_confirmed",
                }],
            },
            {
                "spine_signature": "sig-winter", "outfit_key": "winter",
                "faces": [{
                    "id": "07", "sources": ["aap_observed"],
                    "visual_evidence": "context_inferred",
                }],
            },
        ]},
    }
    cast = {"Kai": {
        "id": "kai", "portrait": True,
        "spine_signature": "sig-winter", "outfit_key": "winter",
    }}

    constraints = annotation_constraints(index, cast)

    assert constraints["faces_by_id"]["kai"] == {"07"}
    assert constraints["face_evidence_by_id"]["kai"] == {"07": "context_inferred"}
