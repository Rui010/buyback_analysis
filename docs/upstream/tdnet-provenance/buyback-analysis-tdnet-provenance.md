# buyback_analysis向け TDnet原典・抽出run履歴 実装引継ぎ仕様

作成日: 2026-11-08  
依頼元: `C:\apps\ir-analytics-platform`  
実装先: `C:\apps\buyback_analysis`  
契約版: `tdnet-provenance-v1`

## 1. 目的

中計・会社予想修正の新規抽出について、抽出値を実際に入力したTDnet PDFへSHA-256で遡れるようにする。あわせて、再抽出時に旧結果を削除せず、同一入力・同一処理条件の成功結果を再利用できる追記型run履歴を整備する。

本書は`buyback_analysis`側へ渡す実装仕様である。依頼元リポジトリは共通契約、検証関数、受入条件を所有し、実装先リポジトリのコード、SQLite、運用ジョブ、デプロイは変更しない。

本書の作業分担は[リポジトリ所有境界と引継ぎルール](../repository-boundaries.md)に従う。

## 2. 所有境界

| 項目 | 所有者 |
|---|---|
| PDF取得・保存、運用原典台帳、テキスト化、LLM呼び出し | `buyback_analysis` |
| SQLite migration、バックアップ、復元手順 | `buyback_analysis` |
| 中計・会社予想の抽出結果とrun履歴 | `buyback_analysis` |
| 共通データ契約、TDnet台帳の項目・照合規則、受入検証 | `ir-analytics-platform` |
| 複数システムの統合時系列、as-of検索 | `ir-analytics-platform` |

実装先から依頼元パッケージを直接importすることは必須としない。依存を増やさず同じ契約を実装してよい。ただし、出力項目と受入条件は本書に一致させる。

## 3. 現状と解決する問題

現在は`get_pdf_path()`が`<PDF_DOWNLOAD_PATH>/<公表日>/<ファイル名>`へPDFを保存し、既存ファイルがあれば再利用する。nativeモードは保存パスを、textモードは同じPDFから抽出した文字列をLLMへ渡す。

一方、`midterm_plans`と`forecast_revision_details`には`source_hash`、`storage_uri`、run IDがない。さらに`RERUN_URLS`は既存行を処理前に削除する。このため、次を証明・再現できない。

- どのPDFバイト列をLLMへ渡したか
- 同じURLの保存ファイルが後から変わっていないか
- どのコード、プロンプト、モデルで抽出したか
- 再抽出前の結果と採用期間
- 同一条件の成功runを再利用できたか

## 4. 実装範囲

### 4.1 必須: 原典確定をLLM呼び出しより先に行う

中計・会社予想の両経路を次の順序へ統一する。

1. TDnet行から`url`、`date`、`time`、`code`を取得する。
2. `get_pdf_path()`で保存済みPDFを取得または新規保存する。
3. 初回取得時は保存PDFをバイナリで読み、SHA-256を計算し、URL、文書ID、保存URI、SHA-256を不変の運用原典台帳へ登録する。
4. 抽出run開始時は保存済みの台帳行を読み、`storage_uri`から解決した実ファイルを再hashして台帳値と照合する。抽出runのたびに台帳行を作り直してはならない。
5. 台帳照合に成功した同じPDFをnative処理またはテキスト抽出へ渡す。
6. runと抽出値を保存する。

textモードでも、先にPDFパスを確定してからテキスト化する。URLから別途再ダウンロードしてはならない。

初回取得時のhash登録は、外部の独立した正解値との照合ではなく、取得したbyte列の基準値を固定する処理である。照合の目的は、その後の抽出・再抽出までに保存PDFが差し替わっていないことを検知することにある。既存PDFを初めて台帳へ登録する場合は、登録時の`observed_at`以降の基準値として扱い、過去の取得時点まで検証済みとはみなさない。

運用原典台帳とPDF実体は、取得処理を所有する`buyback_analysis`が保持する。`ir-analytics-platform`は台帳の項目、照合規則、共通検証関数、統合用readerを保持する。共通検証関数へ渡す`registry_entry`は、抽出run内で実ファイルから都度組み立てた値ではなく、先に永続化された運用原典台帳の行でなければならない。

### 4.2 TDnet原典識別規則

- 文書ID: URL path末尾の`.pdf`を除いた文字列
- 保存フォルダ: TDnetの公表日`date`を`YYYYMMDD`へ変換したもの
- ファイル名: `<文書ID>.pdf`
- `storage_uri`: `tdnet-pdf://<公表日YYYYMMDD>/<文書ID>.pdf`
- `source_hash`: PDF全バイトの小文字64桁SHA-256。`sha256:`接頭辞は付けない

文書IDに含まれる日付を保存フォルダに使ってはならない。文書IDが`20260218`を含んでも、公表日が2026-02-19なら`tdnet-pdf://20260219/...`とする。

### 4.3 必須: source document相当の保存項目

最低限、各新規抽出runから次へ遡れるようにする。

| 項目 | 必須 | 内容 |
|---|---|---|
| `url` | 必須 | TDnet公開URL |
| `external_document_id` | 必須 | URLから得た文書ID |
| `disclosure_date` | 必須 | TDnet公表日 |
| `published_at` | 可能なら必須 | TDnet `date + time`、UTC offset付き |
| `source_hash` | 必須 | PDF SHA-256 |
| `storage_uri` | 必須 | 論理保存URI |
| `fetched_at` | 新規取得時必須 | URL単位の取得完了時刻、UTC offset付き |
| `file_size` | 推奨 | 保存PDFのbyte数 |

既存ファイル再利用時は、過去の正確な取得時刻を推測しない。`fetched_at=null`または別の`observed_at`として記録し、新規ダウンロードの取得時刻と区別する。

### 4.4 必須: `processing_runs`を追記保存する

中計metrics、中計keywords、中計分類、会社予想stage1、会社予想stage2は、結果や費用を区別できるstageとして保存する。

| 項目 | 必須 | 内容 |
|---|---|---|
| `run_id` | 必須 | UUID等の不変ID |
| `url`または`source_document_id` | 必須 | 処理対象原典 |
| `source_hash` | 抽出run時必須 | 原典PDF hash。PDF取得前に完了するeligibility runではNULL可 |
| `input_hash` | 必須 | PDF以外の機械入力を含む正規化hash |
| `run_kind` | 必須 | `extract`等 |
| `stage` | 必須 | `eligibility`、`metrics`、`keywords`、`classification`、`stage1`、`stage2` |
| `code_commit` | 必須 | 実行コードを一意に識別するversion。原則Git commit |
| `extractor_version` | 必須 | 抽出器の論理版 |
| `prompt_name` / `prompt_hash` | LLM時必須 | 使用プロンプト |
| `model_provider` / `model_name` | LLM時必須 | 使用モデル |
| `generation_config` | 任意 | temperature等 |
| `reuse_key` | 必須 | 再利用条件の正規化hash |
| `status` | 必須 | `running` / `succeeded` / `failed` / `reused` |
| `outcome` | 判断run時必須 | `withdrawn` / `skipped`等の業務上の判断結果 |
| `outcome_reason` | 判断run時必須 | 機械判定可能な判断理由 |
| `started_at` / `completed_at` | 必須 | UTC offset付き |
| `retry_of_run_id` | retry時必須 | 再試行元 |
| `reused_run_id` | reuse時必須 | 再利用元の成功run |
| token・費用・request ID | 取得可能なら必須 | stage別の実績 |
| `error_code` | 失敗時推奨 | `429`等 |

runはINSERTのみとする。既存runの内容を更新・削除しない。`running`から終端状態への遷移を同じ行で許す場合も、結果や処理条件の上書きには使わない。

`code_commit`は次の優先順位で決定する。

1. デプロイ時に環境変数またはbuild manifestへ注入したGit commit ID
2. Git checkout環境の`git rev-parse HEAD`
3. Git情報を含まない配布物について、build manifestに保存されたGit commit ID
4. commit IDを取得できない暫定配布物だけ、`artifact-sha256:<成果物hash>`

`unknown`、実行日時、サーバー名など、同じコードを安定して識別できない値を設定してはならない。`artifact-sha256:`を使用した場合もreuse keyへ含め、Git commitと値の種類を区別できるようにする。

実装する取得関数は、明示的に注入された`CODE_COMMIT`、Git checkoutから取得したHEAD、build manifest、artifact hashの順で解決する。過去の運用ではサーバーでGit pullした報告があるが、現在の本番反映方法は未検証である。Step 1のデプロイ前確認で本番実体がGit checkoutかを確認し、Git checkoutならHEAD取得を使用する。ファイル配布なら配布処理から`CODE_COMMIT`またはbuild manifestを必ず注入する。反映方法の違いを理由にrun記録を省略しない。

### 4.5 必須: LLMを呼ばない判断経路を監査可能にする

タイトルからLLM前に確定する会社予想の`withdrawn`など、LLMを呼ばずに処理を終了する場合も、その判断を行ったrunを保存する。

- 例: `run_kind=route`、`stage=eligibility`
- 処理自体が正常に判断を完了した場合は`status=succeeded`
- 業務上の判断結果を`outcome=withdrawn`等へ保存する
- `outcome_reason`へ機械判定可能な理由を保存する
- prompt、model、request IDはNULL、tokenと費用はNULLまたは0とする
- 実際に開始しなかった`metrics`、`keywords`、`classification`、`stage1`、`stage2`のrunは作らない
- PDF取得前のタイトル判定で完了するeligibility runは、`source_document_id`と`source_hash`をNULLにし、TDnet行を特定する`input_locator`と正規化した`input_hash`を必須とする

処理の成否を表す`status`と、業務上の判断を表す`outcome`を混同しない。PDF取得・読取・hash照合など、開始した処理が失敗した場合は、その開始済みrunを`status=failed`として残す。

現行の中計経路では、metrics LLMの後にタイトルで`withdrawn` / `postponed`を判定し、該当しなければ分類LLMが`withdrawn` / `no_targets` / `postponed`を返す。現行コードに中計の`skipped`を新規生成する経路はない。このため、これらを「LLMを呼ばなかったeligibility run」として記録してはならず、実際に実行したmetrics・classification runとその結果を保存する。将来LLM前の明示的な対象外判定を追加した場合だけ、その判定をeligibility runとして記録する。

### 4.6 必須: 抽出結果とrunを接続する

新規の中計・会社予想抽出結果は、生成した`run_id`を保持する。実装には別のversioned result/observationテーブルを使用し、現行結果テーブルへの`run_id`追加だけで済ませない。現在の採用versionはadoptionテーブルまたはcurrent pointerで明示する。

ただし、現行の`(code, url)`主キーだけで新旧結果を区別する設計は不可とする。少なくとも同一URLに複数runの結果を保持できなければならない。

## 5. RERUN・retry・reuse規則

### 5.1 RERUN

現行のdelete-before-extractを廃止する。

- RERUN開始時に`midterm_plans`、`midterm_plan_keywords`、`forecast_revision_details`、`forecast_revision_metrics`の旧結果を削除しない。
- 新runと新抽出結果を追加する。
- 新runが成功してから採用版を切り替える。
- 新runが失敗した場合、旧採用版を維持する。
- `--force`は削除指定ではなく「reuseせず新runを作る」指定とする。

### 5.2 retry

- failed runを削除しない。
- 新runの`retry_of_run_id`に失敗runを設定する。
- retry成功後も失敗runとエラー内容を残す。

### 5.3 reuse

次の正規化値がすべて一致する成功runがあれば、原則としてLLMを呼ばない。

```text
source_hash
input_hash
run_kind
stage
extractor_version（なければcode_commit）
prompt_hash
model_provider
model_name
generation_config
```

新しいrunを`status=reused`で作り、`reused_run_id`に元の成功runを記録する。再利用時のtoken・費用を新規LLM実行として計上しない。

## 6. 段階的な実装単位

### Step 1: 原典hash記録

- PDF取得後、LLM前のSHA-256計算
- `storage_uri`生成
- 共通検証関数へ`pdf_root`を渡し、`storage_uri`から解決した実ファイルをrunごとに再hashして台帳値と照合
- 共通検証関数がmetadataと分離して返す`resolved_path`をnative/text両経路のLLM入力にそのまま使用し、別経路でパスを再構築しない。絶対パスはmetadataや`input_hash`へ含めない
- source document相当の保存
- 中計・会社予想runへの`source_hash`記録
- native/textが同じPDFを使用するテスト

このStepでは過去行をbackfillしない。既存データは`legacy-unverified:<文書ID>`相当として扱う。

### Step 2: 追記型run・結果保存

- `processing_runs`追加
- 現行結果テーブルへ`run_id`だけを追加する方式ではなく、別のversioned result/observationテーブルでrunごとの抽出結果を不変に保持する
- 現行結果テーブルは当面の互換用・現行採用値として扱い、versionedテーブルと混同しない
- adoptionテーブルまたはcurrent pointerにより現在の採用versionを明示する
- delete-before-extract廃止
- 成功後の採用切替
- retry関係の保存

Step 2の設計は上記の「別versionedテーブル＋adoption方式」に固定する。レビュー間でA案/B案の呼称が逆転していたため、以後はA/Bの記号を仕様上の名称として使用しない。現行の`(code, url)`中心の主キーへ`run_id`を追加するだけの方式は、同一URLの複数run結果と採用期間を安全に保持できないため採用しない。新runが成功した場合だけ採用versionを切り替え、失敗時は旧採用versionを維持する。

### Step 3: reuse・費用監査

- reuse key実装
- 成功run再利用
- stage別token・費用・request ID保存
- 文書単位の費用集計

Stepごとに独立コミットとし、Step 1完了を理由にRERUN履歴問題まで解決済みとは報告しない。

## 7. migration要件

- 本番SQLite変更前にオンラインバックアップを作る。
- migrationは不足列・不足テーブルだけを追加する冪等処理にする。
- `Base.metadata.create_all()`で既存テーブルへ列が追加されると仮定しない。
- migration前後で対象テーブルのschema、行数、代表URLの値を読み取り確認する。
- 既存行へ後日計算したhashを一括設定しない。抽出時のファイル同一性を証明できないためである。
- Step 2では、versioned run・結果テーブルを`buyback_analysis`のSQLiteへ実装し、既存のPostgreSQLコピー対象へ自動的に含めない。
- 現行の`buyback_app/backend/infra/data_transport.py`は、`bk_`で始まるテーブル以外のSQLite全テーブルを列挙し、PostgreSQL側に存在しなければ`buyback_<table>`を自動作成する。このままでは新しい履歴テーブルも自動的にコピーされるため、最初の本番新規テーブルmigrationより前に[buyback_app向け同期除外仕様](buyback-app-data-transport-history-exclusion.md)を適用する。Step 1のコード・migration・テスト作成は先行してよいが、本番SQLiteへのmigration適用は同期除外の受入完了まで行わない。
- PostgreSQLで履歴を利用する要件が発生した場合は、`buyback_app`向けに別途、run IDをキーにした追記同期を設計する。
- `TRUNCATE + APPEND`による現行状態コピーを、versioned履歴の同期方式としてそのまま採用しない。

## 8. エラー時の動作

| 状態 | 動作 |
|---|---|
| PDF取得失敗 | failed runを保存し、LLMを呼ばない |
| PDF読取失敗 | failed runを保存し、LLMを呼ばない |
| SHA-256計算失敗 | failed runを保存し、未検証hashで続行しない |
| 台帳登録済みPDFが消失 | 自動的に台帳を更新せず停止する。同じURLから自動再取得して抽出を継続しない |
| 消失PDFを運用者が復元 | 復元byte列を再hashし、台帳hashと一致する場合だけ同じ原典として再開する |
| 再取得・復元PDFのhashが台帳と不一致 | 同じ原典の置換として扱わず`status=failed`、`error_code=source_conflict`で停止し、手動確認なしに新versionを追加しない |
| URLと文書ID不一致 | 契約エラー。LLMを呼ばない |
| `storage_uri`と文書ID不一致 | 契約エラー。LLMを呼ばない |
| 同一reuse keyの成功runあり | LLMを呼ばず`reused` |
| 会社予想の`withdrawn`をLLM前に確定 | 判断runを`succeeded`で保存し、`outcome`と理由を記録。未開始のLLM stage runは作らない |
| 新run保存失敗 | 旧採用を維持し、抽出結果だけを孤立保存しない |
| 新抽出失敗 | 旧採用を維持する |

## 9. 必須テスト

### 原典

- 文書IDの日付と公表日が異なっても、公表日フォルダを使う。
- 保存PDFの既知bytesから期待SHA-256を生成する。
- native/textの両経路でhash対象PDFとLLM入力PDFが同じである。
- URL、文書ID、保存URI、hash欠損・不一致を拒否する。
- 既存ファイル再利用時に再ダウンロードしないが、毎run hashを確認する。

### 履歴

- force再処理で旧run・旧結果が残る。
- 新run失敗時に旧採用が残る。
- retryが失敗runを参照し、両runが残る。
- 同一reuse keyではLLM executorを呼ばない。
- prompt、model、source hashのいずれかが変わればreuseしない。
- stage1成功・stage2失敗を別々に記録できる。
- 会社予想のタイトル判定`withdrawn`では判断runだけが残り、LLM executorと未開始stageのrunが作られない。
- 中計のmetrics・classification LLM後に決まった状態を、非LLM eligibility runとして誤記録しない。
- `status=succeeded`と`outcome=withdrawn`を独立して保存できる。
- 台帳登録済みPDFの消失、同一hashでの復元、異なるhashの拒否を検証できる。

### migration

- 空DBと既存DBの両方へ適用できる。
- 2回実行してもschema・データが壊れない。
- migration前後で既存行数と主要値が変わらない。
- backupから復元できる。

## 10. 受入条件

- [ ] 新規の中計・会社予想runが64桁SHA-256と`tdnet-pdf://` URIを持つ
- [ ] source document相当とprocessing runのhashが一致する
- [ ] hash対象PDFとLLM入力PDFが同一パスである
- [ ] 共通検証関数がmetadataと分離して返した`resolved_path`をLLM入力に使用し、保存先を変えても`input_hash`が変わらない
- [ ] 台帳作成後にPDFを差し替えると、run開始前の再hash照合で拒否される
- [ ] 抽出run内で実ファイルから台帳値を作り直さず、先に永続化された運用原典台帳を照合に使用する
- [ ] 台帳登録済みPDFが消失した場合は自動再取得で継続せず、同一hashの復元だけを許可する
- [ ] 異なるhashのPDFを同じ台帳行へ上書きせず、手動確認なしに新versionを追加しない
- [ ] 既存データを検証済みhashへ見せかけてbackfillしていない
- [ ] Git checkoutでない配布形態でも、注入されたcommit IDまたは`artifact-sha256:`でコード版を一意に識別できる
- [ ] RERUNで旧run・旧抽出値を削除しない
- [ ] 新run失敗時に旧採用を維持する
- [ ] versioned結果テーブルと採用versionが分離され、同一URLの複数run結果が残る
- [ ] LLMを呼ばない会社予想`withdrawn`の理由を判断runから監査できる
- [ ] 中計のLLM後の状態を非LLM判断runとして扱っていない
- [ ] 同一処理条件の成功runを再利用できる
- [ ] stage別の成功・失敗・retry・reuseを監査できる
- [ ] migrationが冪等で、事前バックアップと事後確認がある
- [ ] 実LLM呼び出しなしのテストで主要経路を検証できる

## 11. 対象外

- 既存全履歴へのhash backfill
- 既存run ID `0201`〜`0203`相当の書換え
- TDnetに存在するが共有へ未保存の107,471 URLの一括再取得
- 指標定義、期間、連結区分の推測補完
- `ir-analytics-platform`へのDB書込み
- 本番migration、サーバー反映、実LLM実行の自動承認

## 12. 実装先から返してほしい成果物

1. 変更ファイル一覧と設計判断
2. migrationスクリプトとbackup・restore手順
3. 新旧schema差分
4. テストコマンドと結果
5. 代表URL1件について、URL、storage URI、hash、run、抽出結果が接続できる証拠
6. force、retry、reuseのテスト結果
7. ローカルcommit ID、push有無、本番適用有無
8. 未解決事項と、次に判断が必要な条件

## 13. 参照

- [MVP最小データ契約](../../results/phase-0.5/mvp-contract.md)
- [Phase 1実装チケット](../../results/phase-0.5/phase-1-tickets.md)
- [TDnet PDF原典台帳と被覆率](../../results/tdnet-pdf-source-registry.md)
- 共通検証実装: `src/ir_analytics_contract/tdnet_sources.py`の`attach_verified_tdnet_source(tdnet_metadata, registry_entry, pdf_root)`。戻り値は`(verified_metadata, resolved_path)`とし、`resolved_path`は再hash済みでLLMへ渡すべき唯一のPDFパスだが、metadataや`input_hash`には含めない。
- 共通run契約実装: `src/ir_analytics_contract/processing.py`
