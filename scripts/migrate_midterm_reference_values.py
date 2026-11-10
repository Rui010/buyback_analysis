"""既存SQLiteのmidterm_plansへreference_values列を追加するエントリーポイント。

列を追加したコードを動かす前に実行すること（モデルに列があるため、未追加のDBではmidterm_plansの読み書きが失敗する）。
PostgreSQLへの同期は列の構成が違うとスキップされるため、buyback_app側でbuyback_midterm_plansに
同じ列（reference_values TEXT）を追加してから同期を再開する。
"""

import sys
from pathlib import Path

# ``python scripts/...`` でもリポジトリ直下のパッケージを解決できるようにする。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from buyback_analysis.interface.sqlite_engine import engine
from midterm_plan_analysis.usecase.migrate_reference_values import migrate_reference_values
from scripts.migrate_midterm_plan_period_fields import _backup_sqlite_database


if __name__ == "__main__":
    backup_path = _backup_sqlite_database(label="reference-values")
    migrated = migrate_reference_values(engine)
    print(f"バックアップ: {backup_path}")
    print(f"reference_values列の移行完了: {', '.join(migrated) if migrated else '追加不要'}")
