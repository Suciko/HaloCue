"""Portable reviewer entry: isolated data, explicit setup, localhost only."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import traceback
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ("anthropic", "cryptography", "PIL", "UnityPy", "pypdf")


def reviewer_environment(data: Path) -> dict[str, str]:
    # Do not inherit a maintainer's provider, corpus, feedback sync or AA paths.
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("HALOCUE_")
        and not key.endswith("_API_KEY")
        and key not in {"ANTHROPIC_AUTH_TOKEN", "OPENAI_BASE_URL", "ANTHROPIC_BASE_URL"}
    }
    env.update(
        {
            "HALOCUE_USER_DATA_DIR": str(data / "user"),
            "HALOCUE_LEGACY_ROOT": str(data / "legacy"),
            "HALOCUE_RESOURCE_INDEX": str(data / "resources.json"),
            "HALOCUE_NAME_BASELINE": str(data / "name-baseline.json"),
            "HALOCUE_BA_CORPUS_DIR": str(data / "no-corpus"),
            "HALOCUE_BA_WRITING_SKILL_DIR": str(ROOT / "services/halocue/writing/skill/ba-writing"),
            "PYTHONUTF8": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    return env


def write_json(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def request_stop(data: Path) -> int:
    status_file = data / "runtime.json"
    if not status_file.exists():
        print("No review instance recorded in this data directory.")
        return 0
    status = json.loads(status_file.read_text(encoding="utf-8"))
    if status.get("status") == "stopped":
        print("Review instance is already stopped.")
        return 0
    pid = status.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        raise ValueError("Invalid review runtime PID; no stop request sent")
    # A local request only; never signal or kill another process by its PID.
    (data / "stop.request").write_text(str(pid), encoding="ascii")
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        latest = json.loads(status_file.read_text(encoding="utf-8"))
        if latest.get("pid") != pid:
            print("A different review instance started; it was not stopped.")
            return 2
        if latest.get("status") == "stopped":
            print("Review instance stopped safely.")
            return 0
        time.sleep(0.25)
    print("Stop was requested but not confirmed. Check the original terminal.")
    return 2


def setup_environment(argv: list[str], data: Path) -> int:
    environment = ROOT / ".review-venv"
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    requirements = ROOT / "requirements-review.txt"
    stamp = environment / ".review-requirements"
    env = reviewer_environment(data)
    if not python.exists():
        print("Creating an isolated Python environment (first launch only)...", flush=True)
        subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True, env=env)
    declared = requirements.read_text(encoding="utf-8")
    if not stamp.exists() or stamp.read_text(encoding="utf-8") != declared:
        print("Installing review dependencies from pip; no model calls are made.", flush=True)
        subprocess.run(
            [str(python), "-m", "pip", "install", "-r", str(requirements)], check=True, env=env
        )
        stamp.write_text(declared, encoding="utf-8")
    return subprocess.call(
        [
            str(python),
            "-X",
            "utf8",
            str(Path(__file__).resolve()),
            *[arg for arg in argv if arg != "--setup"],
        ],
        cwd=ROOT,
        env=env,
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--setup", action="store_true", help="Create local venv and install requirements-review.txt"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check source/runtime dependencies without starting a server",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Print local URL without opening the system browser",
    )
    parser.add_argument(
        "--empty", action="store_true", help="Start without adding a fictional sample"
    )
    parser.add_argument(
        "--stop", action="store_true", help="Safely stop this review data directory instance"
    )
    parser.add_argument("--data-dir", type=Path, default=ROOT / ".review-data")
    parser.add_argument(
        "--port", type=int, default=0, help="Local port, default 0 chooses a free port"
    )
    args = parser.parse_args(argv)
    if not (3, 11) <= sys.version_info[:2] < (3, 14):
        print("Python 3.11, 3.12 or 3.13 is required; install one and try again.", file=sys.stderr)
        return 2
    data = args.data_dir.expanduser().resolve()
    if args.stop:
        return request_stop(data)
    if args.setup:
        return setup_environment(argv, data)
    missing = [name for name in REQUIRED if importlib.util.find_spec(name) is None]
    if missing:
        print(
            "Missing dependencies: " + ", ".join(missing) + ". Run 开始验收.cmd or add --setup.",
            file=sys.stderr,
        )
        return 2
    for name in (
        "services/halocue/integrated/src/halocue_integrated/server.py",
        "services/halocue/writing/web/knowledge-impact.js",
        "services/halocue/writing/web/card-assistance.js",
    ):
        if not (ROOT / name).is_file():
            print("Incomplete source bundle: " + name, file=sys.stderr)
            return 2
    if args.check:
        print("Review runtime dependencies and source entry: OK")
        return 0
    data.mkdir(parents=True, exist_ok=True)
    (data / "legacy").mkdir(exist_ok=True)
    (data / "no-corpus").mkdir(exist_ok=True)
    if not (data / "resources.json").exists():
        write_json(data / "resources.json", {"bg": {}, "sounds": [], "characters": []})
    env = reviewer_environment(data)
    os.environ.clear()
    os.environ.update(env)
    sys.path.insert(0, str(ROOT))
    from services.halocue.runtime_layout import enable_service_imports

    enable_service_imports()
    from halocue_integrated.server import IntegratedRuntime
    from tools.review_fixture import create_review_sample

    runtime = IntegratedRuntime(
        host="127.0.0.1",
        port=args.port,
        writing_data_dir=data / "writing",
        production_data_dir=data / "production",
        resource_index=data / "resources.json",
        legacy_root=data / "legacy",
    )
    runtime.start_upstreams()
    stop = threading.Event()
    server = threading.Thread(target=runtime.gateway.serve_forever, daemon=True)
    server.start()
    old_handlers = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        old_handlers[sig] = signal.signal(sig, lambda *_: stop.set())
    status_file = data / "runtime.json"
    try:
        seed = data / "sample.json"
        sample = json.loads(seed.read_text(encoding="utf-8")) if seed.exists() else {}
        if not seed.exists() and not args.empty and not runtime.writing_service.list_works():
            sample = create_review_sample(runtime.writing_service)
            write_json(seed, sample)
        base = f"http://127.0.0.1:{runtime.port}"
        url = base + "/?section=projects"
        capabilities = runtime.writing_service.capabilities()["capabilities"]
        required = {"card_assistance/1.0", "knowledge-change-impact/1.0"}
        if not required.issubset(capabilities):
            raise RuntimeError("The review package backend is missing the advertised features")
        write_json(
            status_file,
            {
                "url": url,
                "base_url": base,
                "pid": os.getpid(),
                "status": "running",
                "sample": sample,
                "data_dir": str(data),
                "capabilities": sorted(required),
            },
        )
        print("\nHaloCue collaborator review is ready.", flush=True)
        print("ENTRY=" + url, flush=True)
        print("DATA=" + str(data), flush=True)
        print(
            "First launch uses local simulation. Real models/AA require your own explicit setup.",
            flush=True,
        )
        print(
            "Keep this terminal open. Press Ctrl+C to stop safely. See START_REVIEW.md.\n",
            flush=True,
        )
        if not args.no_browser:
            webbrowser.open(url)
        while not stop.wait(0.25):
            request = data / "stop.request"
            if request.exists() and request.read_text(encoding="ascii").strip() == str(os.getpid()):
                request.unlink()
                break
    finally:
        runtime.close()
        server.join(timeout=5)
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
        if status_file.exists():
            status = json.loads(status_file.read_text(encoding="utf-8"))
            if status.get("pid") == os.getpid():
                status["status"] = "stopped"
                write_json(status_file, status)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception:
        log = ROOT / ".review-data" / "startup-error.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(traceback.format_exc(), encoding="utf-8")
        print("Startup failed. See " + str(log), file=sys.stderr)
        raise SystemExit(1)
