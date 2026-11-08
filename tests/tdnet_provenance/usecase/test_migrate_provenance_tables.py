import pytest
from sqlalchemy import create_engine, inspect, text

from tdnet_provenance.usecase.migrate_provenance_tables import (
    migrate_provenance_tables,
    table_row_counts,
)


def _engine_with_existing_data():
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE midterm_plans (code TEXT, url TEXT, PRIMARY KEY (code, url))"))
        connection.execute(text("INSERT INTO midterm_plans VALUES ('1234', 'https://x/a.pdf')"))
    return engine


def test_creates_tables_on_empty_db():
    engine = create_engine("sqlite:///:memory:", future=True)
    assert migrate_provenance_tables(engine) == ["processing_runs", "tdnet_source_documents"]
    assert {"processing_runs", "tdnet_source_documents"} <= set(inspect(engine).get_table_names())


def test_existing_tables_and_rows_are_unchanged():
    engine = _engine_with_existing_data()
    before = table_row_counts(engine)

    migrate_provenance_tables(engine)

    after = table_row_counts(engine)
    assert after["midterm_plans"] == before["midterm_plans"] == 1
    with engine.connect() as connection:
        assert connection.execute(text("SELECT url FROM midterm_plans")).scalar() == "https://x/a.pdf"


def test_second_run_is_noop():
    engine = _engine_with_existing_data()
    migrate_provenance_tables(engine)
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO processing_runs (run_id, input_locator, input_hash, run_kind, stage, code_commit, "
            "generation_config, reuse_key, status, started_at, completed_at) "
            "VALUES ('r1', 'u', 'h', 'extract', 'metrics', 'c', '{}', 'k', 'succeeded', 's', 'e')"
        ))

    assert migrate_provenance_tables(engine) == []
    assert table_row_counts(engine)["processing_runs"] == 1


def test_rejects_existing_table_with_different_columns():
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE processing_runs (run_id TEXT PRIMARY KEY)"))

    with pytest.raises(RuntimeError, match="processing_runs"):
        migrate_provenance_tables(engine)
    assert "tdnet_source_documents" not in inspect(engine).get_table_names()
