from sqlalchemy import create_engine, inspect, text

import pytest

from midterm_plan_analysis.usecase.migrate_plan_period_fields import (
    migrate_plan_period_fields,
)


def _create_legacy_table(engine):
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE midterm_plans ("
                "code VARCHAR NOT NULL, url VARCHAR NOT NULL, "
                "plan_name VARCHAR, plan_start_year INTEGER, plan_end_year INTEGER, "
                "disclosure_date VARCHAR, metrics TEXT, extraction_status VARCHAR, "
                "PRIMARY KEY (code, url))"
            )
        )
        connection.execute(
            text(
                "INSERT INTO midterm_plans "
                "(code, url, plan_name, plan_start_year, plan_end_year) "
                "VALUES ('1234', 'https://example.com/plan.pdf', '2027中計', 2025, 2027)"
            )
        )


def test_migration_adds_nullable_columns_and_preserves_rows():
    engine = create_engine("sqlite:///:memory:", future=True)
    _create_legacy_table(engine)

    migrated = migrate_plan_period_fields(engine)

    assert migrated == [
        "plan_start_period_label",
        "plan_end_period_label",
        "plan_start_fiscal_end",
        "plan_end_fiscal_end",
    ]
    columns = {column["name"]: column for column in inspect(engine).get_columns("midterm_plans")}
    for name in migrated:
        assert name in columns
        assert columns[name]["nullable"] is True

    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT code, url, plan_start_year, plan_end_year, "
                "plan_start_period_label FROM midterm_plans"
            )
        ).one()
    assert tuple(row) == ("1234", "https://example.com/plan.pdf", 2025, 2027, None)


def test_migration_is_idempotent():
    engine = create_engine("sqlite:///:memory:", future=True)
    _create_legacy_table(engine)

    migrate_plan_period_fields(engine)

    assert migrate_plan_period_fields(engine) == []


def test_migration_returns_empty_when_table_does_not_exist():
    engine = create_engine("sqlite:///:memory:", future=True)

    assert migrate_plan_period_fields(engine) == []


def test_migration_rejects_non_sqlite_engine():
    engine = create_engine("postgresql+psycopg2://user:pass@localhost/db", future=True)

    with pytest.raises(ValueError, match="SQLite"):
        migrate_plan_period_fields(engine)
