# Web サービスログ分析・障害調査ラボ

**ローカルの合成リクエストを記録し、Python・SQLite・SQL で分析する学習プロジェクトです。** 同じログの再取り込みで件数が増えないことと、模擬設定障害の発生・修正・復旧を再現できます。

実ユーザー・本番環境のデータではありません。実装・テスト・文書作成に AI 支援を使用しています。

## 現在できること

- 200、404、意図的な 500、0.5 秒の待機を含む GET リクエストを生成。
- 時刻・リクエスト ID・パス・ステータス・応答時間を JSON Lines 形式で記録。
- ログを検証して SQLite に取り込み。同一 ID・同一内容は重複、内容が違う同一 ID は競合として報告。
- SQL で件数、4xx/5xx 率、平均・最大応答時間、遅いリクエスト数を集計。
- `/report` の模擬依存先設定を変更し、正常 → 障害 → 復旧を同じリクエストで確認。

これは最初の約 5 時間分の学習範囲を先に実装したスナップショットです。実際の学習時間や理解の完了を示すものではありません。グラフ、実際の依存サービス、Linux・クラウド環境は今後の検討事項です。

## クイックスタート

Python 3.10 以上を想定。Windows / PowerShell / Python 3.14.5 で確認済み。外部パッケージは不要です。以下はリポジトリのルートで実行します。

```powershell
python demo.py
python incident_demo.py
python -m unittest discover -s tests -v
```

`demo.py` は空いているループバックポートで一時サービスを起動し、8 リクエストの生成、2 回の取り込み、SQL 集計まで実行してサービスを終了します。`data/demo-.../` にログ、SQLite、JSON・Markdown の結果を保存します。既存の 8765 番のサービスとは独立して動作します。

`incident_demo.py` は模擬設定障害を自動再現します。各段階で `/` と `/report` を 1 回ずつ要求し、`data/incident-.../` に段階別のログ・SQLite・結果を保存します。既存の出力フォルダーは上書きしません。

## 実測サンプル

実行して保存した [分析結果](examples/pipeline/report.md) と [再取り込み結果](examples/pipeline/import-summary.json) を掲載しています。元の [8 件の合成ログ](examples/pipeline/access.jsonl) から再集計できます。

```powershell
python import_logs.py examples/pipeline/access.jsonl --db data/example.sqlite3
python import_logs.py examples/pipeline/access.jsonl --db data/example.sqlite3
python analyze.py --db data/example.sqlite3 --format markdown --out data/example-report.md
```

新しい DB の初回は 8 件追加、2 回目は追加 0 件・重複 8 件です。各ステータスの内訳は 200 が 4 件、404 が 2 件、500 が 2 件。分母が 8 件なので、4xx 率 25%、5xx 率 25%、総エラー率 50% になります。これは設計した合成リクエストの比率であり、システムの実際の信頼性を表す指標ではありません。応答時間は実行環境で変動します。

障害実験の結果と調査の流れは [障害記録](docs/incident-001.md) を参照してください。

## 手動で動かす

ターミナル A：

```powershell
python server.py --log logs/access.jsonl
```

ターミナル B：

```powershell
python generate_requests.py --repeat 2
python import_logs.py logs/access.jsonl --db data/lab.sqlite3
python analyze.py --db data/lab.sqlite3
python analyze.py --db data/lab.sqlite3 --format markdown --out data/report.md
```

終了はターミナル A の Ctrl+C。ログは追記されます。新しいリクエストには新しい ID が付き、正しく新規件数として数えます。再取り込みの重複排除とは区別します。

| パス | 応答 | 用途 |
| --- | --- | --- |
| `/` | 200 | 正常パス |
| `/missing` などの未定義パス | 404 | 存在しないパス |
| `/error` | 常に 500 | 意図的なエラー応答 |
| `/slow` | 0.5 秒待機後に 200 | 遅い成功応答 |
| `/report` | 設定により 200 または 500 | 模擬設定障害の実験 |

`/report` は `config/service.json` の `dependency_ready` が JSON の `true` の場合に成功します。`false`、設定不正、読み取り失敗なら 500 です。模擬依存先はフラグで表現しており、外部サービスへの接続は行いません。ファイルはリクエストごとに読み直します。

8765 番が使用中ならサーバーと生成器の両方に `--port 8766` を指定します。任意の設定ファイルはサーバーの `--config` で指定できます。

## 指標・品質・制約

- [指標とログの定義](docs/metrics.md)：分母、時刻、計測範囲、空データの扱い。
- [SQL](sql/)：集計処理を Python から分離して掲載。
- [テスト](tests/test_pipeline.py)：再取り込み、新規追加、競合、不正値、時差、空データ、実 HTTP、設定障害と復旧を確認。
- [中国語のモジュール解説](docs/learning-guide.md)：各ファイルの役割と読む順番。

受理された GET ログだけを集計します。クライアント切断、未対応メソッド、HTTP 解析前の失敗、接続拒否はこの JSONL では網羅しません。ブラウザーの追加リクエスト（例：favicon）も件数に入るため、固定件数の再現には自動デモを使います。

不正行を含む取り込みでは正常行を保存し、最大 20 件の行番号と理由を表示します。終了コードは通常成功 0、不正・競合行あり 2、ファイルや DB などの処理失敗 1 です。集計前に取り込み結果を確認してください。ログ書き込み中のファイルは末尾が未完成の場合があるため、実験終了後の取り込みを推奨します。

サービスは `127.0.0.1` のみで待ち受ける教材です。認証、ログローテーション、アラート、本番運用の構成はありません。

## 次の段階

模擬障害の手動調査と本人による説明、用途の明確なグラフ、日文ドキュメントの改善を進めます。履歴書には本人が理解・説明できる実装と検証の範囲だけを記載します。
