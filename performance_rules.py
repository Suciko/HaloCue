# -*- coding: utf-8 -*-
"""Final deterministic guards for performance combinations."""

import tables


def enforce_focusline_shots(scripts):
    """FocusLine is legal only for one visible portrait and always implies closeup."""
    focusline = tables.BGEFFECT["BG_FocusLine"]
    for script in scripts:
        if script.get("bgEffect") != focusline:
            continue
        characters = script.get("characters", {}).get("$values", [])
        visible = [
            character for character in characters[1:]
            if character.get("name")
        ]
        speaker_slot = int(script.get("speakerSlotNum") or 0)
        speaker = (
            characters[speaker_slot]
            if 0 < speaker_slot < len(characters)
            and characters[speaker_slot].get("name")
            else None
        )
        focal = speaker or (visible[0] if len(visible) == 1 else None)
        if focal is None:
            script["bgEffect"] = 0
            continue
        for character in visible:
            if character is not focal:
                character["name"] = ""
        focal["shapeOverride"] = int(focal.get("shapeOverride") or 0) | 4
        highlights = script.get("highlightedSlotNums", {}).get("$values")
        if isinstance(highlights, list):
            highlights[:] = [
                slot for slot in highlights
                if slot == speaker_slot and characters[slot].get("name")
            ]
    return scripts


def enforce_persistent_closeups(scripts):
    """Keep camera-distance closeup active until its character leaves the shot."""
    active_name = None
    for script in scripts:
        characters = script.get("characters", {}).get("$values", [])
        visible = {
            character.get("name"): character
            for character in characters[1:]
            if character.get("name")
        }
        explicit = [
            character
            for character in visible.values()
            if int(character.get("shapeOverride") or 0) & 4
        ]
        if explicit:
            speaker_slot = int(script.get("speakerSlotNum") or 0)
            speaker = (
                characters[speaker_slot]
                if 0 < speaker_slot < len(characters)
                and characters[speaker_slot].get("name")
                else None
            )
            focal = speaker if speaker in explicit else explicit[0]
            active_name = focal.get("name")
        elif active_name not in visible:
            active_name = None
        if active_name in visible:
            focal = visible[active_name]
            focal["shapeOverride"] = int(focal.get("shapeOverride") or 0) | 4
    return scripts
