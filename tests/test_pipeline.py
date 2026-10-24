"""Verify counting correctness, data rejection and an actual local HTTP run."""

import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid
from urllib.error import HTTPError
from urllib.request import ProxyHandler, build_opener

from analyze import analyze, markdown
from demo import local_service, run_demo
from import_logs import import_file, normalize
from incident_demo import run_incident


def record(**updates):
    row = {
        "request_id": str(uuid.uuid4()),
        "timestamp": "2026-10-24T10:00:00+00:00",
        "environment": "local-lab", "traffic_type": "synthetic",
        "method": "GET", "path": "/", "status": 200, "duration_ms": 1.0,
    }
    row.update(updates)
    return row


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.log = self.root / "access.jsonl"
        self.db = self.root / "lab.sqlite3"

    def tearDown(self):
        self.temp.cleanup()

    def write(self, rows):
        self.log.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    def test_reimport_and_new_requests(self):
        rows = [record(), record(status=500)]
        self.write(rows)
        self.assertEqual(import_file(self.log, self.db)["inserted"], 2)
        repeated = import_file(self.log, self.db)
        self.assertEqual((repeated["inserted"], repeated["duplicates"]), (0, 2))
        self.write(rows + [record()])
        added = import_file(self.log, self.db)
        self.assertEqual((added["inserted"], added["duplicates"]), (1, 2))
        self.assertEqual(analyze(self.db)["summary"]["request_count"], 3)

    def test_same_file_duplicates_and_conflicting_id(self):
        original = record()
        conflict = dict(original, status=500)
        self.write([original, original, conflict])
        stats = import_file(self.log, self.db)
        self.assertEqual((stats["inserted"], stats["duplicates"], stats["rejected"]), (1, 1, 1))
        self.assertIn("conflict", stats["issues"][0]["reason"])
        summary = analyze(self.db)["summary"]
        self.assertEqual((summary["request_count"], summary["server_error_count"]), (1, 0))

    def test_invalid_lines_bom_and_blanks(self):
        self.log.write_text("\ufeff" + json.dumps(record()) + '\n\n{bad json}\n[]\n', encoding="utf-8")
        stats = import_file(self.log, self.db)
        self.assertEqual((stats["inserted"], stats["blank_lines"], stats["rejected"]), (1, 1, 2))
        self.assertEqual([issue["line"] for issue in stats["issues"]], [3, 4])

    def test_validation_boundaries(self):
        invalid = [
            {"duration_ms": -1}, {"duration_ms": True}, {"duration_ms": "500"},
            {"duration_ms": float("inf")}, {"duration_ms": float("nan")},
            {"status": True}, {"status": 200.0}, {"status": 99}, {"status": 600},
            {"request_id": "bad"}, {"timestamp": "2026-10-24T10:00:00"},
            {"timestamp": 123}, {"method": "POST"}, {"environment": "production"},
            {"traffic_type": "real"}, {"path": "bad"}, {"path": "/?secret=1"},
        ]
        for update in invalid:
            with self.subTest(update=update), self.assertRaises(ValueError):
                normalize(record(**update))
        missing = record()
        del missing["duration_ms"]
        with self.assertRaises(ValueError):
            normalize(missing)

    def test_equivalent_timezone_and_numeric_format_are_duplicates(self):
        original = record(duration_ms=1)
        equivalent = dict(original, timestamp="2026-10-24T19:00:00+09:00", duration_ms=1.0)
        self.write([original, equivalent])
        stats = import_file(self.log, self.db)
        self.assertEqual((stats["inserted"], stats["duplicates"]), (1, 1))
        self.assertEqual(analyze(self.db)["summary"]["first_request_utc"], "2026-10-24T10:00:00.000000+00:00")

    def test_sql_denominators_and_slow_boundary(self):
        self.write([
            record(duration_ms=0), record(path="/missing", status=404, duration_ms=499.999),
            record(path="/error", status=500, duration_ms=500), record(duration_ms=1000),
            record(path="/redirect", status=302, duration_ms=2),
        ])
        import_file(self.log, self.db)
        report = analyze(self.db)
        summary = report["summary"]
        self.assertEqual((summary["client_error_pct"], summary["server_error_pct"], summary["error_pct"]), (20, 20, 40))
        self.assertEqual((summary["slow_count"], summary["slow_pct"]), (2, 40))
        self.assertAlmostEqual(summary["avg_duration_ms"], 400.4, places=3)
        root = next(row for row in report["by_path"] if row["path"] == "/")
        self.assertEqual((root["request_count"], root["error_pct"], root["avg_duration_ms"]), (2, 0, 500))
        self.assertEqual(analyze(self.db, slow_ms=1000)["summary"]["slow_count"], 1)

    def test_empty_database_and_invalid_threshold(self):
        self.write([])
        import_file(self.log, self.db)
        report = analyze(self.db)
        summary = report["summary"]
        self.assertEqual(summary["request_count"], 0)
        self.assertEqual(summary["error_count"], 0)
        for key in ("error_pct", "avg_duration_ms", "max_duration_ms", "slow_pct"):
            self.assertIsNone(summary[key])
        self.assertEqual(report["by_path"], [])
        self.assertIn("N/A", markdown(report))
        for threshold in (-1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                analyze(self.db, threshold)

    def test_missing_database_is_not_created(self):
        with self.assertRaises(sqlite3.OperationalError):
            analyze(self.db)
        self.assertFalse(self.db.exists())

    def test_cli_rejection_is_visible(self):
        self.log.write_text(json.dumps(record()) + '\n{"bad": 1}\n', encoding="utf-8")
        result = subprocess.run([
            sys.executable, str(Path(__file__).resolve().parents[1] / "import_logs.py"),
            str(self.log), "--db", str(self.db),
        ], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(json.loads(result.stdout)["rejected"], 1)
        self.assertEqual(analyze(self.db)["summary"]["request_count"], 1)

    def test_nonstandard_json_and_duplicate_keys_are_rejected(self):
        self.log.write_text('{"status":200,"status":500}\n{"duration_ms":NaN}\n', encoding="utf-8")
        stats = import_file(self.log, self.db)
        self.assertEqual((stats["inserted"], stats["rejected"]), (0, 2))

    def test_markdown_path_does_not_inject_table_or_html(self):
        self.write([record(path='/<img>|`x`')])
        import_file(self.log, self.db)
        rendered = markdown(analyze(self.db))
        self.assertNotIn("<img>", rendered)
        self.assertIn("&lt;img&gt;&#124;&#96;x&#96;", rendered)

    def test_actual_http_demo(self):
        output = self.root / "demo"
        report = run_demo(output)
        self.assertEqual(report["summary"]["request_count"], 8)
        self.assertEqual(report["summary"]["server_error_pct"], 25)
        self.assertEqual(len((output / "access.jsonl").read_text(encoding="utf-8").splitlines()), 8)
        evidence = json.loads((output / "import-summary.json").read_text(encoding="utf-8"))
        self.assertEqual(evidence["second_import"]["duplicates"], 8)
        self.assertEqual(len(report["by_path"]), 4)
        with self.assertRaises(FileExistsError):
            run_demo(output)

    def test_configuration_fault_and_recovery(self):
        results = run_incident(self.root / "incident")
        self.assertEqual([results[phase]["summary"]["server_error_count"] for phase in (
            "baseline", "fault", "recovered"
        )], [0, 1, 0])
        for phase in results:
            root = next(row for row in results[phase]["by_path"] if row["path"] == "/")
            self.assertEqual(root["server_error_count"], 0)
        report_path = next(row for row in results["fault"]["by_path"] if row["path"] == "/report")
        self.assertEqual(report_path["server_error_count"], 1)

    def test_database_failure_rolls_back_new_rows(self):
        self.write([])
        import_file(self.log, self.db)
        connection = sqlite3.connect(self.db)
        try:
            connection.execute("""CREATE TRIGGER fail_insert BEFORE INSERT ON requests
                WHEN NEW.path = '/force-db-error'
                BEGIN SELECT RAISE(ABORT, 'test database failure'); END""")
            connection.commit()
        finally:
            connection.close()
        self.write([record(), record(path="/force-db-error")])
        with self.assertRaises(sqlite3.IntegrityError):
            import_file(self.log, self.db)
        self.assertEqual(analyze(self.db)["summary"]["request_count"], 0)

    def test_config_failures_and_query_exclusion(self):
        config = self.root / "service.json"
        log = self.root / "service-access.jsonl"
        opener = build_opener(ProxyHandler({}))
        with local_service(log, config) as port:
            for content in (None, "{invalid json}", '{"dependency_ready": "true"}'):
                if content is not None:
                    config.write_text(content, encoding="utf-8")
                with self.assertRaises(HTTPError) as captured:
                    opener.open(f"http://127.0.0.1:{port}/report?example=not-logged", timeout=5)
                with captured.exception as response:
                    self.assertEqual(response.code, 500)
                    response.read()
            config.write_text('{"dependency_ready": true}', encoding="utf-8")
            with opener.open(f"http://127.0.0.1:{port}/report", timeout=5) as response:
                self.assertEqual(response.status, 200)
                response.read()
        rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(row["path"] == "/report" for row in rows))
        self.assertNotIn("not-logged", log.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
