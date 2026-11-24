# TODO: 案件の進捗・完了をフロントに出す（方針B）

作成日: 2026-11-23（未着手。作業再開時はここから）

## 目的

フロントの一覧は従来テーブル（`announcements`等）基準のまま、案件がある行だけ進捗・完了を付け足す（方針1）。
そのために、buyback_analysis側で「発表文書URL → 案件の現在状態」を1行にまとめた表を作り、それだけをPostgreSQLへ同期する（方針B）。

新4テーブル（`buyback_events`・`buyback_event_link_decisions`・`buyback_plans`・`buyback_plan_projections`）は同期しない。
理由: 親子順序・TRUNCATE中の参照不整合・追記型履歴の扱いを決めずに済み、紐づけ方を変えてもフロントへの影響がこの表の中で収まる。

## 決定事項（2026-11-23）

- 表名: SQLite `announcement_plan_status` → PostgreSQL `buyback_announcement_plan_status`
- 主キーは `buyback_plan_id`。1文書から複数案件ができた場合は同じ `announcement_url` が複数行になる（フロントは全行表示）
- 入れるのは `is_publishable=true` の案件だけ。未確定イベントは入れない
- 進捗率は上流で計算する（上限か累計が欠けていればNULL）
- `latest_progress_date` を入れる
- 自己株買いパイプラインの最後、projection再計算の後に毎回まるごと作り直す
- 当初値・判定履歴・引用は入れない（必要になったら列を足す）

## 列

| 列 | 内容 | 元 |
|---|---|---|
| `buyback_plan_id` | 案件ID（PK） | plans |
| `announcement_url` | 発表文書URL。フロントの結合キー | 起点イベント（`plans.origin_event_uid` → `events.url`） |
| `code` | 証券コード | plans |
| `plan_status` | `planned` / `in_progress` / `completed` | projection |
| `current_shares` / `current_amount_yen` | 現在の上限（変更反映後） | projection |
| `current_start_date` / `current_end_date` | 現在の取得期間 | projection |
| `cumulative_shares_acquired` / `cumulative_amount_spent_yen` | 進捗累計 | projection |
| `completion_shares_acquired` / `completion_amount_spent_yen` | 完了時の最終実績 | projection |
| `progress_rate_amount` / `progress_rate_shares` | 累計 ÷ 上限 | 上流で計算 |
| `latest_progress_date` | 最新の進捗報告日 | LINKEDな進捗イベントの日付 |
| `aggregation_rule_version` / `calculated_at` | 集計ルール版・計算日時 | projection |

## 現状データ（2026-11-20時点のサーバーSQLiteコピーで確認）

- 案件64件、すべてACTIVE・publishable（planned 58 / in_progress 2 / completed 4）
- 64件とも起点文書が `announcements` に存在。1文書→複数案件は0件

## TODO

### buyback_analysis
- [x] テストを先に書く（列の導出、進捗率NULL条件、publishableのみ、1文書複数案件、作り直しの冪等性）
- [x] モデル `buyback_analysis/models/announcement_plan_status.py` とテスト
- [x] 作成usecase `buyback_analysis/usecase/rebuild_announcement_plan_status.py`（2026-11-24。進捗率は0〜1の比率、latest_progress_dateはprogressイベントのみ、FKなし、calculated_atはprojectionの値）
- [x] `main.py` の全文書処理後（サマリー前）に1回呼ぶ。失敗時はrollbackしてログ・エラー通知（パイプラインは止めない）。サマリーに「案件状態表:N件」を追加
- [x] 本番SQLiteへのテーブル作成方法: `init_db()`（`sqlite_engine.py` でモデルをimport）。FKなし・毎回作り直しの派生表なのでmigration不要（2026-11-24決定）
- [x] 設計を `docs/buyback_plan_event_linking_design.md` と下流契約 `docs/handoffs/buyback-plan-event-linking-contract.md` に反映
- [x] CLAUDE.md のアーキテクチャ・データフローを更新
- [x] カバレッジ計測（新規2モジュール100%）

### buyback_app向け（作業指示書を `docs/handoffs/` に書く）
- [x] PostgreSQLのテーブル定義（DDL）: `C:/apps/stock-market-db` の revision `4efefc53e4b4`（2026-11-24 master反映・本番PG適用済み、列・PK・インデックス確認済み）。数値はdouble precision、calculated_atはtimestamp（UTC）。allowlist追加より先に適用する
- [ ] 同期allowlistに `announcement_plan_status` を追加
- [ ] フロント: `announcements.url = announcement_url` で結合し、案件がある行だけ進捗・完了を表示。同URL複数行は全表示

### 並行
- [ ] 進捗の累計値欠落（初回12件中8件）のプロンプト改善

## 適用順序

1. buyback_analysisで実装・テスト → サーバー反映 → 表が作られることを確認
2. buyback_appでDDL作成・allowlist追加 → 同期を確認
3. フロント実装
