"""Android capability guards for desktop-only HaloCue operations."""

from __future__ import annotations


class AndroidCapabilityUnavailable(RuntimeError):
    """Raised when a desktop-only operation is called inside the APK."""

    def __init__(self, capability: str):
        self.capability = capability
        super().__init__(f"{capability} is unavailable on Android")


def unavailable(capability: str):
    raise AndroidCapabilityUnavailable(capability)
