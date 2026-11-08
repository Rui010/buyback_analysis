# TDnet原典hash・processing run記録・結果version・再利用と費用（Step 1〜3）

仕様: [docs/upstream/tdnet-provenance/buyback-analysis-tdnet-provenance.md](upstream/tdnet-provenance/buyback-analysis-tdnet-provenance.md)（契約版 `tdnet-provenance-v1`）。本書は仕様に対する本リポジトリ側の実装判断だけを記す。

## 有効化

`TDNET_PROVENANCE_ENABLED=true` のときだけ、中計（`main.py`・`backfill_keywords.py`）と会社予想修正（`main.py`）が台帳照合・run記録・結果versionの保存を行う。省略時（`false`）は従来どおりに動き、新しいテーブルにも触れない。ただし `RERUN_URLS` は旧結果を版として残すため有効時だけ使え、無効時に指定すると起動時に停止する（自己株買い・業績ベースラインも同じ）。

有効化の前提:

1. buyback_appの同期allowlist化が受入完了していること（未完了だと新テーブルがPostgreSQLへ自動コピーされる）
2. `scripts/migrate_tdnet_provenance_tables.py` を実行済みであること（未実行なら起動時に停止する）
3. 実行環境がGit checkoutであるか、`CODE_COMMIT`（40桁）が設定されていること（どちらもなければ起動時に停止する）

## テーブル

`tdnet_provenance/models/` の5テーブルは専用の `ProvenanceBase` に登録しており、`init_db()`（`Base.metadata.create_all()`）では作成されない。作成はmigrationスクリプトだけが行う。

- `tdnet_source_documents`（運用原典台帳）: URLごとに1行。初回処理時に登録し、以後は更新・削除しない
- `processing_runs`: 開始したstageごとに終了時に1行INSERTする。token・費用・reuse列はStep 3用で、後から列を追加しないためにNULL許容で先に用意している
- `result_versions`: 1文書の抽出結果1回分。現行結果テーブルに書いた行そのものをJSON（`payload`）で持ち、作ったrunのIDを `run_ids` に持つ。更新・削除しない
- `run_outputs`: 成功したLLM runの出力（LLM関数の戻り値のJSON）。同じ条件のrunを再利用するときに返す
- `result_adoptions`: 採用の追記記録。URL・result_typeごとに最新の行が現在の採用版で、次の行の `adopted_at` までがその版の採用期間

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

PDF取得前のfailed runは `source_hash=NULL`、`input_locator=URL` になる。

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
- `extractor_version`: LLM stageはLLM関数モジュールの `EXTRACTOR_VERSION`（例 `forecast_revision_stage1:1`）。判断runと原典失敗runは `code_commit`
- `generation_config`: LLM関数モジュールの `GENERATION_CONFIG`（`generate_content()` に渡す値と同じ定数）。`response_schema` 等のPydanticモデルはクラス名とJSON Schemaのhashにして記録する
- `code_commit`: `CODE_COMMIT` → `git rev-parse HEAD` の順で取得する。build manifestと `artifact-sha256:` は、本番の反映方法を確認してから実装する


## 結果versionと採用切替（Step 2）

現行結果テーブル（`midterm_plans`・`midterm_plan_keywords`・`forecast_revision_details`・`forecast_revision_metrics`）は「現在の採用値」として残し、互換のため従来と同じ形で読める。保存は `save_midterm_result.py`・`save_forecast_result.py` が `adopt_result()` を通して行う。

| 抽出結果 | 動作 |
|---|---|
| `failed` 以外（中計の `withdrawn`/`postponed`/`no_targets`、会社予想の `no_periods`/`correction`/`withdrawn` を含む） | 1トランザクションで、現行行を置き換え、書いた行を新しい版として `result_versions` へ、採用を `result_adoptions` へ追記する。途中で失敗したらrollbackし旧採用を残す |
| `failed` | 現行行があれば何も書かず旧採用を維持する。なければ従来どおりfailed行を書く（会社予想のfailed再試行・中計の処理済み判定がこの行を使うため）。failed行は版にしない |

- そのURLの版がまだない状態で最初に置き換えるとき、現行行を `origin=legacy` の版として退避する（Step 2適用前の結果を失わないため）。run・hashは持たず、採用時刻も分からないため採用行は作らない。現行行がfailedだけなら退避しない
- 会社予想はStage1が成功すればStage2が失敗しても採用する（Stage1の結果は従来どおり保存する）
- RERUNは削除してから再処理するのをやめ、処理済みスキップだけを外して再処理する。成功時に採用版を切り替え、失敗時は旧採用を維持する
- 現行結果がfailedのURLを再処理するとき（会社予想のfailed再試行・RERUN）は、そのURLの直近のfailed runを今回最初のrunの `retry_of_run_id` にする。failed runは削除しない
- `backfill_keywords.py` は既存の計画行を変えずにキーワードを追加し、計画＋追加キーワードを新しい版として採用する
- 中計の保存は、キーワードと計画を1つの版にまとめる。採用切替中にキーワードの保存が失敗した場合は版を作らない（従来経路はキーワードの失敗に関係なく計画を保存する）

### 自己株買い・業績ベースラインのRERUN

仕様の対象外（台帳照合・run記録は行わない）だが、RERUNで先に削除すると失敗時に旧結果が失われるため、RERUN時の保存だけ同じ `adopt_result()` を使う。通常処理は従来どおり（削除を伴わないため）。

- 版は `run_ids=[]`・`origin=unrecorded`（run記録のない抽出結果）になる。依頼元仕様の外で本リポジトリが追加した範囲
- 自己株買い（`BuybackResultWriter`）: RERUN時はDBの判定結果を使わず種別判定からやり直し、判定結果は採用まで保存しない。保存成功時は `is_checked`（`parse_status=saved`）とIRテーブルの行を1つの版として採用する。判定結果が対象外になった場合も `is_checked`（`skipped`）だけの版として採用する（旧IR行はlegacy版に残る）。抽出・保存に失敗した場合は旧結果に触れない。版の状態列は `is_checked.parse_status`
- 業績ベースライン（`save_earnings_result`）: 中計・会社予想と同じ（failedは旧採用を維持、現行行がなければfailed行を書く）

## 再利用と使用量・費用（Step 3）

### 再利用

`run_llm()` は、同じreuse key（`source_hash`・`input_hash`・`run_kind`・`stage`・`extractor_version`・`prompt_hash`・モデル・`generation_config`）で成功し、出力が `run_outputs` に保存されているrunがあれば、LLMを呼ばずにその出力を返し、`status=reused`・`reused_run_id` のrunを記録する（token・費用は0）。

- `extractor_version` に `code_commit` を使うとcommitのたびに再利用が効かなくなるため、LLM関数モジュールごとの `EXTRACTOR_VERSION` を使う。**LLMの出力を解析する処理（JSON整形・null正規化・スキーマ検証後の加工など）を変えたら、そのモジュールの `EXTRACTOR_VERSION` を上げること。** 上げ忘れると古い解析結果が再利用される。プロンプト・モデル・生成設定（スキーマを含む）・PDF・入力の変更はreuse keyに自動で反映される
- 再利用しない場合: `RERUN_FORCE=true`（全stageでLLMを呼び直す）、retryの最初のrun（失敗の再試行は呼び直す）、失敗run（出力を保存しない）
- RERUNで全stageが再利用された場合も、新しい版と採用は記録する（その時点で再処理したことを残す）
- 出力がJSON化できない場合は保存せず、そのrunは再利用されない（エラーログを出す）

### 使用量・費用

- 8つのLLM関数は `generate_content()` の直後に `report_llm_response(response)` を呼ぶ。`run_llm()` が `capture_llm_usage()` の中でLLM関数を呼ぶため、戻り値を変えずにtoken数とresponse IDを受け取れる。run記録をしない経路（自己株買い等）では何もしない
- `input_tokens` は `prompt_token_count`、`output_tokens` は `candidates_token_count` と `thoughts_token_count` の合計。関数内のリトライで成功応答が複数あれば合計し、`provider_request_id` は最後の応答のID。例外で終わった呼び出しでも、それまでに報告された分を失敗runに記録する
- 費用は `LLM_PRICE_INPUT_PER_1M_TOKENS`・`LLM_PRICE_OUTPUT_PER_1M_TOKENS`・`LLM_PRICE_CURRENCY` の3つを指定したときだけ計算する（単価はコードに持たない。一部だけの指定は起動時エラー）。未指定ならtoken数だけを記録し、費用はNULL
- 文書単位の集計は `aggregate_document_usage()`、表示は `python scripts/report_llm_usage.py [--since 日時] [URL ...]`
