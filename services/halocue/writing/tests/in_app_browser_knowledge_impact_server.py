"""Disposable integrated service for knowledge impact acceptance (synthetic only)."""

import json
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
for name in ("writing", "production", "integrated"):
    sys.path.insert(0, str(ROOT / "services" / "halocue" / name / "src"))

from halocue_integrated.server import IntegratedRuntime  # noqa: E402
from services.halocue.writing.tests.test_knowledge_change_impact import (  # noqa: E402
    edit_card,
    edit_world,
    make_impact_work,
)

if __name__ == "__main__":
    data = Path(tempfile.mkdtemp(prefix="halocue-iab-knowledge-impact-"))
    index = data / "resources.json"
    index.write_text('{"bg": {}, "sounds": [], "characters": []}', encoding="utf8")
    runtime = IntegratedRuntime(
        host="127.0.0.1",
        port=0,
        writing_data_dir=data / "writing",
        production_data_dir=data / "production",
        resource_index=index,
        legacy_root=data,
    )
    work, ids = make_impact_work(runtime.writing_service)
    edit_card(
        runtime.writing_service, work["id"], ids["cards"][0], knowledge_boundary="不知道夜间口令"
    )
    edit_world(runtime.writing_service, work["id"], "world-archive", summary="夜间需要双人核验")
    fixtures = [{"work_id": work["id"], **ids}]
    runtime.start_upstreams()
    threading.Thread(target=runtime.gateway.serve_forever, daemon=True).start()
    print(
        json.dumps(
            {
                "base_url": f"http://127.0.0.1:{runtime.gateway.server_port}",
                "data_dir": str(data),
                "fixtures": fixtures,
                "provider": "synthetic / no paid requests",
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        runtime.close()
