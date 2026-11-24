# 自社株買い案件・イベント 下流提供契約

## 1. 位置づけ

`buyback_analysis`から`buyback_app`への提供境界である。上流設計は
[Phase 1](../buyback_plan_event_linking_design.md)を参照する。下流合意前に同期対象へ追加しない。

2026-11-23に、下流へは派生表`announcement_plan_status`1つだけを提供すると決定した
（方針B）。Phase 1の4テーブル（`buyback_plans`・`buyback_plan_projections`・
`buyback_events`・`buyback_event_link_decisions`）は同期しない。

## 2. 提供データ

| SQLite | PostgreSQL | 用途 |
|---|---|---|
| `announcement_plan_status` | `buyback_announcement_plan_status` | 発表文書URLごとの案件の現在状態（進捗・完了） |

| 列 | 型 | NULL | 内容 |
|---|---|---|---|
| `buyback_plan_id` | text | 不可（PK） | 案件ID。同期をまたいで不変 |
| `announcement_url` | text | 不可 | 発表文書URL。`buyback_announcements.url`との結合キー |
| `code` | text | 不可 | 証券コード |
| `plan_status` | text | 不可 | `planned` / `in_progress` / `completed` |
| `current_shares` | double precision | 可 | 現在の取得上限株数（変更反映後） |
| `current_amount_yen` | double precision | 可 | 現在の取得上限金額（円） |
| `current_start_date` / `current_end_date` | text（YYYY-MM-DD） | 可 | 現在の取得期間 |
| `cumulative_shares_acquired` | double precision | 可 | 進捗報告の累計取得株数 |
| `cumulative_amount_spent_yen` | double precision | 可 | 進捗報告の累計取得金額（円） |
| `completion_shares_acquired` | double precision | 可 | 完了時の最終取得株数 |
| `completion_amount_spent_yen` | double precision | 可 | 完了時の最終取得金額（円） |
| `progress_rate_amount` / `progress_rate_shares` | double precision | 可 | 累計 ÷ 現在の上限（0〜1の比率）。上限・累計のどちらかが欠けるか上限0ならNULL |
| `latest_progress_date` | text（YYYY-MM-DD） | 可 | 最新の進捗報告日 |
| `aggregation_rule_version` | text | 不可 | 集計ルール版 |
| `calculated_at` | timestamp（タイムゾーンなし） | 不可 | 案件の集計日時（UTC） |

型は既存の`buyback_*`テーブルに合わせる（数値は`double precision`、日付は`YYYY-MM-DD`の`text`）。
`calculated_at`はSQLiteからタイムゾーンなしのUTC文字列で届くため、PostgreSQLでは`timestamp`
（タイムゾーンなし）とし、UTCとして扱う（DBの`TimeZone`は`Asia/Tokyo`のため`timestamptz`にすると
9時間ずれる）。DDLは`stock-market-db`のAlembic revision `4efefc53e4b4`。

## 3. 利用規則

- 一覧は従来テーブル基準のまま、`buyback_announcements.url = announcement_url`で結合し、
  案件がある行にだけ進捗・完了を表示する。
- 同じ`announcement_url`が複数行ある場合（1文書から複数案件）は全行を表示する。
- 表に行がない発表は「案件状態なし」として扱い、進捗0%とは表示しない。
- 進捗率NULLは「計算できない」であり、0として扱わない。
- 上流は確定済み（publishable）の案件だけを入れる。未確定イベントは含まない。
- URL、案件ID、enum、単位、日付の意味を同期時に変更しない。

## 4. 上流の更新方法

- 自己株買いパイプラインの最後に毎回まるごと作り直す（1トランザクション）。
- 外部キーを持たないため、現行同期（allowlist・TRUNCATE + APPEND）で単独同期できる。
- 列の追加は後方互換で行い、既存列の意味・単位は変えない。

## 5. 下流で行う作業（buyback_app）

- PostgreSQLの`buyback_announcement_plan_status` 作成（`stock-market-db`で`alembic upgrade head`。allowlist追加より先に適用する）
- 同期allowlistへの`announcement_plan_status`追加
- フロントでの結合・表示

## 6. 受入条件

- 1案件が1行になり、同期再実行で重複しない。
- 案件のない発表行の表示が変わらない。
- 未確定イベントが進捗・完了に混入しない。
- 切替前に代表データを両側で確認する。
