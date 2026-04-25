# 自社株買い分析システム

## 概要

TDNETの一覧から自社株買いに絡むIRを取得し、PDFファイルをダウンロードする
ダウンロードしたPDFファイルをテキストファイルに変換し、LLMにパースさせる
パースした結果をデータベースに格納する

## セットアップ

### 環境変数の設定

1. `.env.example` をコピーして `.env` を作成します
   ```bash
   cp .env.example .env
   ```

2. `.env` ファイルを編集し、以下の値を設定します

   | 変数名 | 説明 | 必須 |
   |---|---|---|
   | `SQLITE_DB_URL` | SQLiteデータベースのパス | ✓ |
   | `POSTGRESQL_DB_HOST` | PostgreSQL ホスト（TDnetデータ用） | ✓ |
   | `POSTGRESQL_DB_PORT` | PostgreSQL ポート | ✓ |
   | `POSTGRESQL_DB_NAME` | PostgreSQL データベース名 | ✓ |
   | `POSTGRESQL_DB_USER` | PostgreSQL ユーザー名 | ✓ |
   | `POSTGRESQL_DB_PASSWORD` | PostgreSQL パスワード | ✓ |
   | `GEMINI_API_KEY` | Google Gemini API キー | ✓ |
   | `PDF_DOWNLOAD_PATH` | PDFダウンロード先ディレクトリ | ✓ |
   | `DAYS_BACK` | デフォルト取得期間（日数）。デフォルト：5 | - |
   | `SYSTEM_START_DATE` | データ取得開始日（YYYY-MM-DD形式）。指定時はDAYS_BACKを無視 | - |
   | `SYSTEM_END_DATE` | データ取得終了日（YYYY-MM-DD形式）。指定時はDAYS_BACKを無視 | - |

### 実行

```bash
python -m buyback_analysis.main
```

### 中期経営計画パイプラインの実行

TDnetの「経営計画」「中計」を含むIRを取得し、Geminiで経営指標を抽出して `midterm_plans` テーブルに保存します。

```bash
python -m midterm_plan_analysis.main
```

自社株買いパイプラインと同じ環境変数（`SQLITE_DB_URL`, `POSTGRESQL_DB_*`, `GEMINI_API_KEY`, `PDF_DOWNLOAD_PATH`, `DAYS_BACK`, `SYSTEM_START_DATE`, `SYSTEM_END_DATE`）を使用します。

#### 過去データを手動で処理する場合

TDnetから直接ダウンロードできない過去のPDFは手動で配置してください。

```
{PDF_DOWNLOAD_PATH}/
└── {YYYYMMDD}/          # 開示日（例: 20230415）
    └── {ファイル名}.pdf  # TDnetのURLのファイル名と同じ名前
```

ファイルが存在する場合はダウンロードをスキップしてそのまま処理を続行します。

### announcements テーブルの resolution_date バックフィル

`resolution_date` カラム追加前に取り込まれた `announcements` の過去レコードに決議日を補完します。

```bash
python -m scripts.backfill_resolution_date
```

### 完了データのバックフィル

`prompts/completion.md` のプロンプト修正前に取り込まれた `buyback_completion` の過去レコードを再抽出・上書きする場合に使用します。

```bash
python -m scripts.backfill_completion
```

途中で失敗した場合は再実行すると、処理済みの URL をスキップして続きから再開します。
全件完了後は `backfill_completion_checkpoint.txt` を削除しても問題ありません。

### テスト

```bash
pytest tests/ -v
```