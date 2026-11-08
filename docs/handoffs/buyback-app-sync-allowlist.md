# buyback_app 作業指示: SQLite→PostgreSQL同期の対象をallowlistにする

作成日: 2026-11-08  
作業リポジトリ: `C:\apps\buyback_app`  
対象ファイル: `backend/infra/data_transport.py`（`python -m infra.data_transport`、毎日実行）  
元の仕様: `C:\apps\ir-analytics-platform\docs\plans\handoffs\buyback-app-data-transport-history-exclusion.md`

## 1. 目的

buyback_analysisのSQLiteに追加される履歴テーブル5つを、PostgreSQLへコピーしないようにする。今の同期処理は、未知のテーブルも自動でコピーしてしまう。

- `tdnet_source_documents`
- `processing_runs`
- `run_outputs`（LLMの出力全文が入る）
- `result_versions`
- `result_adoptions`

**この作業が本番に反映されるまで、buyback_analysis側のmigration（`scripts/migrate_tdnet_provenance_tables.py`）は実行できない。** それまでの間、buyback_analysisの全パイプラインで `RERUN_URLS` が使えない（RERUNは履歴テーブルを使うため）。

## 2. 現状（2026-11-08に確認）

`backend/infra/data_transport.py` の動作:

1. `sqlite_master` からSQLiteの全テーブルを列挙し、`bk_` で始まるものだけを除外する
2. 各テーブルについて、PostgreSQLに `buyback_<テーブル名>` がなければ `to_sql(..., if_exists="replace")` で新規作成する（`_sync_table` の `"created"`）
3. あれば列集合を比較し、一致すれば `TRUNCATE` してから `append` する。不一致なら通知してスキップする

このため、buyback_analysisが新しいテーブルを作ると、次回の同期でPostgreSQLにも自動的に作られてコピーされる。

## 3. 変更内容

### 3.1 同期対象を明示したallowlistにする

同期対象をコード内の定数で列挙し、それ以外は同期しない。denylistにはしない（今後増える履歴・運用テーブルを指定漏れでコピーしないため）。

allowlistは、現在PostgreSQLに `buyback_` として同期されているテーブル（`bk_` 由来を除く）と同じ、次の12個にする。buyback_analysisのモデル定義と一致することも確認済み。

```python
SYNC_TABLES = (
    # 自己株買い
    "announcements",
    "progress",
    "completion",
    "corrections",
    "retirements",
    "is_checked",
    # 中期経営計画
    "midterm_plans",
    "midterm_plan_keywords",
    # 業績予想修正
    "forecast_revision_details",
    "forecast_revision_metrics",
    # 業績ベースライン
    "earnings_baselines",
    "earnings_baseline_metrics",
)
```

### 3.2 テーブルの扱い

| SQLiteのテーブル | 動作 | 集計 |
|---|---|---|
| allowlistにあり、PostgreSQLにも `buyback_<table>` がある | 従来どおり、列集合が一致すれば `TRUNCATE`＋`append`、不一致なら通知してスキップ | `synced` / `skipped` |
| allowlistにあり、PostgreSQLにない | **自動作成しない**。通知してスキップする（§5の確認事項1） | `skipped` |
| allowlistにない（`bk_` で始まるものを含む） | 読み込まず、PostgreSQLにも触れない。テーブル名をログに出す | `excluded` |
| allowlistにあるが、SQLiteにない | 何もしない。警告ログを出す | `missing` |

- allowlist外のテーブルはエラーにしない（buyback_analysis側でテーブルが増えるのは正常な運用のため）
- 既存の `bk_` 除外は、allowlistにより不要になる。残しても害はない

### 3.3 完了通知

`notify_success` の本文に `excluded` と `missing` の件数を加え、除外したテーブル数を通知で確認できるようにする。例:

```
12テーブル中 12件同期（新規作成0件、スキップ0件）、対象外6件、SQLiteになし0件
```

`"created"`（新規作成）は自動作成をやめるため常に0になる。項目を残すか削るかは実装者の判断でよい。

## 4. テスト

`backend/tests/` に追加する（実PostgreSQLは使わない）。テーブル選別を純粋関数（例: `select_sync_tables(sqlite_tables) -> (sync, excluded, missing)`）に切り出すと、DBなしでテストできる。

必須:

- allowlist内のテーブルは同期対象になる
- allowlist外のテーブル（`processing_runs`・`run_outputs` など）と `bk_` テーブルは `excluded` になり、PostgreSQLへの作成・書き込みが呼ばれない
- allowlistにあってPostgreSQLにないテーブルは作成されず、スキップとして通知される
- 列が不一致のときに通知してスキップする、という既存の動作が変わらない
- 完了通知に `excluded` の件数が入る

`_sync_table` と `main()` は、`pd.read_sql`・`to_sql`・`get_database_engine`・`inspect`・`notify_*` をモックして検証できる。

## 5. 確認事項（実装前に判断してほしいこと）

1. **allowlistにあってPostgreSQLにないテーブルを自動作成するか**: 元の仕様は「PostgreSQL側に新しい `buyback_<table>` を自動作成しない」としているので、本指示書は作成しない側にしている。今後、同期したいテーブルを増やす場合は「allowlistに追加する＋PostgreSQLにテーブルを作る」の2手順になる。allowlistに明示したテーブルに限って自動作成を残す選択肢もある（allowlist外がコピーされない、という目的は満たせる）
2. **PostgreSQLに残っている古い退避テーブル**: `buyback_bk_forecast_revision_details_20260630`・`_20260702`、`buyback_bk_forecast_revision_metrics_20260630`・`_20260702`、`buyback_bk_midterm_plans_20260516`・`_20260522` の6つが残っている（`bk_` 除外が入る前にコピーされたものとみられる）。今回の対象外。削除するかは別途判断する

## 6. 適用順序

1. buyback_appで実装し、テストを通す
2. 運用ジョブに反映する
3. 反映後、SQLiteに未知のテスト用テーブルがある状態で同期を実行し、`excluded` になってPostgreSQLに作られないことを確認する（本番SQLiteにテスト用テーブルを作れない場合は、本番と同じ構成の別DBで確認する）
4. 確認できたら、buyback_analysis側にmigrationの実行を依頼する

## 7. 受入条件

- [ ] 同期対象がallowlistで管理され、allowlist外のテーブルは同期されない
- [ ] allowlist外のテーブルについて、PostgreSQLに `buyback_<table>` が作成されない
- [ ] allowlist内の12テーブルは、従来どおり `TRUNCATE`＋`append` で同期される
- [ ] 完了通知とログで、`excluded` の件数とテーブル名が確認できる
- [ ] §4の必須テストが通る
- [ ] 運用ジョブへの反映後、§6の手順3で確認済み

## 8. 返してほしい情報

- commit ID、push・運用ジョブへの反映の有無
- テスト結果
- §6の手順3の確認結果（同期ログまたは通知の内容）
- §5の確認事項1の判断
