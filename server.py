"""A loopback-only HTTP service for local, synthetic GET experiments."""

import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from pathlib import Path
import time
from urllib.parse import urlsplit
import uuid


DEFAULT_CONFIG = Path(__file__).resolve().parent / "config" / "service.json"


def make_handler(access_log, config_path=DEFAULT_CONFIG):
    class LabHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            started_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
            started = time.perf_counter()
            request_id = str(uuid.uuid4())
            path = urlsplit(self.path).path

            if path == "/":
                status, message = 200, "local lab is running"
            elif path == "/error":
                # Intentional response, not an unexpected Python exception.
                status, message = 500, "simulated internal error"
            elif path == "/slow":
                time.sleep(0.5)
                status, message = 200, "simulated slow response"
            elif path == "/report":
                # A configuration flag stands in for a dependency in this local lab.
                # Reload per request so correcting the file can be verified immediately.
                try:
                    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
                    ready = isinstance(config, dict) and config.get("dependency_ready") is True
                except (OSError, ValueError):
                    ready = False
                if ready:
                    status, message = 200, "simulated report is available"
                else:
                    status, message = 500, "simulated report dependency is unavailable; check configuration"
            else:
                status, message = 404, "path not found"

            body = json.dumps({"message": message, "request_id": request_id}).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()

            access_log.info(json.dumps({
                "timestamp": started_at,
                "request_id": request_id,
                "environment": "local-lab",
                "traffic_type": "synthetic",
                "method": "GET",
                "path": path,
                "status": status,
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            }, ensure_ascii=False))

        def log_message(self, format, *args):
            # Access records go to JSONL instead of the default console format.
            pass

    return LabHandler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--log", type=Path, default=Path("logs/access.jsonl"))
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    args.log.parent.mkdir(parents=True, exist_ok=True)

    access_log = logging.getLogger("lab.access")
    access_log.setLevel(logging.INFO)
    access_log.propagate = False
    handler = logging.FileHandler(args.log, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    access_log.addHandler(handler)

    with ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(access_log, args.config)) as server:
        print(f"Local synthetic lab: http://127.0.0.1:{server.server_port}", flush=True)
        print(f"Log file (append): {args.log.resolve()}", flush=True)
        print("Stop with Ctrl+C", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.", flush=True)
        finally:
            handler.close()
            access_log.removeHandler(handler)


if __name__ == "__main__":
    main()
