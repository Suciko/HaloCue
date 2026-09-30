"""Disposable integrated service for card assistance acceptance (synthetic only)."""

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
from services.halocue.writing.tests.test_card_assistance import (  # noqa: E402
    CardAssistanceProvider,
    make_card_work,
)

if __name__ == "__main__":
    data = Path(tempfile.mkdtemp(prefix="halocue-iab-card-assistance-"))
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
    runtime.writing_service.provider = CardAssistanceProvider()
    fixtures = []
    for kind in ("character_card", "world_card"):
        work, context = make_card_work(runtime.writing_service, kind)
        fixtures.append({"work_id": work["id"], "context": context})
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
