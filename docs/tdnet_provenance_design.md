# TDnet原典hash・processing run記録・結果version（Step 1・2）

仕様: [docs/upstream/tdnet-provenance/buyback-analysis-tdnet-provenance.md](upstream/tdnet-provenance/buyback-analysis-tdnet-provenance.md)（契約版 `tdnet-provenance-v1`）。本書は仕様に対する本リポジトリ側の実装判断だけを記す。

## 有効化

`TDNET_PROVENANCE_ENABLED=true` のときだけ、中計（`main.py`・`backfill_keywords.py`）と会社予想修正（`main.py`）が台帳照合・run記録・結果versionの保存を行う。省略時（`false`）は従来どおりに動き、新しいテーブルにも触れない。ただし `RERUN_URLS` は旧結果を版として残すため有効時だけ使え、無効時に指定すると起動時に停止する。

有効化の前提:

1. buyback_appの同期allowlist化が受入完了していること（未完了だと新テーブルがPostgreSQLへ自動コピーされる）
2. `scripts/migrate_tdnet_provenance_tables.py` を実行済みであること（未実行なら起動時に停止する）
3. 実行環境がGit checkoutであるか、`CODE_COMMIT`（40桁）が設定されていること（どちらもなければ起動時に停止する）

## テーブル

`tdnet_provenance/models/` の4テーブルは専用の `ProvenanceBase` に登録しており、`init_db()`（`Base.metadata.create_all()`）では作成されない。作成はmigrationスクリプトだけが行う。

- `tdnet_source_documents`（運用原典台帳）: URLごとに1行。初回処理時に登録し、以後は更新・削除しない
- `processing_runs`: 開始したstageごとに終了時に1行INSERTする。token・費用・reuse列はStep 3用で、後から列を追加しないためにNULL許容で先に用意している
- `result_versions`: 1文書の抽出結果1回分。現行結果テーブルに書いた行そのものをJSON（`payload`）で持ち、作ったrunのIDを `run_ids` に持つ。更新・削除しない
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
- `extractor_version`: 抽出器の論理版はまだ管理していないため、`code_commit` と同じ値を明示的に保存する（reuse keyの値は仕様の代替規則と同じになる）
- `code_commit`: `CODE_COMMIT` → `git rev-parse HEAD` の順で取得する。build manifestと `artifact-sha256:` は、本番の反映方法を確認してから実装する

## Step 1で記録しない項目

- `generation_config`: `{}` で記録する。LLM関数内の設定には `response_schema` などJSON化できない値が含まれ、呼び出し側へ写すとずれるため、Step 3でLLM関数から返す形にする
- token・費用・request ID: Step 3で対応する

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
- `--force`（reuseせず新runを作る指定）はStep 3のreuseと合わせて扱う。現状のRERUNは常に新runを作る
