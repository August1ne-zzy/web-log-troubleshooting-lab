"""Reproduce and correct a simulated dependency configuration fault locally."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.request import ProxyHandler, build_opener
import uuid

from analyze import analyze, markdown
from demo import local_service
from import_logs import import_file


def run_incident(output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    config_path = output_dir / "service.json"
    log_path = output_dir / "access.jsonl"
    opener = build_opener(ProxyHandler({}))
    phase_ids = {}
    with local_service(log_path, config_path) as port:
        # Healthy -> injected configuration error -> corrected configuration.
        for phase, ready in (("baseline", True), ("fault", False), ("recovered", True)):
            config_path.write_text(json.dumps({"dependency_ready": ready}) + "\n", encoding="utf-8")
            ids = set()
            for path in ("/", "/report"):
                try:
                    response = opener.open(f"http://127.0.0.1:{port}{path}", timeout=5)
                except HTTPError as error:
                    response = error
                with response:
                    payload = json.loads(response.read())
                    expected = 500 if phase == "fault" and path == "/report" else 200
                    if response.code != expected:
                        raise RuntimeError(f"Unexpected response for {phase} {path}")
                    ids.add(payload["request_id"])
            phase_ids[phase] = ids
        deadline = time.monotonic() + 3
        while len(log_path.read_text(encoding="utf-8").splitlines()) < 6:
            if time.monotonic() > deadline:
                raise RuntimeError("Timed out waiting for incident access records")
            time.sleep(0.01)

    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    results = {}
    for phase, ids in phase_ids.items():
        directory = output_dir / phase
        directory.mkdir()
        phase_log = directory / "access.jsonl"
        selected = [row for row in rows if row["request_id"] in ids]
        if len(selected) != 2:
            raise RuntimeError("Missing phase records")
        phase_log.write_text("".join(json.dumps(row) + "\n" for row in selected), encoding="utf-8")
        stats = import_file(phase_log, directory / "lab.sqlite3")
        if stats["inserted"] != 2 or stats["rejected"]:
            raise RuntimeError("Incident import failed")
        report = analyze(directory / "lab.sqlite3")
        expected_errors = 1 if phase == "fault" else 0
        if report["summary"]["server_error_count"] != expected_errors:
            raise RuntimeError("Unexpected incident SQL result")
        (directory / "report.md").write_text(markdown(report), encoding="utf-8")
        results[phase] = report
    (output_dir / "incident-results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    parser.add_argument("--output-dir", type=Path, default=Path("data") / f"incident-{suffix}")
    args = parser.parse_args()
    try:
        results = run_incident(args.output_dir)
    except (OSError, RuntimeError) as error:
        parser.exit(1, f"Incident demo failed: {error}\n")
    for phase, report in results.items():
        summary = report["summary"]
        print(f"{phase}: requests={summary['request_count']} 5xx={summary['server_error_count']} 5xx_pct={summary['server_error_pct']}")
    print(f"Artifacts: {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
