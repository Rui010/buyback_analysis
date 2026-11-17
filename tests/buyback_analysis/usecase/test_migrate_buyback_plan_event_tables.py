import pytest
from sqlalchemy import create_engine, inspect, text

from buyback_analysis.usecase.migrate_buyback_plan_event_tables import (
    TARGET_TABLES,
    migrate_buyback_plan_event_tables,
    verify_buyback_plan_event_references,
    verify_buyback_plan_event_schema,
)
from tdnet_provenance.usecase.migrate_provenance_tables import table_fingerprints


def test_creates_all_four_tables_on_empty_database():
    engine = create_engine("sqlite:///:memory:", future=True)

    result = migrate_buyback_plan_event_tables(engine)

    assert set(result.created_tables) == set(TARGET_TABLES)
    assert result.added_columns == ()
    assert set(TARGET_TABLES) <= set(inspect(engine).get_table_names())
    verify_buyback_plan_event_schema(engine)
    verify_buyback_plan_event_references(engine)


def test_second_run_is_noop_and_preserves_unrelated_data():
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE existing_data (id INTEGER PRIMARY KEY, value TEXT)"))
        connection.execute(text("INSERT INTO existing_data VALUES (1, 'keep')"))
    migrate_buyback_plan_event_tables(engine)
    before = table_fingerprints(engine)

    result = migrate_buyback_plan_event_tables(engine)

    assert result.created_tables == ()
    assert result.added_columns == ()
    assert table_fingerprints(engine) == before


def test_adds_quote_verification_column_to_pre_release_shape():
    engine = create_engine("sqlite:///:memory:", future=True)
    migrate_buyback_plan_event_tables(engine)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE buyback_events DROP COLUMN source_quote_verified"))
        connection.execute(
            text(
                "INSERT INTO buyback_events "
                "(event_uid, version_id, url, code, event_type, event_fingerprint, "
                "source_quote, payload, is_active) VALUES "
                "('e1', 'v1', 'https://x/a.pdf', '1234', 'new_plan', 'fp', "
                "'十分な長さの原文引用です。', '{}', 1)"
            )
        )

    result = migrate_buyback_plan_event_tables(engine)

    assert result.created_tables == ()
    assert result.added_columns == ("buyback_events.source_quote_verified",)
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT event_uid, source_quote_verified FROM buyback_events")
        ).one()
    assert tuple(row) == ("e1", 0)
    verify_buyback_plan_event_schema(engine)


def test_rejects_unexpected_existing_shape_before_creating_other_tables():
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE buyback_plans (buyback_plan_id TEXT PRIMARY KEY)"))

    with pytest.raises(RuntimeError, match="buyback_plans"):
        migrate_buyback_plan_event_tables(engine)

    assert "buyback_events" not in inspect(engine).get_table_names()


def test_rejects_non_sqlite_database():
    engine = create_engine("sqlite:///:memory:", future=True)
    engine.dialect.name = "postgresql"

    with pytest.raises(ValueError, match="SQLite"):
        migrate_buyback_plan_event_tables(engine)


def test_reference_check_detects_orphan_plan():
    engine = create_engine("sqlite:///:memory:", future=True)
    migrate_buyback_plan_event_tables(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO buyback_plans "
                "(buyback_plan_id, code, origin_event_uid, lifecycle_status, created_at) "
                "VALUES ('p1', '1234', 'missing', 'ACTIVE', '2026-11-16')"
            )
        )

    with pytest.raises(RuntimeError, match="起点イベントのない案件"):
        verify_buyback_plan_event_references(engine)


def test_verify_schema_detects_missing_table():
    engine = create_engine("sqlite:///:memory:", future=True)

    with pytest.raises(RuntimeError, match="buyback_events: テーブルがありません"):
        verify_buyback_plan_event_schema(engine)


def test_verify_schema_detects_missing_index():
    engine = create_engine("sqlite:///:memory:", future=True)
    migrate_buyback_plan_event_tables(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX ix_buyback_events_url"))

    with pytest.raises(RuntimeError, match="ix_buyback_events_url"):
        verify_buyback_plan_event_schema(engine)
