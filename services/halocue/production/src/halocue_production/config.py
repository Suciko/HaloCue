from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    project_root: Path
    data_dir: Path
    legacy_root: Path
    resource_index: Path | None
    aa_data: Path | None
    name_baseline: Path | None = None
    host: str = "127.0.0.1"
    port: int = 8892

    @classmethod
    def from_env(
        cls,
        *,
        host: str | None = None,
        port: int | None = None,
        data_dir: str | Path | None = None,
    ) -> "Settings":
        project_root = Path(__file__).resolve().parents[2]
        workspace_root = project_root.parent
        repository_root = project_root.parents[2]
        resolved_data = Path(
            data_dir
            or os.getenv("HALOCUE_DATA_DIR")
            or repository_root / ".halocue" / "production"
        ).expanduser().resolve()
        legacy_root = Path(
            os.getenv("HALOCUE_LEGACY_ROOT")
            or repository_root
        ).expanduser().resolve()
        resource_value = os.getenv("HALOCUE_RESOURCE_INDEX")
        default_index = legacy_root / "aa_resources.json"
        resource_index = Path(resource_value).expanduser().resolve() if resource_value else default_index
        aa_value = os.getenv("HALOCUE_AA_DATA")
        baseline_value = os.getenv("HALOCUE_NAME_BASELINE")
        default_baseline = repository_root / ".halocue" / "production" / "reference" / "character-name-baseline.json"
        name_baseline = (
            Path(baseline_value).expanduser().resolve()
            if baseline_value
            else default_baseline
        )
        return cls(
            project_root=project_root,
            data_dir=resolved_data,
            legacy_root=legacy_root,
            resource_index=resource_index if resource_index.is_file() else None,
            aa_data=Path(aa_value).expanduser().resolve() if aa_value else None,
            name_baseline=name_baseline if name_baseline.is_file() else None,
            host=host or os.getenv("HALOCUE_HOST") or "127.0.0.1",
            port=int(port or os.getenv("HALOCUE_PORT") or 8892),
        )

    def prepare(self) -> None:
        for child in ("runs", "drafts", "releases", "jobs", "uploads"):
            (self.data_dir / child).mkdir(parents=True, exist_ok=True)
