"""既存SQLiteへ中計の期間表記カラムを追加するエントリーポイント。"""

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# ``python scripts/...`` でもリポジトリ直下のパッケージを解決できるようにする。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from buyback_analysis.interface.sqlite_engine import engine
from midterm_plan_analysis.usecase.migrate_plan_period_fields import (
    migrate_plan_period_fields,
)


def _backup_sqlite_database() -> Path:
    database = engine.url.database
    if not database or database == ":memory:":
        raise ValueError("ファイルSQLiteだけが移行対象です")

    source_path = Path(database).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"SQLiteファイルが見つかりません: {source_path}")

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = source_path.with_name(f"{source_path.name}.bak-plan-period-{timestamp}")
    with sqlite3.connect(source_path) as source, sqlite3.connect(backup_path) as backup:
        source.backup(backup)
    return backup_path


if __name__ == "__main__":
    backup_path = _backup_sqlite_database()
    migrated = migrate_plan_period_fields(engine)
    print(f"バックアップ: {backup_path}")
    print(f"計画期間カラム移行完了: {', '.join(migrated) if migrated else '追加不要'}")
