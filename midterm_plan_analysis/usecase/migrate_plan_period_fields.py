"""中期経営計画の期間表記カラムを既存SQLiteへ追加する。"""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


PLAN_PERIOD_COLUMNS = (
    "plan_start_period_label",
    "plan_end_period_label",
    "plan_start_fiscal_end",
    "plan_end_fiscal_end",
)


def migrate_plan_period_fields(engine: Engine) -> list[str]:
    """不足している期間表記カラムだけを追加し、追加したカラム名を返す。"""
    if engine.dialect.name != "sqlite":
        raise ValueError("計画期間カラム移行はSQLiteでのみ実行できます")

    inspector = inspect(engine)
    if "midterm_plans" not in inspector.get_table_names():
        return []

    existing_columns = {
        column["name"] for column in inspector.get_columns("midterm_plans")
    }
    missing_columns = [
        column for column in PLAN_PERIOD_COLUMNS if column not in existing_columns
    ]
    if not missing_columns:
        return []

    with engine.begin() as connection:
        for column in missing_columns:
            connection.execute(
                text(f"ALTER TABLE midterm_plans ADD COLUMN {column} VARCHAR")
            )

    return missing_columns
