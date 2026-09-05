"""Validated production-direction presets shared by legacy and service callers."""

from typing import Literal


DirectionProfile = Literal["standard", "conservative"]
PROFILE_VERSION = "1.0"


class DirectionProfileChanged(ValueError):
    code = "direction_profile_changed"

    def __init__(self) -> None:
        super().__init__("Direction rules changed; start a new generation")


class InvalidDirectionProfile(ValueError):
    code = "invalid_direction_profile"

    def __init__(self) -> None:
        super().__init__("Direction profile must be standard or conservative")


def normalize_direction_profile(value: object = None) -> DirectionProfile:
    """Keep omitted legacy settings standard; reject malformed explicit values."""
    if value is None:
        return "standard"
    if isinstance(value, str):
        if value == "standard":
            return "standard"
        if value == "conservative":
            return "conservative"
    raise InvalidDirectionProfile()
