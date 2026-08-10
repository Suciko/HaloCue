"""Import-compatible Android replacement for the Windows Spine renderer."""

from dataclasses import dataclass
from pathlib import Path

from android_runtime_guard import unavailable


@dataclass(frozen=True)
class RenderedFace:
    face_id: str
    portrait_path: Path
    head_path: Path


def render_face_variations(*args, **kwargs):
    unavailable("spine_rendering")
