# buyback_analysis TDnet原典・抽出run履歴 実装報告（tdnet-provenance-v1）

報告日: 2026-11-08  
報告元: `C:\apps\buyback_analysis`  
宛先: `C:\apps\ir-analytics-platform`  
対象仕様: `docs/plans/handoffs/buyback-analysis-tdnet-provenance.md`（第2版。本リポジトリの写し: `docs/upstream/tdnet-provenance/`）

状態: **Step 1〜3を実装・テスト済み、レビュー承認済み。mainへの統合・push・本番適用は未実施。代表URLの実データ証拠は未取得。**

## 1. 変更ファイルと設計判断

### 1.1 変更ファイル

`main..fb751e7`: 78ファイル（+5,005 / −323）。うちテスト27ファイル。

| 区分 | ファイル |
|---|---|
| 新規パッケージ | `tdnet_provenance/`（models: `tdnet_source_document`・`processing_run`・`result_version`・`result_adoption`・`run_output`／usecase: `source_identity`・`resolve_verified_source`・`prepare_pdf_input`・`provenance_recorder`・`adopt_result`・`aggregate_usage`・`code_version`・`migrate_provenance_tables`） |
| 新規スクリプト | `scripts/migrate_tdnet_provenance_tables.py`・`scripts/report_llm_usage.py` |
| 中計 | `midterm_plan_analysis/main.py`・`backfill_keywords.py`、`usecase/run_midterm_stages.py`（新規）・`save_midterm_result.py`（新規）・`post_midterm_plan.py`・`post_midterm_keywords.py`・`extract_midterm_keywords(_native).py` |
| 会社予想修正 | `forecast_revision_analysis/main.py`、`usecase/run_forecast_revision_stages.py`（新規）・`save_forecast_result.py`（新規）・`post_forecast_revision.py`・`extract_forecast_revision_stage1(_native).py`・`infer_forecast_revision_stage2.py` |
| 共用 | `buyback_analysis/usecase/get_pdf_path.py`・`get_pdf_data.py`・`parse_text_by_llm.py`・`parse_pdf_by_llm.py`・`classify_midterm_by_llm.py`、`buyback_analysis/interface/llm_usage.py`（新規） |
| 仕様外の追加（§1.3） | `buyback_analysis/main.py`・`usecase/buyback_result_writer.py`（新規）・`post_data.py`、`earnings_baseline_analysis/main.py`・`usecase/save_earnings_result.py`（新規）・`post_earnings_baseline.py` |
| 文書 | `docs/tdnet_provenance_design.md`（設計の正本）・`docs/db-migration.md`・`CLAUDE.md` |

### 1.2 設計判断

すべて `TDNET_PROVENANCE_ENABLED=true` のときだけ有効になる（既定は `false` で従来動作）。新テーブルは専用の `ProvenanceBase` に置き、パイプライン起動時の `init_db()` では作成されない。

| 項目 | 判断 |
|---|---|
| 原典照合 | 共通検証関数 `attach_verified_tdnet_source` と同じ規則を本リポジトリで実装した（依頼元パッケージはimportしない）。運用原典台帳 `tdnet_source_documents` は初回取得時に1回だけ登録し、更新しない。抽出run開始前に、永続化済みの台帳行から `storage_uri` を解決し、再hashして照合する。照合済みパスだけをnative/text両方式のLLM入力に使い、パスは `input_hash` に含めない |
| 台帳と実ファイルの不一致 | PDFが消えていれば `source_missing` で停止する（自動再取得しない）。同じbytesに戻せば再開できる。hashが違えば `source_conflict` で停止し、台帳は書き換えない |
| PDF保存 | 一時ファイルに書いてから置き換える（書き込み途中の失敗で壊れたPDFが残らない） |
| `processing_runs` の作成時期 | 仕様ではStep 2だが、Step 1の受入条件「runがhashを持つ」を満たすためStep 1で作成した。Step 3用の列も最初から持たせ、後から列を追加しない |
| `source_document_id` | `uuid5(TDNET_NAMESPACE, "tdnet:<文書ID>")`（`ir_analytics_contract.tdnet` と同じ） |
| `input_locator` | PDF照合後のrunは `storage_uri`、PDF取得前に終わるrunはURL |
| `published_at` | TDnetの `date`＋`time` をJST（`+09:00`）として記録する。`time` を解釈できなければNULL |
| `code_commit` | `CODE_COMMIT`（40桁）→ `git rev-parse HEAD` の順に解決する。どちらも取れなければ起動時に停止し、`unknown` は使わない。build manifestと `artifact-sha256:` は未実装（§8） |
| 判断run | 会社予想のタイトルによる取り下げ判定を `run_kind=route`・`stage=eligibility`・`outcome=withdrawn`・`outcome_reason=title_keyword:<一致語>` で記録する。中計の `withdrawn`/`postponed`/`no_targets` はmetrics・classificationのLLMの後に決まるため、判断runにはしない（仕様 §4.5のとおり） |
| versioned結果（Step 2） | `result_versions`（1文書の抽出結果1回分。現行結果テーブルに書いた行そのものをJSONで持ち、作成したrunのIDを `run_ids` に持つ）と、追記専用の `result_adoptions` に分けた。版テーブルを現行テーブルの列構成と揃える方式は、列変更のたびに二重のmigrationが要るため採らなかった |
| 採用切替 | 「旧行の退避 → 現行行の置換 → 版の追記 → 採用の追記 → commit」を1トランザクションで行う。失敗すればrollbackし、旧採用を維持する |
| Step 2より前の結果 | 初めて置き換える時点で、現行行を `origin=legacy` の版として退避する（runとhashは持たない）。採用時刻は分からないため、legacy版の採用行は作らない |
| failedの扱い | 新しい抽出が失敗した場合、現行行があれば何も書かない（旧採用を維持）。現行行がなければ、従来どおり現行テーブルにfailed行を書く（会社予想の失敗再試行と中計の処理済み判定がこの行を使うため）。failed行は版にしない |
| retry | 現行結果がfailedのURLを再処理するとき、直近のfailed runを今回最初のrunの `retry_of_run_id` に入れる |
| reuse（Step 3） | 成功runの出力を `run_outputs` に保存し、reuse keyが一致すればLLMを呼ばず `status=reused`・`reused_run_id` を記録する（token・費用は0）。reuse keyは `ir_analytics_contract.processing.RunSpec.reuse_key()` と同じ正規化で計算する |
| `extractor_version` | LLM関数モジュールごとの `EXTRACTOR_VERSION`（例: `forecast_revision_stage1:1`）。出力の解析処理を変えたら手で上げる運用とし、CLAUDE.mdに明記した（`code_commit` にすると、commitのたびにreuseが効かなくなるため）。判断runと原典失敗runは `code_commit` |
| `generation_config` | LLM関数モジュールの定数 `GENERATION_CONFIG` を、Gemini呼び出しと記録の両方で使う。Pydanticのスキーマは、クラス名とJSON Schemaのhashとして記録する |
| force（仕様 §5.1） | `RERUN_URLS` の指定がforceにあたる。既定では再利用せず全stageを呼び直す（誤抽出の修正に使えるようにするため）。`RERUN_ALLOW_REUSE=true` のときだけ、条件が同じstageを再利用する。RERUNは版テーブルを使うため、`TDNET_PROVENANCE_ENABLED=true` が必要（無効なら起動時に停止） |
| token・request ID | LLM関数の戻り値は変えず、呼び出し直後の `report_llm_response()` で受け取る。`output_tokens` は回答token＋思考tokenの合計。関数内のリトライで成功応答が複数あれば合計し、request IDは最後の応答のもの。例外で終わった呼び出しも、それまでの使用量を失敗runに記録する |
| 費用 | `LLM_PRICE_INPUT_PER_1M_TOKENS`・`LLM_PRICE_OUTPUT_PER_1M_TOKENS`・`LLM_PRICE_CURRENCY` の3つを指定したときだけ計算する（単価はコードに持たない）。文書単位の集計は `aggregate_document_usage()` と `scripts/report_llm_usage.py` |
| PostgreSQL | 新テーブルは同期対象に含めない（`buyback_app` の同期allowlist化が前提。§2） |

### 1.3 仕様外で追加した範囲

自己株買い・業績ベースラインのパイプラインも `RERUN_URLS` で旧結果を先に削除していたため、本リポジトリの判断で、RERUN時の保存だけ同じ採用切替を使うようにした。台帳照合とrun記録は行わない。この2つの版は `run_ids=[]`・`origin=unrecorded` になる。統合時に、run・hashを持たない版として扱ってほしい。

## 2. migration・backup・restore

前提: **`buyback_app` の同期allowlist化（`buyback-app-data-transport-history-exclusion.md`）が受入完了するまで、本番SQLiteへ実行しない。** 現行の同期処理は `bk_` 以外の全テーブルをPostgreSQLへ自動コピーするため。

```powershell
.\.venv\Scripts\python.exe scripts\migrate_tdnet_provenance_tables.py
```

1. 全テーブルの行数と全行の内容hashを取得する
2. SQLiteのオンラインバックアップ（`<db>.bak-provenance-<日時>`）を作成する
3. 不足しているテーブルだけを作成する（同名テーブルの列集合が異なれば、何も作らずに停止する）
4. 新テーブルの列・NULL許容・主キー・索引を検証する
5. 参照切れを検証する（版のないadoption、runのない出力、再利用元・再試行元のないrun）
6. 既存テーブルの行数と全行hashが変わっていないことを検証する（変わっていれば異常終了し、復元を促す）

再実行しても冪等（不足分だけを作成する）。復元はパイプライン停止中に次を実行する。

```powershell
.\.venv\Scripts\python.exe scripts\migrate_tdnet_provenance_tables.py --restore <バックアップファイル>
```

一時SQLiteで、初回実行・再実行・復元を確認済み。本番DBでは未実行。

## 3. schema差分

既存テーブルの列・主キーは変更していない。追加するのは次の5テーブル（SQLiteのみ）。

| テーブル | 主キー | 主な列 |
|---|---|---|
| `tdnet_source_documents` | `url` | `source_document_id`（unique）、`external_document_id`、`disclosure_date`、`published_at`、`storage_uri`、`source_hash`、`file_size`、`fetched_at`（新規取得時のみ）、`observed_at` |
| `processing_runs` | `run_id` | `url`、`source_document_id`、`input_locator`、`source_hash`、`input_hash`、`run_kind`、`stage`、`code_commit`、`extractor_version`、`prompt_name`/`prompt_hash`、`model_provider`/`model_name`、`generation_config`、`reuse_key`、`status`（succeeded/failed/reused）、`outcome`/`outcome_reason`、`started_at`/`completed_at`、`retry_of_run_id`、`reused_run_id`、`provider_request_id`、`input_tokens`/`output_tokens`、`estimated_cost`/`estimated_cost_currency`、`error_code`。索引: `url`、`reuse_key` |
| `run_outputs` | `run_id` | `output`（JSON）、`created_at` |
| `result_versions` | `version_id` | `url`、`code`、`result_type`（midterm_plan/forecast_revision/buyback/earnings_baseline）、`extraction_status`、`payload`（JSON）、`run_ids`（JSON）、`origin`（run/legacy/unrecorded）、`created_at`。索引: `(url, result_type)` |
| `result_adoptions` | `adoption_id` | `url`、`result_type`、`version_id`、`adopted_at`。索引: `(url, result_type, adopted_at)` |

いずれも追記専用（アプリケーションはUPDATE・DELETEしない）。SQLiteの外部キーは使わず、参照整合性はmigrationの事後検証で確認する。

## 4. テスト

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

- 結果: **540 passed**（実LLM・本番DB・実PDFのダウンロードは使わない）
- 新規・変更したusecaseのカバレッジ: 98%（`tdnet_provenance/`・`llm_usage.py`・各パイプラインの `run_*`/`save_*`・`buyback_result_writer.py`）
- `main.py` 自体は既存方針どおりユニットテストの対象外。配線はusecase関数に切り出してテストした。加えて、PostgreSQL・Gemini・HTTPをモックし、本物の保存関数と一時SQLiteで各 `main.py` を通すスモークテストを行った（スクリプトはリポジトリ外）

主な検証内容:

| 対象 | 検証 |
|---|---|
| 原典 | 文書IDの日付と公表日が違っても公表日フォルダを使う／既知bytesのSHA-256／native・textとも照合済みパスをLLMへ渡す／URL・文書ID・保存URI・hashの不一致を拒否する／登録済みURLは再ダウンロードせず毎回再hashする／消失・同一bytesでの復元・別bytesの拒否 |
| 判断run | `withdrawn` では判断runだけが残り、LLMと未開始stageのrunは作られない／`status` と `outcome` を独立に保存する |
| 履歴 | 旧結果がlegacy版として残る／新runの失敗時に旧採用が残る／書き込み途中の失敗でrollbackされる／Stage1成功・Stage2失敗が別runになる／run保存失敗時に抽出結果を保存しない |
| migration | 空DB・既存DBへの適用／2回実行／既存行の全行hash不変／schema・索引・NULL許容の差異検出／参照切れ検出／バックアップからの復元 |

## 5. 代表URLの接続証拠

**未取得。** 本番相当のデータでmigrationとフラグ有効化を行った後に取得する。取得時は、1件のURLについて次を示す。

- `tdnet_source_documents` の行（`storage_uri`・`source_hash`）
- 同じ `source_hash` を持つ `processing_runs`
- `result_versions.run_ids` から辿ったrunと版の `payload`
- `result_adoptions` の現在の採用
- 現行結果テーブルの値が、採用中の版の `payload` と一致すること

モックを使ったスモークテストでは、この接続（台帳 → run → 版 → 採用 → 現行テーブル）を確認済み。

## 6. force・retry・reuseの結果

| 区分 | テスト | 結果 |
|---|---|---|
| force | `RERUN_URLS` の指定時は、同じ条件の成功runがあってもLLMを呼び直す（`test_rerun_with_same_conditions_calls_llm_again`）／環境変数の組み合わせでforceが決まる（`test_from_env_force_follows_rerun`、5パターン）／RERUNで旧run・旧結果が残る（`test_rerun_preserves_existing_rows_as_legacy_version` ほか） | 合格 |
| retry | 最初のrunだけが直近のfailed runを参照し、failed runは残る（`test_retry_links_first_run_to_latest_failed_run`）／retryの最初のrunは再利用しない（`test_first_run_of_retry_does_not_reuse`）／failed行の再試行成功時はlegacy退避をしない | 合格 |
| reuse | 同じreuse keyならLLMを呼ばず `reused`・token 0・費用0で記録する（`test_same_conditions_reuse_without_calling_llm`）／`extractor_version`・プロンプト・入力・生成設定・`source_hash` のどれかが変われば呼び直す（5パターン）／失敗runは再利用しない／reuse keyが共通契約の算出方法と一致する | 合格 |

スモークテストでは、同じ条件のRERUNでLLMを4回とも呼び直し、`RERUN_ALLOW_REUSE=true` では4 stageとも再利用（LLM呼び出し0回）になることを確認した。

## 7. commit・push・本番適用

| 項目 | 状態 |
|---|---|
| ブランチ | `docs/tdnet-provenance-handoff`（mainから分岐、main未統合） |
| commit | `a915cd6` 仕様の写し／`27a82d4` Step 1／`625fa34` Step 1レビュー対応／`7222939` Step 2／`e180399` 自己株買い・業績ベースラインのRERUN／`797b23b` Step 3／`fb751e7` Step 3レビュー対応 |
| push | なし |
| 本番migration | 未実施 |
| フラグ有効化・実LLM実行 | 未実施 |

## 8. 未解決事項と次に判断が必要な条件

1. **本番migrationの前提**: `buyback_app` の同期allowlist化の受入完了（依頼元が管理する引継ぎ）
2. **`code_commit` の取得方法**: 本番の反映方法がGit checkoutかを、デプロイ前に確認する。Git checkoutでなければ `CODE_COMMIT` を配布処理で設定する。build manifest・`artifact-sha256:` は、必要になった時点で実装する
3. **代表URLの証拠**（§5）: migrationとフラグ有効化の後に取得する
4. **費用の単価**: 未設定。設定するまで、費用はNULL（token数のみ記録）
5. **統合側の読み取り経路**: 新テーブルはSQLiteにのみ存在し、PostgreSQLへはコピーされない。ir-analytics-platformが履歴を読む場合は、SQLiteから直接読むのか、`buyback_app` 向けにrun IDをキーとした追記同期を別途仕様化するのかの判断が必要
6. **仕様外の追加範囲の扱い**（§1.3）: 自己株買い・業績ベースラインの `origin=unrecorded` の版を、統合でどう扱うか
7. **既存データ**: 仕様どおりhashのbackfillはしていない。Step 2より前の結果は、RERUNで初めて置き換えるときに `origin=legacy` として退避される。それまでは現行テーブルにだけ存在する
