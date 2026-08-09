# -*- coding: utf-8 -*-
"""自定义素材发现、验证和注册之间共享的数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AssetCandidate:
    kind: str
    source_path: Path
    stem: str
    aa_key: int | str
    sha256: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    severity: str = "error"


@dataclass(frozen=True)
class ValidationResult:
    candidate: AssetCandidate | None
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def ok(self) -> bool:
        return self.candidate is not None and not any(
            issue.severity == "error" for issue in self.issues
        )
