# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 実行コマンド

```bash
# 依存関係のインストール
pip install -r requirements.txt

# 自己株買いパイプラインの実行
python -m buyback_analysis.main

# 中期経営計画パイプラインの実行
python -m midterm_plan_analysis.main
```

## 環境変数（`.env`）

| 変数名 | 説明 |
|---|---|
| `SQLITE_DB_URL` | SQLite接続URL（例: `sqlite:///./data.db`） |
| `POSTGRESQL_DB_HOST` | TDnetデータのPostgreSQLホスト |
| `POSTGRESQL_DB_PORT` | PostgreSQLポート |
| `POSTGRESQL_DB_NAME` | PostgreSQLデータベース名 |
| `POSTGRESQL_DB_USER` | PostgreSQLユーザー |
| `POSTGRESQL_DB_PASSWORD` | PostgreSQLパスワード |
| `GEMINI_API_KEY` | Google Gemini API キー |
| `PDF_DOWNLOAD_PATH` | PDFの保存先ディレクトリ |

## アーキテクチャ概要

### buyback_analysis（自己株買い分析）

```
buyback_analysis/
├── main.py              # エントリーポイント・パイプライン制御
├── consts/
│   └── detect_type.py   # DetectType Enum（文書種別の定義）
├── interface/
│   ├── postgresql_engine.py   # TDnetデータ読み込み用DB接続
│   ├── sqlite_engine.py       # 結果保存用SQLite接続・init_db()
│   └── load_prompt_template.py  # prompts/*.md を読み込みformat()
├── models/              # SQLAlchemy ORMモデル（SQLite用）
│   ├── base.py
│   ├── announcement.py  # buyback_announcements テーブル
│   ├── progress.py      # buyback_progress テーブル
│   ├── completion.py    # buyback_completion テーブル
│   ├── correction.py    # corrections テーブル
│   └── is_checked.py    # is_checked テーブル（URL処理済み管理）
├── prompts/             # Gemini APIへのプロンプトテンプレート（Markdown）
│   ├── ir_type.md       # 文書種別判定用
│   ├── announcement.md  # 発表データ抽出用
│   ├── progress.md      # 進捗データ抽出用
│   ├── completion.md    # 完了データ抽出用
│   ├── correction.md    # 訂正データ抽出用
│   └── midterm_plan.md  # 中期経営計画抽出用（midterm_plan_analysisが参照）
└── usecase/             # ビジネスロジック
    ├── detect_type.py   # LLMによる文書種別判定
    ├── parse_text_by_llm.py  # LLMによる構造化JSON抽出
    ├── post_data.py     # SQLiteへの保存（DetectTypeでモデルを選択）
    ├── post_url.py      # is_checkedテーブルへのURL登録
    ├── get_tdnet_buyback_data.py  # PostgreSQLから「自己株」含みタイトルを取得
    ├── get_pdf_data.py  # PDFダウンロード・テキスト抽出
    ├── data_exists.py   # 重複チェック
    └── logger.py        # ロガー
```

### midterm_plan_analysis（中期経営計画分析）

```
midterm_plan_analysis/
├── main.py              # エントリーポイント・パイプライン制御
├── models/
│   └── midterm_plan.py  # midterm_plans テーブル（SQLAlchemy ORM）
└── usecase/
    ├── get_tdnet_midterm_data.py  # PostgreSQLから「経営計画」「中計」含みタイトルを取得
    └── post_midterm_plan.py       # SQLiteへの保存
```

`interface/`・`usecase/logger.py`・`usecase/get_pdf_data.py`・`usecase/parse_text_by_llm.py` は `buyback_analysis` のものを共用する。

## データフロー

### buyback_analysis

1. **PostgreSQL**（外部DB）から`tdnet`テーブルの「自己株」含みIR一覧を取得
2. 各IRのPDFをダウンロードしてテキスト抽出
3. `is_checked`テーブルで処理済みか確認 → 未処理なら**Gemini**で`DetectType`を判定してDB登録
4. 対象外の`DetectType`（`OTHER`, `EQUITY_COMPENSATION`, `STRATEGIC_TRANSACTION`）はスキップ
5. 対象の文書は種別に対応するプロンプトテンプレートを使い**Gemini**でJSON抽出
6. 抽出結果を**SQLite**の対応テーブルに保存

### midterm_plan_analysis

1. **PostgreSQL**から`tdnet`テーブルのタイトルに「経営計画」または「中計」を含むIR一覧を取得
2. 各IRのPDFをダウンロードしてテキスト抽出
3. `midterm_plans`テーブルの主キー（`code` + `url`）で重複チェック → 処理済みならスキップ
4. `buyback_analysis/prompts/midterm_plan.md` を使い**Gemini**でJSON抽出
5. 抽出結果（計画名・開始/終了年度・定量目標一覧）を**SQLite**の`midterm_plans`テーブルに保存

## 重要な設計上の注意点

- **2つのDB**が並行して使われる: 読み取り元はPostgreSQL（TDnetデータ）、書き込み先はSQLite（分析結果）
- `is_checked`テーブルがURLの処理済み管理を担う。データ保存の重複チェックは`data_exists_in_ir_tables()`が別途担当
- プロンプトテンプレート（`prompts/*.md`）は`{title}`, `{content}`, `{code}`, `{name}` などのPython `str.format()`プレースホルダーを使う
- `parse_text_by_llm()`はGeminiのレスポンスから` ```json ` コードブロックを除去してJSONパースする
- Gemini APIは`gemini-2.0-flash-lite`を使用。502/503/504エラー時は60秒待機で最大3回リトライ
- `post_data()`はLLMが返す辞書の`type`フィールドで`DetectType`を判別し、対応するORMモデルにマッピングする
- `midterm_plan_analysis` は独自の `interface/` を持たず、`buyback_analysis` のユーティリティ群（`postgresql_engine`・`sqlite_engine`・`get_pdf_data`・`parse_text_by_llm`・`Logger`）を共用する
- `load_prompt_template()` は自身のパッケージ（`buyback_analysis/`）配下の `prompts/` を参照するため、`midterm_plan.md` も `buyback_analysis/prompts/` に配置する（`midterm_plan_analysis/prompts/` は存在しない）
- `midterm_plan_analysis` の重複チェックは `is_checked` テーブルではなく `midterm_plans` 主キー（`code` + `url`）で行う
