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

### テスト

```bash
pytest tests/ -v
```