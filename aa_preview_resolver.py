# -*- coding: utf-8 -*-
"""Resolve AA logical resource keys to a user's local preview index.

The index contains derived thumbnails only.  It is deliberately kept outside
the repository so the public project stores contracts and logical keys, not
AA game resources or decompiled files.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

from official_preview_index import OfficialPreviewIndex


AssetKind = Literal["background", "avatar"]


@dataclass(frozen=True)
class ResolvedPreview:
    kind: AssetKind
    key: str
    path: Path


def avatar_key_from_spine(spine: str | None) -> str:
    """Map AA's ``CharacterSpine_<id>`` name to its official avatar key."""

    stem = Path(str(spine or "").replace("\\", "/")).name
    prefix = "CharacterSpine_"
    if not stem.casefold().startswith(prefix.casefold()):
        return ""
    suffix = stem[len(prefix) :]
    return f"Student_Portrait_{suffix}" if suffix else ""


class AAPreviewResolver:
    """Safe lookup facade over a locally generated ``OfficialPreviewIndex``."""

    def __init__(self, index_root: str | Path):
        self.index = OfficialPreviewIndex(index_root)

    def resolve(self, kind: AssetKind, key: str | None) -> ResolvedPreview | None:
        normalized = str(key or "").strip()
        if not normalized:
            return None
        path = self.index.resolve(kind, normalized)
        return ResolvedPreview(kind, normalized, path) if path else None

    def resolve_avatar(
        self,
        *,
        avatar_key: str | None = None,
        spine_key: str | None = None,
    ) -> ResolvedPreview | None:
        return self.resolve("avatar", avatar_key) or self.resolve(
            "avatar", avatar_key_from_spine(spine_key)
        )


def apply_local_preview_uris(
    descriptor: dict[str, Any],
    resolver: AAPreviewResolver,
    *,
    uri_for: Callable[[AssetKind, str], str],
) -> dict[str, Any]:
    """Return a descriptor copy with host-provided local preview URIs.

    ``uri_for`` is supplied by the local app server (for example an allowlisted
    ``/api/resources/preview`` route).  The resolver itself never exposes a
    filesystem path to browser code.
    """

    import copy

    result = copy.deepcopy(descriptor)
    background = result.get("background")
    if isinstance(background, dict):
        key = background.get("aa_key") or background.get("logical_key")
        preview = resolver.resolve("background", key)
        if preview:
            background["preview_uri"] = uri_for(preview.kind, preview.key)
            background["preview_source"] = "aa-local-index"

    for actor in result.get("actors", []):
        if not isinstance(actor, dict):
            continue
        preview = resolver.resolve_avatar(
            avatar_key=actor.get("avatar_key"),
            spine_key=actor.get("spine_key"),
        )
        if preview:
            actor["preview_uri"] = uri_for(preview.kind, preview.key)
            actor["preview_source"] = "aa-local-index"
    return result
