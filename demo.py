"""Run an isolated local experiment: HTTP -> JSONL -> SQLite -> SQL report."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
import json
import logging
from pathlib import Path
import threading
import time
import uuid

from analyze import analyze, markdown
from generate_requests import send_requests
from import_logs import import_file
from server import DEFAULT_CONFIG, make_handler


@contextmanager
def local_service(log_path, config_path=DEFAULT_CONFIG):
    logger = logging.Logger("lab.demo")
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    try:
        with ThreadingHTTPServer(("127.0.0.1", 0), make_handler(logger, config_path)) as service:
            thread = threading.Thread(target=service.serve_forever, daemon=True)
            thread.start()
            try:
                yield service.server_port
            finally:
                service.shutdown()
                thread.join(timeout=5)
    finally:
        handler.close()
        logger.removeHandler(handler)


def run_demo(output_dir):
    output_dir = Path(output_dir)
    # Never erase or append to a previous experiment accidentally.
    output_dir.mkdir(parents=True, exist_ok=False)
    log_path = output_dir / "access.jsonl"
    with local_service(log_path) as port:
        responses = send_requests(port, repeat=2)
        if [row["status"] for row in responses] != [200, 404, 500, 200] * 2:
            raise RuntimeError("Unexpected HTTP response sequence")
        # The handler logs after sending the body; reception can finish slightly earlier.
        deadline = time.monotonic() + 3
        while len(log_path.read_text(encoding="utf-8").splitlines()) < 8:
            if time.monotonic() >= deadline:
                raise RuntimeError("Timed out waiting for completed access records")
            time.sleep(0.01)

    db_path = output_dir / "lab.sqlite3"
    first = import_file(log_path, db_path)
    second = import_file(log_path, db_path)
    if (first["inserted"], first["rejected"], second["inserted"], second["duplicates"], second["rejected"]) != (8, 0, 0, 8, 0):
        raise RuntimeError("Duplicate import verification failed")
    report = analyze(db_path)
    summary = report["summary"]
    if (summary["request_count"], summary["client_error_count"], summary["server_error_count"],
        summary["error_pct"]) != (8, 2, 2, 50.0):
        raise RuntimeError("Unexpected SQL metrics")
    if summary["slow_count"] < 2:
        raise RuntimeError("Expected at least two requests with duration >= 500 ms")
    evidence = {"first_import": first, "second_import": second}
    for filename, value in (("report.json", report), ("import-summary.json", evidence)):
        (output_dir / filename).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "report.md").write_text(markdown(report), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    parser.add_argument("--output-dir", type=Path, default=Path("data") / f"demo-{suffix}")
    args = parser.parse_args()
    try:
        report = run_demo(args.output_dir)
    except (OSError, RuntimeError) as error:
        parser.exit(1, f"Demo failed: {error}\n")
    print("PASS: local synthetic HTTP -> JSONL -> SQLite -> SQL")
    print("First import: 8 inserted. Second import: 0 inserted, 8 duplicates.")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"Artifacts: {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
