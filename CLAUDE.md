# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 方針

- テストファースト
- 設計はドキュメントに残す
- カバレッジを計算して

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
| `SLACK_TOKEN` | Slack Bot トークン（省略時は通知しない） |
| `SLACK_CHANNEL` | 通知先チャンネル（例: `#alerts`） |
| `SLACK_MENTION` | エラー時のメンション先（例: `@username`、省略可） |
| `BUYBACK_USE_NATIVE_PDF` | `true` でbuyback_analysisの抽出ステップをネイティブPDF方式に切り替え（省略時は`false`） |
| `MIDTERM_USE_NATIVE_PDF` | `true` でmidterm_plan_analysisをネイティブPDF方式に切り替え（省略時は`false`） |
| `RERUN_URLS` | カンマ区切りのURLリスト。指定したURLの既存データを削除して強制再処理する（両パイプライン共通） |

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
│   ├── load_prompt_template.py  # prompts/*.md を読み込みformat()
│   ├── logger.py              # ロガー
│   └── notifier.py            # Slack通知
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
    └── data_exists.py   # 重複チェック
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

`interface/`・`usecase/get_pdf_data.py`・`usecase/parse_text_by_llm.py` は `buyback_analysis` のものを共用する。

### forecast_revision_analysis（業績予想修正分析）

```
forecast_revision_analysis/
├── main.py              # エントリーポイント・パイプライン制御
├── models/
│   ├── forecast_revision_detail.py   # forecast_revision_details テーブル（詳細）
│   └── forecast_revision_metric.py   # forecast_revision_metrics テーブル（期間別指標）
└── usecase/
    ├── get_tdnet_forecast_revision_data.py       # PostgreSQLから「修正」「業績」含みタイトルを取得
    ├── schemas.py                                # Stage1/Stage2のresponseSchema（Pydantic）
    ├── extract_forecast_revision_stage1.py        # Stage1抽出（テキスト方式）
    ├── extract_forecast_revision_stage1_native.py # Stage1抽出（ネイティブPDF方式）
    ├── build_stage2_context.py                    # Stage1結果からStage2用の要約テキストを整形
    ├── infer_forecast_revision_stage2.py           # Stage2推論（PDF本文は再送しない）
    ├── merge_stage_results.py                      # Stage1/Stage2結果をpost_forecast_revision()の入力shapeにマージ
    └── post_forecast_revision.py                   # SQLiteへの保存・欠損チェック
```

`buyback_analysis` の `interface/` および `usecase/get_pdf_data.py` を共用する。LLM抽出はStage1/Stage2に分離しており、汎用の `parse_text_by_llm`/`parse_pdf_by_llm`（buyback_analysis/midterm_plan_analysisが使用）とは別に、forecast_revision_analysis固有のPydanticスキーマ付き抽出関数を持つ（詳細は `docs/forecast_revision_llm_pipeline_redesign.md`）。

## データフロー

### buyback_analysis

1. **PostgreSQL**（外部DB）から`tdnet`テーブルの「自己株」含みIR一覧を取得
2. 各IRのPDFをダウンロードしてテキスト抽出
3. `is_checked`テーブルで処理済みか確認 → 未処理なら**Gemini**で`DetectType`を判定してDB登録
4. 対象外の`DetectType`（`OTHER`, `EQUITY_COMPENSATION`, `STRATEGIC_TRANSACTION`）はスキップ
5. 対象の文書は種別に対応するプロンプトテンプレートを使い**Gemini**でJSON抽出
6. 抽出結果を**SQLite**の対応テーブルに保存

### forecast_revision_analysis

1. **PostgreSQL**から`tdnet`テーブルのタイトルに「修正」「業績」両方を含むIR一覧を取得
2. 各IRのPDFをダウンロードしてテキスト抽出（`FORECAST_REVISION_USE_NATIVE_PDF=true` でネイティブPDF方式）
3. `forecast_revision_details` 主キー（`code` + `url`）で重複チェック → 処理済みならスキップ
4. タイトルに「取り下げ」「廃止」「撤回」があれば `extraction_status=withdrawn` で即保存
5. **Stage1**: `buyback_analysis/prompts/forecast_revision_stage1.md`（ネイティブPDF方式は`forecast_revision_stage1_native.md`）を使い**Gemini**で抽出系フィールド（`periods`/`prev_forecast_date`/`value_unit`/`reason_raw`）を`responseSchema`（`Stage1Extraction`）で型固定して抽出
6. **Stage2**: Stage1結果から`build_stage2_context()`で機械整形した要約テキスト（PDF本文は含まない）をもとに、`buyback_analysis/prompts/forecast_revision_stage2.md`を使い**Gemini**で推論系フィールド（`direct_factors`/`structural_vulnerability`/`spillover_conditions`）を`responseSchema`（`Stage2Inference`）で抽出。Stage1が失敗した場合はStage2を実行しない
7. `merge_stage_results()`でStage1/Stage2の結果をマージ（Stage2失敗時は推論系フィールドを`None`のまま、Stage1のデータは保存する）
8. マージ結果の`periods`について、`prev_value != curr_value` の期間が1件以上あれば `ok`、なければ `no_periods`、Stage1失敗は `failed`（`is_modified`はLLMに問い合わせず`prev_value`/`curr_value`の比較でコード側が確定する）
9. 抽出結果を `forecast_revision_details`（詳細）・`forecast_revision_metrics`（期間別指標）に保存
10. `extraction_status=ok` のレコードに限り `check_missing_fields()` で欠損チェックを実施
11. 欠損があればログに `[MISSING] field=... code=... url=...` 形式で記録（URL付きでgrepしやすくする）
12. 完了通知のサマリーに「欠損データ: X件」として件数を含める

### midterm_plan_analysis

1. **PostgreSQL**から`tdnet`テーブルのタイトルに「経営計画」または「中計」を含むIR一覧を取得
2. 各IRのPDFをダウンロードしてテキスト抽出
3. `midterm_plans`テーブルの主キー（`code` + `url`）で重複チェック → 処理済みならスキップ
4. `buyback_analysis/prompts/midterm_plan.md` を使い**Gemini**でJSON抽出
5. 抽出結果（計画名・開始/終了年度・定量目標一覧）を**SQLite**の`midterm_plans`テーブルに保存

## テスト方針

```bash
# テスト実行（仮想環境をActivateしてから）
pytest tests/ -v
```

### ディレクトリ構成

```
tests/
├── buyback_analysis/
│   ├── models/       # ORMモデルのカラム定義・主キーの確認
│   └── usecase/      # ユースケース関数の単体テスト
└── midterm_plan_analysis/
    ├── models/
    └── usecase/
```

### テストを書く対象・書かない対象

**書く対象（ユニットテスト）**
- `usecase/` 配下の関数: 外部依存（Gemini API・DB）は `unittest.mock` でモックする
- `models/` 配下のORMモデル: カラム定義・型・主キーの確認
- バリデーションロジック・分岐（正常系・異常系・境界値）

**書かない対象**
- `main.py` のパイプライン全体: PostgreSQL・Gemini API・ファイルシステムへの依存が多く、統合テストになるため対象外
- `interface/` 配下のDB接続・ロガー: インフラ層のため対象外

### モックの方針

- Gemini API（`genai.Client`）は `unittest.mock.patch` でモックし、実APIは呼ばない
- SQLAlchemyセッションは `MagicMock()` を渡す
- 環境変数は `monkeypatch.setenv()` で設定する

### 実装変更時のテスト更新ルール

- モデルのカラム・型・主キーを変更したら `tests/*/models/` のテストを必ず更新する
- `usecase/` に新しい関数を追加したら対応するテストファイルも作成する
- 有効値の列挙（例: `extraction_status` の値セット）を変更したら、そのバリデーションのテストも更新する

## 重要な設計上の注意点

- **2つのDB**が並行して使われる: 読み取り元はPostgreSQL（TDnetデータ）、書き込み先はSQLite（分析結果）
- `is_checked`テーブルがURLの処理済み管理を担う。データ保存の重複チェックは`data_exists_in_ir_tables()`が別途担当
- プロンプトテンプレート（`prompts/*.md`）は`{title}`, `{content}`, `{code}`, `{name}` などのPython `str.format()`プレースホルダーを使う
- `parse_text_by_llm()`はGeminiのレスポンスから` ```json ` コードブロックを除去してJSONパースする
- Gemini APIは`gemini-2.5-flash-lite`を使用。502/503/504エラー時は60秒待機で最大3回リトライ
- `post_data()`はLLMが返す辞書の`type`フィールドで`DetectType`を判別し、対応するORMモデルにマッピングする
- `midterm_plan_analysis` は独自の `interface/` を持たず、`buyback_analysis` のユーティリティ群（`postgresql_engine`・`sqlite_engine`・`logger`・`notifier`・`get_pdf_data`・`parse_text_by_llm`）を共用する
- `load_prompt_template()` は自身のパッケージ（`buyback_analysis/`）配下の `prompts/` を参照するため、`midterm_plan.md` も `buyback_analysis/prompts/` に配置する（`midterm_plan_analysis/prompts/` は存在しない）
- `midterm_plan_analysis` の重複チェックは `is_checked` テーブルではなく `midterm_plans` 主キー（`code` + `url`）で行う
- `forecast_revision_analysis` の欠損チェック対象フィールド: detail レベルは `prev_forecast_date`、period レベルは `metric_name`・`label_raw`・`prev_value`・`curr_value`・`fiscal_year`・`consolidation_type`。これらが null だとデータとして意味をなさない。`check_missing_fields()` は `extraction_status=ok` のレコードにのみ適用し、欠損があっても保存は行う（欠損件数を完了通知のサマリーに含める）
- `forecast_revision_analysis` のLLM抽出はStage1（抽出・`responseSchema`で型固定・`temperature=0`）とStage2（推論・PDF本文は再送せずStage1の要約のみを入力・`temperature=0.2`）に分離している。`is_modified`はStage1のresponseSchemaに含めず、`prev_value`/`curr_value`の比較でコード側（`post_forecast_revision.py`・`main.py`の`_determine_extraction_status()`）が確定する。設計背景は `docs/forecast_revision_llm_pipeline_redesign.md` を参照
- `forecast_revision_metrics` の自然キーは `(url, period_type, fiscal_year, consolidation_type, metric_name)` の複合ユニーク制約で担保する。`fiscal_year`（対象決算期の西暦年）・`consolidation_type`（`consolidated`=連結 / `non_consolidated`=単体・個別）がないと、同一期間・同一指標名で連結/単体や決算年度違いの行を区別できず重複を検出できない設計上の欠陥があったため追加した（詳細は `docs/forecast_revision.md` §7参照）
- ログは3パイプラインとも `interface/logger.py` の `Logger` を共用するが、各`main.py`の先頭（他のimportより前）で `os.environ.setdefault("LOG_FILE", "...")` を設定することで出力先を分けている（`buyback_analysis.log` / `midterm_plan_analysis.log` / `forecast_revision_analysis.log`）。`get_pdf_data()` など複数パイプラインで共用しているモジュールも、実行中のパイプラインに応じて自動的に正しいログファイルへ振り分けられる。`LOG_FILE`未設定時は`app.log`（`Logger`のデフォルト）
