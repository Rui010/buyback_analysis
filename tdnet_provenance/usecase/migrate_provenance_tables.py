"""運用原典台帳・processing runテーブルの冪等migrationと事後検証。

不足テーブルだけを作成する。既存テーブルの列集合がモデルと異なる場合は何も作らずに停止する
（`create_all()`は既存テーブルへ列を追加しないため、差分を黙って残さない）。
"""

import hashlib
import sqlite3
from pathlib import Path

from sqlalchemy import inspect, text

from tdnet_provenance.models.base import ProvenanceBase
import tdnet_provenance.models  # noqa: F401 全テーブルをmetadataへ登録


def table_row_counts(engine) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            name: connection.execute(text(f'SELECT COUNT(*) FROM "{name}"')).scalar()
            for name in inspect(connection).get_table_names()
        }


def table_fingerprints(engine) -> dict[str, tuple[int, str]]:
    """全テーブルの(行数, 全行の内容hash)。行数が同じでも値が変われば検出できる。"""
    fingerprints = {}
    with engine.connect() as connection:
        inspector = inspect(connection)
        for name in inspector.get_table_names():
            columns = [c["name"] for c in inspector.get_columns(name)]
            order = ", ".join(str(i) for i in range(1, len(columns) + 1))
            digest = hashlib.sha256()
            count = 0
            for row in connection.execute(text(f'SELECT * FROM "{name}" ORDER BY {order}')):
                digest.update(repr(tuple(row)).encode("utf-8"))
                count += 1
            fingerprints[name] = (count, digest.hexdigest())
    return fingerprints


def migrate_provenance_tables(engine) -> list[str]:
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    for name, table in ProvenanceBase.metadata.tables.items():
        if name not in existing:
            continue
        actual = {column["name"] for column in inspector.get_columns(name)}
        expected = {column.name for column in table.columns}
        if actual != expected:
            raise RuntimeError(
                f"{name} の列がモデルと一致しません。不足: {sorted(expected - actual)} 余分: {sorted(actual - expected)}"
            )

    missing = sorted(set(ProvenanceBase.metadata.tables) - existing)
    ProvenanceBase.metadata.create_all(engine, tables=[ProvenanceBase.metadata.tables[n] for n in missing])
    return missing


def verify_provenance_schema(engine) -> None:
    """migration後のschema（列・NULL許容・主キー・索引）がモデルと一致することを確認する。"""
    inspector = inspect(engine)
    problems = []
    for name, table in ProvenanceBase.metadata.tables.items():
        if not inspector.has_table(name):
            problems.append(f"{name}: テーブルがありません")
            continue
        actual = {c["name"]: c for c in inspector.get_columns(name)}
        for column in table.columns:
            found = actual.get(column.name)
            if found is None:
                problems.append(f"{name}.{column.name}: 列がありません")
            elif bool(found["nullable"]) != bool(column.nullable):
                problems.append(f"{name}.{column.name}: nullableが{found['nullable']}（期待{column.nullable}）")
        for extra in sorted(set(actual) - {c.name for c in table.columns}):
            problems.append(f"{name}.{extra}: モデルにない列です")
        expected_pk = [c.name for c in table.primary_key.columns]
        actual_pk = inspector.get_pk_constraint(name)["constrained_columns"]
        if actual_pk != expected_pk:
            problems.append(f"{name}: 主キーが{actual_pk}（期待{expected_pk}）")
        actual_indexes = {i["name"] for i in inspector.get_indexes(name)}
        for index in table.indexes:
            if index.name not in actual_indexes:
                problems.append(f"{name}: 索引 {index.name} がありません")
    if problems:
        raise RuntimeError("schemaがモデルと一致しません: " + " / ".join(problems))


REFERENCE_CHECKS = {
    "版のないadoption": (
        "SELECT COUNT(*) FROM result_adoptions a "
        "LEFT JOIN result_versions v ON v.version_id = a.version_id WHERE v.version_id IS NULL"
    ),
    "runのないrun_output": (
        "SELECT COUNT(*) FROM run_outputs o "
        "LEFT JOIN processing_runs r ON r.run_id = o.run_id WHERE r.run_id IS NULL"
    ),
    "再利用元のないreused run": (
        "SELECT COUNT(*) FROM processing_runs r "
        "LEFT JOIN processing_runs o ON o.run_id = r.reused_run_id "
        "WHERE r.reused_run_id IS NOT NULL AND o.run_id IS NULL"
    ),
    "再試行元のないretry run": (
        "SELECT COUNT(*) FROM processing_runs r "
        "LEFT JOIN processing_runs o ON o.run_id = r.retry_of_run_id "
        "WHERE r.retry_of_run_id IS NOT NULL AND o.run_id IS NULL"
    ),
}


def verify_provenance_references(engine) -> None:
    """履歴テーブル間の参照切れがないことを確認する（SQLiteの外部キーは使っていないため）。"""
    with engine.connect() as connection:
        broken = {name: connection.execute(text(sql)).scalar() for name, sql in REFERENCE_CHECKS.items()}
    broken = {name: count for name, count in broken.items() if count}
    if broken:
        raise RuntimeError(f"履歴テーブルに参照切れがあります: {broken}")


def backup_sqlite_database(source_path, backup_path) -> Path:
    """SQLiteのオンラインバックアップ。"""
    source_path, backup_path = Path(source_path), Path(backup_path)
    if backup_path.exists():
        raise FileExistsError(f"バックアップ先が既にあります: {backup_path}")
    with sqlite3.connect(source_path) as source, sqlite3.connect(backup_path) as backup:
        source.backup(backup)
    return backup_path


def restore_sqlite_backup(backup_path, target_path) -> None:
    """バックアップの内容でDBを置き換える。パイプライン停止中に実行すること。"""
    with sqlite3.connect(Path(backup_path)) as backup, sqlite3.connect(Path(target_path)) as target:
        backup.backup(target)
