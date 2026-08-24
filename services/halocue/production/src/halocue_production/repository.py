from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

from .errors import ProductionError
from .models import ProductionRun, ScriptRelease


class ProductionRepository:
    _RUN_ID = re.compile(r"run-[0-9a-f]{12}")

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.runs_dir = data_dir / "runs"
        self.releases_dir = data_dir / "releases"
        self._lock = threading.RLock()

    @staticmethod
    def _atomic_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temporary, path)

    def save_release(self, release: ScriptRelease, text: str) -> None:
        release_dir = self.releases_dir / release.release_id
        with self._lock:
            release_dir.mkdir(parents=True, exist_ok=False)
            (release_dir / "source.txt").write_text(text, encoding="utf-8")
            self._atomic_json(release_dir / "release.json", release.to_dict())

    def save_run(self, run: ProductionRun) -> None:
        with self._lock:
            self._atomic_json(self.runs_dir / f"{run.run_id}.json", run.to_dict())

    def get_run(self, run_id: str) -> ProductionRun:
        if not self._RUN_ID.fullmatch(str(run_id)):
            raise ProductionError("invalid_run_id", "制作任务 ID 无效", status=400)
        path = self.runs_dir / f"{run_id}.json"
        if not path.is_file():
            raise ProductionError("run_not_found", "制作任务不存在", status=404)
        try:
            return ProductionRun.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError) as exc:
            raise ProductionError(
                "run_corrupted", "制作任务状态损坏", status=500
            ) from exc

    def list_runs(self) -> list[ProductionRun]:
        rows = []
        for path in self.runs_dir.glob("run-*.json"):
            try:
                rows.append(
                    ProductionRun.from_dict(json.loads(path.read_text(encoding="utf-8")))
                )
            except (OSError, ValueError, TypeError):
                continue
        return sorted(rows, key=lambda item: item.updated_at, reverse=True)
