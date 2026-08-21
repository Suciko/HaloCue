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
    """Persist communication/closeup bits until an explicit end or scene reset."""
    persistent_mask = 1 | 4
    active = {}
    for script in scripts:
        if script.pop("_sceneReset", False):
            active.clear()
        explicit_ends = set(script.pop("_explicitFxEnds", []) or [])
        for name in explicit_ends:
            active.pop(name, None)
        characters = script.get("characters", {}).get("$values", [])
        visible = {
            character.get("name"): character
            for character in characters[1:]
            if character.get("name")
        }
        # A closeup is a single-subject composition.  The runtime keeps shape
        # overrides persistent, but carrying bit 4 into a newly rebuilt group
        # shot makes the previous solo emphasis leak onto a different layout.
        # Clear only the closeup bit here; communication (bit 1) may remain
        # persistent and a later solo shot can explicitly start closeup again.
        if len(visible) > 1:
            # A rebuilt group shot must not inherit the previous solo
            # close-up from either the persistent table or the character
            # records already shaped on this ScriptData row.  Clear both
            # sources before collecting the current row's persistent bits;
            # otherwise the old bit is immediately re-added below.
            for name in list(active):
                active[name] &= ~4
                if not active[name]:
                    active.pop(name, None)
            for character in visible.values():
                character["shapeOverride"] = int(character.get("shapeOverride") or 0) & ~4
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
