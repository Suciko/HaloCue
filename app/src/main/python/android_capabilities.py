from __future__ import annotations

import importlib
from typing import Final


_CAPABILITIES: Final = {
    "pillow": {
        "module": "PIL.Image", "attribute": "open", "label": "Pillow", "required": True,
    },
    "anthropic": {
        "module": "anthropic", "attribute": "Anthropic", "label": "Anthropic SDK", "required": False,
    },
    "opencc": {
        "module": "opencc", "attribute": "OpenCC", "label": "OpenCC", "required": False,
    },
    "unitypy": {
        "module": "UnityPy", "attribute": "load", "label": "UnityPy", "required": False,
    },
}


def capability_report() -> dict[str, dict[str, object]]:
    report: dict[str, dict[str, object]] = {}
    for name, definition in _CAPABILITIES.items():
        try:
            module = importlib.import_module(str(definition["module"]))
            getattr(module, str(definition["attribute"]))
        except Exception as error:
            reason = (
                f"{definition['label']} 不可用: "
                f"{error.__class__.__name__}: {error}"
            )
            available = False
        else:
            reason = ""
            available = True
        report[name] = {
            "available": available,
            "required": bool(definition["required"]),
            "reason": reason,
        }
    return report
