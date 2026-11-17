"""Add Phase 1 buyback plan/event tables to an existing SQLite database.

The script creates an online backup before changing the database. Restore while
all pipelines are stopped:

    python scripts/migrate_buyback_plan_event_tables.py --restore <backup-file>
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from buyback_analysis.interface.sqlite_engine import engine
from buyback_analysis.usecase.migrate_buyback_plan_event_tables import (
    TARGET_TABLES,
    migrate_buyback_plan_event_tables,
    verify_buyback_plan_event_references,
    verify_buyback_plan_event_schema,
)
from tdnet_provenance.usecase.migrate_provenance_tables import (
    backup_sqlite_database,
    restore_sqlite_backup,
    table_fingerprints,
)


def _database_path() -> Path:
    database = engine.url.database
    if not database or database == ":memory:":
        raise ValueError("ファイルSQLiteだけが移行対象です")
    path = Path(database).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"SQLiteファイルが見つかりません: {path}")
    return path


def migrate() -> None:
    database_path = _database_path()
    before = table_fingerprints(engine)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = backup_sqlite_database(
        database_path,
        database_path.with_name(
            f"{database_path.name}.bak-buyback-plan-events-{timestamp}"
        ),
    )
    print(f"バックアップ: {backup_path}")

    result = migrate_buyback_plan_event_tables(engine)
    print(
        "作成したテーブル: "
        + (", ".join(result.created_tables) if result.created_tables else "なし")
    )
    print(
        "追加した列: "
        + (", ".join(result.added_columns) if result.added_columns else "なし")
    )
    verify_buyback_plan_event_schema(engine)
    print("schema検証: OK")
    verify_buyback_plan_event_references(engine)
    print("参照検証: OK")

    after = table_fingerprints(engine)
    unrelated_changed = sorted(
        name
        for name, fingerprint in before.items()
        if name not in TARGET_TABLES and after.get(name) != fingerprint
    )
    target_count_changed = sorted(
        name
        for name in TARGET_TABLES
        if name in before and after.get(name, (-1, ""))[0] != before[name][0]
    )
    if unrelated_changed or target_count_changed:
        raise SystemExit(
            "migrationで既存データが変わりました。"
            f"対象外テーブル: {unrelated_changed} / 対象テーブル行数: {target_count_changed}。"
            f"バックアップから復元してください: {backup_path}"
        )
    print("既存データ検証: OK")


def restore(backup_path: str) -> None:
    database_path = _database_path()
    engine.dispose()
    restore_sqlite_backup(backup_path, database_path)
    print(f"復元しました: {backup_path} -> {database_path}")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--restore":
        restore(sys.argv[2])
    elif len(sys.argv) == 1:
        migrate()
    else:
        raise SystemExit(
            "usage: migrate_buyback_plan_event_tables.py [--restore <backup>]"
        )
