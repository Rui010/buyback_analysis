from sqlalchemy import create_engine, inspect, text

import pytest

from midterm_plan_analysis.usecase.migrate_reference_values import migrate_reference_values


def _create_table_without_reference_values(engine):
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE midterm_plans ("
                "code VARCHAR NOT NULL, url VARCHAR NOT NULL, metrics TEXT, extraction_status VARCHAR, "
                "PRIMARY KEY (code, url))"
            )
        )
        connection.execute(
            text("INSERT INTO midterm_plans (code, url, metrics) VALUES ('1234', 'https://x/a.pdf', '[]')")
        )


def test_migration_adds_nullable_column_and_preserves_rows():
    engine = create_engine("sqlite:///:memory:", future=True)
    _create_table_without_reference_values(engine)

    assert migrate_reference_values(engine) == ["reference_values"]

    columns = {c["name"]: c for c in inspect(engine).get_columns("midterm_plans")}
    assert columns["reference_values"]["nullable"] is True
    with engine.connect() as connection:
        row = connection.execute(text("SELECT code, metrics, reference_values FROM midterm_plans")).one()
    assert tuple(row) == ("1234", "[]", None)  # 既存行は旧仕様のままnull


def test_migration_is_idempotent():
    engine = create_engine("sqlite:///:memory:", future=True)
    _create_table_without_reference_values(engine)
    migrate_reference_values(engine)
    assert migrate_reference_values(engine) == []


def test_migration_skips_missing_table():
    assert migrate_reference_values(create_engine("sqlite:///:memory:", future=True)) == []


def test_migration_rejects_non_sqlite():
    engine = create_engine("postgresql://user:pass@localhost/db", future=True)
    with pytest.raises(ValueError):
        migrate_reference_values(engine)
