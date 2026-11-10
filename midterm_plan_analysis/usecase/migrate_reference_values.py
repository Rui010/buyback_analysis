"""中期経営計画のreference_values列を既存SQLiteへ追加する。

PostgreSQLへの同期（buyback_app）は列の構成が違うテーブルをスキップするため、
PostgreSQL側のbuyback_midterm_plansにも同じ列を追加してから同期を再開すること。
"""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

REFERENCE_VALUES_COLUMN = "reference_values"


def migrate_reference_values(engine: Engine) -> list[str]:
    """reference_values列がなければ追加し、追加した列名を返す（既存行はnullのまま）。"""
    if engine.dialect.name != "sqlite":
        raise ValueError("reference_values列の移行はSQLiteでのみ実行できます")

    inspector = inspect(engine)
    if "midterm_plans" not in inspector.get_table_names():
        return []
    existing = {column["name"] for column in inspector.get_columns("midterm_plans")}
    if REFERENCE_VALUES_COLUMN in existing:
        return []

    with engine.begin() as connection:
        connection.execute(text(f"ALTER TABLE midterm_plans ADD COLUMN {REFERENCE_VALUES_COLUMN} TEXT"))
    return [REFERENCE_VALUES_COLUMN]
