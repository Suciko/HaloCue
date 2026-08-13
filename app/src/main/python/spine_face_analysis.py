"""Import-compatible Android replacement for desktop Spine face analysis."""

from android_runtime_guard import unavailable


def make_variant_key(ident: str, spine_signature: str, outfit_key: str, face_id: str) -> str:
    return f"{ident}:{spine_signature[:16]}:{outfit_key}:{face_id}"


def resolve_spine_cli(*args, **kwargs):
    return None


def analyze_character_faces(*args, **kwargs):
    unavailable("spine_rendering")
