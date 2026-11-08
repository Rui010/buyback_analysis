"""既存SQLiteへ運用原典台帳・processing runテーブルを追加するエントリーポイント。

buyback_appの同期allowlist化（ir-analytics-platform
docs/plans/handoffs/buyback-app-data-transport-history-exclusion.md）の受入完了前に
本番SQLiteへ実行しないこと。新テーブルがPostgreSQLへ自動コピーされる。
"""

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# ``python scripts/...`` でもリポジトリ直下のパッケージを解決できるようにする。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from buyback_analysis.interface.sqlite_engine import engine
from tdnet_provenance.usecase.migrate_provenance_tables import (
    migrate_provenance_tables,
    table_row_counts,
)


def _backup_sqlite_database() -> Path:
    database = engine.url.database
    if not database or database == ":memory:":
        raise ValueError("ファイルSQLiteだけが移行対象です")

    source_path = Path(database).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"SQLiteファイルが見つかりません: {source_path}")

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = source_path.with_name(f"{source_path.name}.bak-provenance-{timestamp}")
    with sqlite3.connect(source_path) as source, sqlite3.connect(backup_path) as backup:
        source.backup(backup)
    return backup_path


if __name__ == "__main__":
    before = table_row_counts(engine)
    backup_path = _backup_sqlite_database()
    created = migrate_provenance_tables(engine)
    after = table_row_counts(engine)

    print(f"バックアップ: {backup_path}")
    print(f"作成したテーブル: {', '.join(created) if created else 'なし（作成済み）'}")
    changed = {name: (count, after.get(name)) for name, count in before.items() if after.get(name) != count}
    if changed:
        raise SystemExit(f"既存テーブルの行数が変わりました: {changed}")
    for name in sorted(after):
        print(f"  {name}: {before.get(name, '-')} -> {after[name]}")
