# 完了データ バックフィル設計書

## 背景

`prompts/completion.md` の修正（commit aa0bd97）により、`start_date` / `end_date` の抽出対象が「全期間の累計取得実績」に変更された。しかし修正前に取り込まれた `buyback_completion` テーブルの過去レコードは誤った値のまま残っている。本スクリプトでこれらを再抽出・上書きする。

## 対象

- テーブル: `buyback_completion`（SQLite）
- 再抽出プロンプト: `prompts/completion.md`（修正済み）

## 処理フロー

```
1. SQLite の completion テーブルから全レコード（url, code, disclosure_date, resolution_date）を取得
2. 各 URL に対して PostgreSQL（TDnet）からタイトル・社名を取得
3. get_pdf_data() でPDFテキストを取得（ローカルキャッシュ優先）
4. parse_text_by_llm() で Gemini 再抽出（completion.md を使用）
5. 既存レコードを DELETE → INSERT で上書き
```

## DELETE → INSERT を採用する理由

`resolution_date` は複合主キー `(code, disclosure_date, resolution_date)` の一部であり、再抽出で値が変わった場合は UPDATE では対応できないため。

## 注意点

| 項目 | 内容 |
|---|---|
| PDF キャッシュ | `PDF_DOWNLOAD_PATH` にキャッシュがあれば再ダウンロードしない |
| Gemini コスト | completion レコード件数分の API 呼び出しが発生する |
| TDnet 結合 | `completion.url` と `tdnet.url` を突き合わせてタイトル・社名を取得 |
| TDnet に存在しない URL | タイトル・社名が取得できない場合はスキップしてログに記録する |
| 実行エントリーポイント | `scripts/backfill_completion.py`（既存パイプラインとは独立） |

## 実装ファイル

```
scripts/
└── backfill_completion.py   # バックフィル用スクリプト（新規）
```

## 実行方法

```bash
python scripts/backfill_completion.py
```

環境変数は既存の `.env` をそのまま利用する（`SQLITE_DB_URL`, `POSTGRESQL_DB_*`, `GEMINI_API_KEY`, `PDF_DOWNLOAD_PATH`）。
