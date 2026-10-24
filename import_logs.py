"""Validate local JSONL records and import unique requests into SQLite."""

import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3
import uuid


SQL_DIR = Path(__file__).resolve().parent / "sql"
COLUMNS = (
    "request_id", "timestamp", "environment", "traffic_type",
    "method", "path", "status", "duration_ms",
)


def normalize(record):
    """Return only known fields, normalized for consistent duplicate comparison."""
    if not isinstance(record, dict):
        raise ValueError("record must be a JSON object")
    if any(field not in record for field in COLUMNS):
        raise ValueError("missing required field")
    if any(not isinstance(record[field], str) for field in COLUMNS[:6]):
        raise ValueError("ID, timestamp, labels, method and path must be strings")
    try:
        request_id = str(uuid.UUID(record["request_id"]))
    except ValueError:
        raise ValueError("request_id must be a UUID") from None
    try:
        timestamp = datetime.fromisoformat(record["timestamp"].replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("timestamp must be ISO 8601") from None
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    timestamp = timestamp.astimezone(timezone.utc).isoformat(timespec="microseconds")
    if (record["environment"], record["traffic_type"], record["method"]) != (
        "local-lab", "synthetic", "GET"
    ):
        raise ValueError("only local-lab / synthetic / GET records are supported")
    if not record["path"].startswith("/") or "?" in record["path"] or "#" in record["path"]:
        raise ValueError("path must start with / and exclude query and fragment")
    status = record["status"]
    if type(status) is not int or not 100 <= status <= 599:
        raise ValueError("status must be an integer from 100 to 599")
    duration = record["duration_ms"]
    if type(duration) not in (int, float):
        raise ValueError("duration_ms must be a finite nonnegative number")
    try:
        duration = float(duration)
    except OverflowError:
        raise ValueError("duration_ms is too large") from None
    if not math.isfinite(duration) or duration < 0:
        raise ValueError("duration_ms must be a finite nonnegative number")
    return (request_id, timestamp, "local-lab", "synthetic", "GET", record["path"], status, duration)


def reject_constant(value):
    raise ValueError("nonstandard JSON numeric constant")


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def import_file(log_path, db_path):
    stats = {"inserted": 0, "duplicates": 0, "rejected": 0, "blank_lines": 0, "issues": []}
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig also accepts a UTF-8 BOM created by some Windows tools.
    with Path(log_path).open(encoding="utf-8-sig") as source, closing(sqlite3.connect(db_path)) as connection, connection:
        connection.executescript((SQL_DIR / "schema.sql").read_text(encoding="utf-8"))
        connection.execute("BEGIN IMMEDIATE")
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                stats["blank_lines"] += 1
                continue
            try:
                record = json.loads(line, parse_constant=reject_constant, object_pairs_hook=unique_keys)
                values = normalize(record)
                existing = connection.execute(
                    f"SELECT {', '.join(COLUMNS)} FROM requests WHERE request_id = ?", (values[0],)
                ).fetchone()
                if existing is not None:
                    if existing != values:
                        raise ValueError("request_id conflict: stored fields differ")
                    stats["duplicates"] += 1
                    continue
                connection.execute(
                    f"INSERT INTO requests ({', '.join(COLUMNS)}) VALUES ({', '.join('?' for _ in COLUMNS)})",
                    values,
                )
                stats["inserted"] += 1
            except (ValueError, OverflowError) as error:
                stats["rejected"] += 1
                if len(stats["issues"]) < 20:
                    # Record location and reason, not the raw potentially sensitive line.
                    reason = "invalid JSON" if isinstance(error, json.JSONDecodeError) else str(error)
                    stats["issues"].append({"line": line_number, "reason": reason})
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--db", type=Path, default=Path("data/lab.sqlite3"))
    args = parser.parse_args()
    try:
        stats = import_file(args.log, args.db)
    except (OSError, UnicodeError, sqlite3.Error) as error:
        parser.exit(1, f"Import failed: {error}\n")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    # Valid rows are committed even if other lines were rejected. Make partial success visible.
    raise SystemExit(2 if stats["rejected"] else 0)


if __name__ == "__main__":
    main()
