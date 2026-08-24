from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .errors import ProductionError


class SettingsStore:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "settings.json"

    def load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProductionError(
                "settings_corrupted", "1.0 设置文件损坏", status=500
            ) from exc
        return value if isinstance(value, dict) else {}

    def save(self, value: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temporary, self.path)

    @staticmethod
    def validate_aa_workspace(value: object) -> Path:
        raw = str(value or "").strip()
        if not raw:
            raise ProductionError("aa_workspace_required", "AA 工作区不能为空")
        path = Path(raw).expanduser().resolve()
        if not path.is_dir():
            raise ProductionError("aa_workspace_not_found", "AA 工作区不存在")
        missing = [name for name in ("projects", "saves", "overrides", "settings") if not (path / name).is_dir()]
        if missing:
            raise ProductionError(
                "invalid_aa_workspace",
                "所选目录不是有效的 AA data 工作区",
                details={"missing": missing},
            )
        return path

