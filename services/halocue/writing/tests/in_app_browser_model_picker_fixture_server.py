"""Disposable inline model-picker QA: loopback provider, no external model calls."""
import json
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from halocue_writing.app import make_handler
from halocue_writing.service import WritingService

class Provider(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def send(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.send({"data": [{"id": name} for name in ["test-writer-a", "test-writer-b", "test-unavailable", "test-long-model-name-for-layout-check-0123456789"]]})

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        if payload.get("model") == "test-unavailable":
            self.send({"error": {"message": "Model unavailable"}}, 404)
        else:
            self.send({"choices": [{"message": {"content": "pong"}, "finish_reason": "stop"}]})

if __name__ == "__main__":
    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    threading.Thread(target=provider.serve_forever, daemon=True).start()
    with tempfile.TemporaryDirectory(prefix="halocue-model-picker-", ignore_cleanup_errors=True) as directory:
        service = WritingService(Path(directory))
        service.start()
        work = service.create_work({"title": "模型选择验收", "idea": "两位学生整理录音。"})
        service.activate_writing_model({"provider": "openai", "base_url": f"http://127.0.0.1:{provider.server_port}/v1", "model": "test-writer-a", "timeout": 5})
        service.activate_writing_model({"provider": "openai", "base_url": f"http://127.0.0.1:{provider.server_port}/v1", "model": "test-writer-b", "timeout": 5})
        server = ThreadingHTTPServer(("127.0.0.1", 8932), make_handler(service, ROOT / "web"))
        print(json.dumps({"url": f"http://127.0.0.1:8932/?section=works&work_id={work['id']}", "data_dir": directory}), flush=True)
        try:
            server.serve_forever()
        finally:
            server.server_close()
            provider.shutdown()
            service.close()
