"""Idempotent SQLite migration for Phase 1 buyback plan/event tables."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import inspect, text

from buyback_analysis.models.base import Base
from buyback_analysis.models.buyback_event import BuybackEvent  # noqa: F401
from buyback_analysis.models.buyback_event_link_decision import (  # noqa: F401
    BuybackEventLinkDecision,
)
from buyback_analysis.models.buyback_plan import BuybackPlan  # noqa: F401
from buyback_analysis.models.buyback_plan_projection import (  # noqa: F401
    BuybackPlanProjection,
)


TARGET_TABLES = (
    "buyback_events",
    "buyback_plans",
    "buyback_event_link_decisions",
    "buyback_plan_projections",
)


@dataclass(frozen=True)
class BuybackPlanEventMigrationResult:
    created_tables: tuple[str, ...]
    added_columns: tuple[str, ...]


def _expected_columns(table_name: str) -> set[str]:
    return {column.name for column in Base.metadata.tables[table_name].columns}


def migrate_buyback_plan_event_tables(engine) -> BuybackPlanEventMigrationResult:
    """Create missing tables and upgrade the pre-release event table shape."""

    if engine.dialect.name != "sqlite":
        raise ValueError("SQLiteだけが移行対象です")

    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    add_quote_column = False
    for table_name in TARGET_TABLES:
        if table_name not in existing:
            continue
        actual = {column["name"] for column in inspector.get_columns(table_name)}
        expected = _expected_columns(table_name)
        missing = expected - actual
        extra = actual - expected
        if table_name == "buyback_events" and missing == {"source_quote_verified"} and not extra:
            add_quote_column = True
            continue
        if missing or extra:
            raise RuntimeError(
                f"{table_name} の列がモデルと一致しません。"
                f"不足: {sorted(missing)} 余分: {sorted(extra)}"
            )

    missing_tables = tuple(sorted(set(TARGET_TABLES) - existing))
    added_columns: tuple[str, ...] = ()
    with engine.begin() as connection:
        if add_quote_column:
            connection.execute(
                text(
                    "ALTER TABLE buyback_events ADD COLUMN "
                    "source_quote_verified BOOLEAN NOT NULL DEFAULT 0"
                )
            )
            added_columns = ("buyback_events.source_quote_verified",)
        Base.metadata.create_all(
            connection,
            tables=[Base.metadata.tables[name] for name in missing_tables],
        )
    return BuybackPlanEventMigrationResult(missing_tables, added_columns)


def verify_buyback_plan_event_schema(engine) -> None:
    """Verify columns, nullability, primary keys, and named indexes."""

    inspector = inspect(engine)
    problems: list[str] = []
    for table_name in TARGET_TABLES:
        table = Base.metadata.tables[table_name]
        if not inspector.has_table(table_name):
            problems.append(f"{table_name}: テーブルがありません")
            continue
        actual = {column["name"]: column for column in inspector.get_columns(table_name)}
        for column in table.columns:
            found = actual.get(column.name)
            if found is None:
                problems.append(f"{table_name}.{column.name}: 列がありません")
            elif bool(found["nullable"]) != bool(column.nullable):
                problems.append(
                    f"{table_name}.{column.name}: nullableが{found['nullable']}"
                    f"（期待{column.nullable}）"
                )
        for extra in sorted(set(actual) - _expected_columns(table_name)):
            problems.append(f"{table_name}.{extra}: モデルにない列です")
        expected_pk = [column.name for column in table.primary_key.columns]
        actual_pk = inspector.get_pk_constraint(table_name)["constrained_columns"]
        if actual_pk != expected_pk:
            problems.append(f"{table_name}: 主キーが{actual_pk}（期待{expected_pk}）")
        actual_indexes = {index["name"] for index in inspector.get_indexes(table_name)}
        for index in table.indexes:
            if index.name not in actual_indexes:
                problems.append(f"{table_name}: 索引 {index.name} がありません")
    if problems:
        raise RuntimeError("schemaがモデルと一致しません: " + " / ".join(problems))


REFERENCE_CHECKS = {
    "起点イベントのない案件": (
        "SELECT COUNT(*) FROM buyback_plans p "
        "LEFT JOIN buyback_events e ON e.event_uid = p.origin_event_uid "
        "WHERE e.event_uid IS NULL"
    ),
    "イベントのない判定": (
        "SELECT COUNT(*) FROM buyback_event_link_decisions d "
        "LEFT JOIN buyback_events e ON e.event_uid = d.event_uid "
        "WHERE e.event_uid IS NULL"
    ),
    "案件のない確定判定": (
        "SELECT COUNT(*) FROM buyback_event_link_decisions d "
        "LEFT JOIN buyback_plans p ON p.buyback_plan_id = d.linked_plan_id "
        "WHERE d.linked_plan_id IS NOT NULL AND p.buyback_plan_id IS NULL"
    ),
    "案件のない集計": (
        "SELECT COUNT(*) FROM buyback_plan_projections x "
        "LEFT JOIN buyback_plans p ON p.buyback_plan_id = x.buyback_plan_id "
        "WHERE p.buyback_plan_id IS NULL"
    ),
}


def verify_buyback_plan_event_references(engine) -> None:
    with engine.connect() as connection:
        broken = {
            name: connection.execute(text(sql)).scalar()
            for name, sql in REFERENCE_CHECKS.items()
        }
    broken = {name: count for name, count in broken.items() if count}
    if broken:
        raise RuntimeError(f"案件・イベントテーブルに参照切れがあります: {broken}")
