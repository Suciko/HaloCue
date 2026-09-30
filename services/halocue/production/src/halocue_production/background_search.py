"""Local multilingual background search; no model calls or remote indexing."""

import re
import unicodedata

from .background_names import _TOKEN_NAMES_ZH


_ALIASES = {
    "火车站": "车站",
    "阿比多斯": "阿拜多斯",
    "阿拜多斯学院": "阿拜多斯",
    "阿拜多斯学园": "阿拜多斯",
    "夜间": "夜晚",
    "晚上": "夜晚",
    "深夜": "夜晚",
    "傍晚": "黄昏",
    "夕阳": "黄昏",
    "日间": "白天",
    "楼顶": "天台",
    "屋顶": "天台",
    "月台": "车站",
    "站台": "车站",
    "寝室": "宿舍",
}


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value)).casefold()
    for alias, canonical in _ALIASES.items():
        value = value.replace(alias, canonical)
    return re.sub(r"[\W_]+", "", value)


def background_search_document(row: dict) -> tuple[str, str]:
    values = []
    for key, value in row.items():
        # Negative suitability notes describe what the image does NOT contain.
        # Searching them made daytime stations match "station night".
        if key.startswith("_") or key in {"aa_hash", "asset_id", "avoid_when"}:
            continue
        if isinstance(value, (list, tuple)):
            values.extend(str(item) for item in value)
        elif isinstance(value, str):
            values.append(value)
    compact_key = normalize(str(row.get("key") or ""))
    # Lowercase AA identities also exist; they no longer retain CamelCase word
    # boundaries, so known place/time tokens contribute searchable aliases.
    values.extend(zh for en, zh in _TOKEN_NAMES_ZH.items() if en in compact_key)
    return normalize(str(row.get("name") or "")), normalize(" ".join(values))


def background_search_score(document: tuple[str, str], query: str) -> int | None:
    terms = [normalize(term) for term in re.split(r"[\s,，]+", query.strip())]
    terms = [term for term in terms if term]
    if not terms:
        return 0
    name, corpus = document
    if not all(term in corpus for term in terms):
        return None
    joined = "".join(terms)
    if name == joined:
        return 100
    if name.startswith(joined):
        return 80
    return 60 if all(term in name for term in terms) else 20
