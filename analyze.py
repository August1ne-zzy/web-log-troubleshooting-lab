"""Run the documented SQL metrics and produce JSON or a Markdown report."""

import argparse
from contextlib import closing
import json
import math
from pathlib import Path
import sqlite3

from import_logs import SQL_DIR


def analyze(db_path, slow_ms=500.0):
    if not math.isfinite(slow_ms) or slow_ms < 0:
        raise ValueError("slow_ms must be finite and nonnegative")
    # Read-only: a typo must not silently create a new empty database.
    with closing(sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        params = {"slow_ms": slow_ms}
        summary = dict(connection.execute(
            (SQL_DIR / "summary.sql").read_text(encoding="utf-8"), params
        ).fetchone())
        paths = [dict(row) for row in connection.execute(
            (SQL_DIR / "by_path.sql").read_text(encoding="utf-8"), params
        )]
    return {
        "environment": "local-lab",
        "traffic_type": "synthetic",
        "scope": "all accepted unique records in this database; all paths and statuses",
        "slow_threshold_ms": slow_ms,
        "summary": summary,
        "by_path": paths,
    }


def markdown(report):
    def display(value):
        return "N/A" if value is None else str(value)

    summary = report["summary"]
    lines = [
        "# ローカル合成リクエストの分析結果", "",
        "実ユーザー・本番環境のデータではありません。数値はこの実験の観測値です。", "",
        "集計対象：このデータベースに受理された一意なリクエスト全件（全パス・全ステータス）。", "",
        f"記録開始（UTC）：{display(summary['first_request_utc'])}", "",
        f"記録終了（UTC）：{display(summary['last_request_utc'])}", "",
        "| 指標 | 値 |", "| --- | ---: |",
    ]
    for label, key in (
        ("リクエスト数", "request_count"),
        ("4xx 件数", "client_error_count"),
        ("5xx 件数", "server_error_count"),
        ("4xx 率 (%)", "client_error_pct"),
        ("5xx 率 (%)", "server_error_pct"),
        ("総エラー率：4xx + 5xx (%)", "error_pct"),
        ("平均応答時間 (ms)", "avg_duration_ms"),
        ("最大応答時間 (ms)", "max_duration_ms"),
        (f"遅いリクエスト数：>= {report['slow_threshold_ms']} ms", "slow_count"),
        ("遅いリクエスト率 (%)", "slow_pct"),
    ):
        lines.append(f"| {label} | {display(summary[key])} |")
    lines += ["", "| パス | 件数 | 4xx | 5xx | 総エラー率 (%) | 平均 (ms) | 最大 (ms) | 遅い件数 |",
              "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for row in report["by_path"]:
        # JSON escaping plus HTML entities prevent a path from injecting Markdown/HTML.
        path = json.dumps(row["path"], ensure_ascii=True)[1:-1]
        path = path.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        path = path.replace("|", "&#124;").replace("`", "&#96;")
        lines.append(f"| {path} | " + " | ".join(str(row[key]) for key in (
            "request_count", "client_error_count", "server_error_count", "error_pct",
            "avg_duration_ms", "max_duration_ms", "slow_count",
        )) + " |")
    lines += ["", "分母はいずれも対象リクエスト数。遅延は全ステータスのサーバー側 duration_ms を使用。",
              "空データでは件数は 0、比率と応答時間は N/A。最大値は p95 ではありません。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/lab.sqlite3"))
    parser.add_argument("--slow-ms", type=float, default=500.0)
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    try:
        report = analyze(args.db, args.slow_ms)
        output = markdown(report) if args.format == "markdown" else json.dumps(report, ensure_ascii=False, indent=2)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(output.rstrip("\n") + "\n", encoding="utf-8")
        else:
            print(output)
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(1, f"Analysis failed: {error}\n")


if __name__ == "__main__":
    main()
