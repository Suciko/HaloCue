# -*- coding: utf-8 -*-
"""Final deterministic guards for performance combinations."""

import tables


def enforce_focusline_shots(scripts):
    """Keep FocusLine only on an existing solo closeup in the center slot."""
    focusline = tables.BGEFFECT["BG_FocusLine"]
    for script in scripts:
        if script.get("bgEffect") != focusline:
            continue
        characters = script.get("characters", {}).get("$values", [])
        visible = [
            character for character in characters[1:]
            if character.get("name")
        ]
        center = characters[3] if len(characters) > 3 else None
        if (
            len(visible) != 1
            or visible[0] is not center
            or not (int(center.get("shapeOverride") or 0) & 4)
        ):
            script["bgEffect"] = 0
    return scripts


def enforce_persistent_closeups(scripts):
    """Persist communication/closeup bits until a named end or shot exit."""
    persistent_mask = 1 | 4
    active = {}
    for script in scripts:
        explicit_ends = set(script.pop("_explicitFxEnds", []) or [])
        for name in explicit_ends:
            active.pop(name, None)
        characters = script.get("characters", {}).get("$values", [])
        visible = {
            character.get("name"): character
            for character in characters[1:]
            if character.get("name")
        }
        for name in list(active):
            if name not in visible:
                active.pop(name, None)
        for name, character in visible.items():
            if name in explicit_ends:
                continue
            bits = int(character.get("shapeOverride") or 0) & persistent_mask
            if bits:
                active[name] = bits
        for name, bits in active.items():
            if name in visible:
                character = visible[name]
                character["shapeOverride"] = int(character.get("shapeOverride") or 0) | bits
    return scripts
