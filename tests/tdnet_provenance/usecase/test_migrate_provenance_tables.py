import pytest
from sqlalchemy import create_engine, inspect, text

from tdnet_provenance.usecase.migrate_provenance_tables import (
    backup_sqlite_database,
    migrate_provenance_tables,
    restore_sqlite_backup,
    table_fingerprints,
    table_row_counts,
    verify_provenance_schema,
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


def test_verify_schema_passes_after_migration():
    engine = create_engine("sqlite:///:memory:", future=True)
    migrate_provenance_tables(engine)
    verify_provenance_schema(engine)


def test_verify_schema_detects_missing_index():
    engine = create_engine("sqlite:///:memory:", future=True)
    migrate_provenance_tables(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX ix_processing_runs_reuse_key"))
    with pytest.raises(RuntimeError, match="ix_processing_runs_reuse_key"):
        verify_provenance_schema(engine)


def test_verify_schema_detects_nullability_difference():
    engine = create_engine("sqlite:///:memory:", future=True)
    migrate_provenance_tables(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE tdnet_source_documents"))
        connection.execute(text(
            "CREATE TABLE tdnet_source_documents (url TEXT PRIMARY KEY, source_document_id TEXT UNIQUE, "
            "external_document_id TEXT NOT NULL, disclosure_date TEXT NOT NULL, published_at TEXT, "
            "storage_uri TEXT NOT NULL, source_hash TEXT NOT NULL, file_size INTEGER NOT NULL, "
            "fetched_at TEXT, observed_at TEXT NOT NULL)"
        ))
    with pytest.raises(RuntimeError, match="source_document_id"):
        verify_provenance_schema(engine)


def test_fingerprints_detect_value_change_with_same_row_count():
    engine = _engine_with_existing_data()
    before = table_fingerprints(engine)
    migrate_provenance_tables(engine)
    assert {k: v for k, v in table_fingerprints(engine).items() if k in before} == before

    with engine.begin() as connection:
        connection.execute(text("UPDATE midterm_plans SET url = 'https://x/b.pdf'"))
    assert table_fingerprints(engine)["midterm_plans"] != before["midterm_plans"]


def test_backup_can_be_restored(tmp_path):
    db_path = tmp_path / "buyback.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE midterm_plans (code TEXT, url TEXT, PRIMARY KEY (code, url))"))
        connection.execute(text("INSERT INTO midterm_plans VALUES ('1234', 'https://x/a.pdf')"))
    before = table_fingerprints(engine)

    backup_path = backup_sqlite_database(db_path, tmp_path / "buyback.db.bak")
    migrate_provenance_tables(engine)
    engine.dispose()

    restore_sqlite_backup(backup_path, db_path)

    restored = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    assert table_fingerprints(restored) == before
    assert "processing_runs" not in inspect(restored).get_table_names()
    restored.dispose()
