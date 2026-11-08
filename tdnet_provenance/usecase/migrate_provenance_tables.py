"""運用原典台帳・processing runテーブルの冪等migration。

不足テーブルだけを作成する。既存テーブルの列集合がモデルと異なる場合は何も作らずに停止する
（`create_all()`は既存テーブルへ列を追加しないため、差分を黙って残さない）。
"""

from sqlalchemy import inspect, text

from tdnet_provenance.models.base import ProvenanceBase
from tdnet_provenance.models.processing_run import ProcessingRun  # noqa: F401 metadataへ登録
from tdnet_provenance.models.tdnet_source_document import TdnetSourceDocument  # noqa: F401 metadataへ登録


def table_row_counts(engine) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            name: connection.execute(text(f'SELECT COUNT(*) FROM "{name}"')).scalar()
            for name in inspect(connection).get_table_names()
        }


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
