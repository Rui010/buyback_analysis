## カラムの追加

- `announcements` テーブルにTEXT型の `status` カラムを追加
- `announcements` テーブルにTEXT型の `resolution_date` カラムを追加
- `completion` テーブルにTEXT型の `resolution_date` カラムを追加

## テーブルの追加

```
CREATE TABLE IF NOT EXISTS corrections (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL,
    url TEXT,
    company_name TEXT NOT NULL,
    disclosure_date TEXT NOT NULL,
    original_announcement_date TEXT NOT NULL,
    document_title TEXT NOT NULL,
    correction_reason TEXT,
    corrections TEXT NOT NULL
);
```

## 2026-09-26: 自己株買いテーブルのURL主キー化

対象は `announcements`、`completion`、`progress`、`retirements`。各テーブルの
主キーを既存の `url` 列単独へ変更し、`code` と `disclosure_date` は
`NOT NULL` のインデックス列にする。これにより同一銘柄・同一開示日の複数開示を
それぞれ保存できる。カラム集合は変わらないため、`infra/data_transport.py` の
全置換同期は変更不要。

SQLiteは既存テーブルの主キーをALTERできないため、以下で移行する。

```powershell
.\.venv\Scripts\python.exe scripts\migrate_buyback_url_primary_keys.py
```

スクリプトは対象表ごとに `bk_<table>` へ退避、モデル定義で新表を作成、全列を
コピー、退避表を削除する。開始前にURLのNULL・空文字・テーブル内重複と既存の
`bk_` 退避表を検査し、問題があれば変更せず停止する。SQLiteトランザクション内で
実行するため、途中失敗時はロールバックされる。

あわせて旧DBの `is_checked` に `parse_status` がない場合は、既存行を `saved` として
同列を追加し、URL一意索引 `uq_is_checked_url` を作成する。これも現行パイプラインが
前提とする既存モデルとの整合化であり、URL重複が検出された場合は変更せず停止する。

## 2026-11-03: 中期経営計画の計画期間表記

`midterm_plans` に次のnullable文字列カラムを追加する。

- `plan_start_period_label`
- `plan_end_period_label`
- `plan_start_fiscal_end`
- `plan_end_fiscal_end`

既存SQLiteへは次を1回実行する。

```powershell
.\.venv\Scripts\python.exe scripts\migrate_midterm_plan_period_fields.py
```

実行前にSQLiteオンラインバックアップを同じディレクトリへ自動作成する。不足列だけを追加する再実行可能な処理で、既存行を変更せず、過去データのバックフィルも行わない。

## 2026-11-08: TDnet原典台帳・processing run

`tdnet_source_documents` と `processing_runs` を新規作成する（既存テーブルは変更しない）。設計は `docs/tdnet_provenance_design.md` を参照。

**buyback_appの同期allowlist化が受入完了するまで、本番SQLiteへ実行しない。** 現行の同期処理は `bk_` 以外の全テーブルをPostgreSQLへ自動コピーするため。

```powershell
.\.venv\Scripts\python.exe scripts\migrate_tdnet_provenance_tables.py
```

実行前にSQLiteオンラインバックアップ（`<db>.bak-provenance-<日時>`）を同じディレクトリへ作成し、前後で全テーブルの行数を表示する。既存テーブルの行数が変わった場合は異常終了する。不足テーブルだけを作成する再実行可能な処理で、同名テーブルの列集合がモデルと異なる場合は何も作らずに停止する。

復元はパイプライン停止中に、バックアップファイルを元のDBファイル名へコピーして戻す。
