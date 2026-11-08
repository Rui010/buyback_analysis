# TDnet原典hash・processing run記録（Step 1）

仕様: [docs/upstream/tdnet-provenance/buyback-analysis-tdnet-provenance.md](upstream/tdnet-provenance/buyback-analysis-tdnet-provenance.md)（契約版 `tdnet-provenance-v1`）。本書は仕様に対する本リポジトリ側の実装判断だけを記す。

## 有効化

`TDNET_PROVENANCE_ENABLED=true` のときだけ、中計（`main.py`・`backfill_keywords.py`）と会社予想修正（`main.py`）が台帳照合とrun記録を行う。省略時（`false`）は従来どおりに動き、新しいテーブルにも触れない。

有効化の前提:

1. buyback_appの同期allowlist化が受入完了していること（未完了だと新テーブルがPostgreSQLへ自動コピーされる）
2. `scripts/migrate_tdnet_provenance_tables.py` を実行済みであること（未実行なら起動時に停止する）
3. 実行環境がGit checkoutであるか、`CODE_COMMIT`（40桁）が設定されていること（どちらもなければ起動時に停止する）

## テーブル

`tdnet_provenance/models/` の2テーブルは専用の `ProvenanceBase` に登録しており、`init_db()`（`Base.metadata.create_all()`）では作成されない。作成はmigrationスクリプトだけが行う。

- `tdnet_source_documents`（運用原典台帳）: URLごとに1行。初回処理時に登録し、以後は更新・削除しない
- `processing_runs`: 開始したstageごとに終了時に1行INSERTする。token・費用・retry/reuse列はStep 3用で、後から列を追加しないためにNULL許容で先に用意している

## 処理順序

各エントリーポイントは `prepare_pdf_input()`（`tdnet_provenance/usecase/`）でPDF入力を用意し、LLM stageは `run_midterm_stages.py`（中計）・`run_forecast_revision_stages.py`（会社予想。タイトルの取り下げ判定を含む）経由で呼ぶ。これらは `sqlite_engine` をimportしないため、`main.py` を対象外とするテスト方針のままで配線をユニットテストできる。

`prepare_pdf_input()` は、recorderがあれば `resolve_verified_source()` で照合済みのパスだけを使い（text方式は `extract_pdf_text()` で同じファイルを読む）、なければ従来どおり `get_pdf_path()` / `get_pdf_data()` を使う。`resolve_verified_source()` は次を行う。

1. 台帳に行がなければ `fetch_pdf()` でPDFを取得（保存済みなら再利用）し、hashを計算して台帳へ登録・commitする
2. 台帳行の `storage_uri` から実ファイルを解決して再hashし、台帳値と照合する

| 状態 | error_code | 動作 |
|---|---|---|
| ダウンロード失敗 | `download_failed` | failed runを記録し、LLMを呼ばない |
| 台帳登録済みのPDFが消えた | `source_missing` | 再ダウンロードしない。同じbytesを戻せば再開できる |
| PDFのhashが台帳と違う | `source_conflict` | 台帳は書き換えず、手動確認まで停止する |
| hash計算失敗 | `hash_failed` | failed runを記録 |
| URL・公表日・保存先が規則に合わない | `contract_error` | failed runを記録 |
| text方式でテキスト抽出失敗 | `pdf_read_failed` | 照合済みのhashを持つfailed runを記録 |

PDF取得前のfailed runは `source_hash=NULL`、`input_locator=URL` になる。既存の結果テーブル（`midterm_plans` 等）への `failed` 保存は従来どおり行う（採用版の扱いはStep 2で変える）。

既存PDFを初めて台帳へ登録した場合は `fetched_at=NULL` で、`observed_at` 以降の基準値として扱う。過去の抽出結果へhashをbackfillしない。

## runの記録内容

| stage | パイプライン | 記録する入力（`input_hash`の元） |
|---|---|---|
| `metrics` / `keywords` | 中計 | title・code・name（text方式は抽出テキストのSHA-256も） |
| `classification` | 中計 | title・code・name・分類に渡したテキストのSHA-256 |
| `stage1` | 会社予想 | metricsと同じ |
| `stage2` | 会社予想 | Stage2に渡した要約テキストのSHA-256 |
| `eligibility`（`run_kind=route`） | 会社予想 | タイトル・判定規則。タイトルの取り下げ判定で `outcome=withdrawn`、`outcome_reason=title_keyword:<一致語>` |

- PDFの絶対パスは `input_hash` に含めない（保存先を変えても `input_hash` は変わらない）
- 成否は、LLM関数が `None` を返したら（分類は `"failed"` を返したら）`failed` / `no_result`、`SystemExit` 等の例外なら `failed` / 例外のクラス名とし、例外はそのまま再送出する
- run自体を保存できなかった場合は `RunPersistError` でパイプラインを止める。これは、runのない抽出結果を保存しないため
- 中計の `withdrawn` / `postponed` / `no_targets` はmetrics・classificationのLLMの後に決まるため、判断runにはしない（仕様 §4.5）
- `extractor_version`: 抽出器の論理版はまだ管理していないため、`code_commit` と同じ値を明示的に保存する（reuse keyの値は仕様の代替規則と同じになる）
- `code_commit`: `CODE_COMMIT` → `git rev-parse HEAD` の順で取得する。build manifestと `artifact-sha256:` は、本番の反映方法を確認してから実装する

## Step 1で記録しない項目

- `generation_config`: `{}` で記録する。LLM関数内の設定には `response_schema` などJSON化できない値が含まれ、呼び出し側へ写すとずれるため、Step 3でLLM関数から返す形にする
- token・費用・request ID: Step 3で対応する
