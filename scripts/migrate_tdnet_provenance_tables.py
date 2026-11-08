"""既存SQLiteへ運用原典台帳・processing runテーブルを追加するエントリーポイント。

buyback_appの同期allowlist化（ir-analytics-platform
docs/plans/handoffs/buyback-app-data-transport-history-exclusion.md）の受入完了前に
本番SQLiteへ実行しないこと。新テーブルがPostgreSQLへ自動コピーされる。

復元: パイプライン停止中に
    python scripts/migrate_tdnet_provenance_tables.py --restore <バックアップファイル>
"""

import sys
from datetime import datetime
from pathlib import Path

# ``python scripts/...`` でもリポジトリ直下のパッケージを解決できるようにする。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from buyback_analysis.interface.sqlite_engine import engine
from tdnet_provenance.usecase.migrate_provenance_tables import (
    backup_sqlite_database,
    migrate_provenance_tables,
    restore_sqlite_backup,
    table_fingerprints,
    verify_provenance_references,
    verify_provenance_schema,
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
        database_path, database_path.with_name(f"{database_path.name}.bak-provenance-{timestamp}")
    )
    print(f"バックアップ: {backup_path}")

    created = migrate_provenance_tables(engine)
    print(f"作成したテーブル: {', '.join(created) if created else 'なし（作成済み）'}")

    verify_provenance_schema(engine)
    print("schema検証: OK")
    verify_provenance_references(engine)
    print("履歴テーブルの参照検証: OK")

    after = table_fingerprints(engine)
    changed = sorted(name for name, value in before.items() if after.get(name) != value)
    if changed:
        raise SystemExit(f"既存テーブルの内容が変わりました: {changed}。バックアップから復元してください: {backup_path}")
    for name in sorted(after):
        print(f"  {name}: {before[name][0] if name in before else '-'} -> {after[name][0]}行")
    print("既存テーブルの内容検証（全行hash）: OK")


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
        raise SystemExit("usage: migrate_tdnet_provenance_tables.py [--restore <backup>]")
