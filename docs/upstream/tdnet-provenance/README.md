# TDnet原典・抽出run履歴 引継ぎ仕様（参照用コピー）

`buyback-analysis-tdnet-provenance.md` は `C:\apps\ir-analytics-platform\docs\plans\handoffs\` の写し（2026-11-08 第2版、コピー元未コミット）。正本はコピー元で、本ファイルは編集しない。

関連資料はコピーせず、コピー元を参照する（パスはすべて `C:\apps\ir-analytics-platform\` 配下）。

- `docs/plans/handoffs/buyback-app-data-transport-history-exclusion.md`: buyback_appの同期allowlist化。本番SQLiteへの履歴テーブルmigrationの前提条件
- `src/ir_analytics_contract/tdnet_sources.py`: `attach_verified_tdnet_source()`（台帳照合）
- `src/ir_analytics_contract/processing.py`: `RunSpec.reuse_key()`・`execute_or_reuse()`（run契約）
