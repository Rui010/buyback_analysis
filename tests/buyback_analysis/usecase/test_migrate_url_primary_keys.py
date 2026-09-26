from sqlalchemy import create_engine, inspect, text
import pytest

from buyback_analysis.usecase.migrate_url_primary_keys import migrate_url_primary_keys


_OLD_TABLES = {
    "announcements": """
        code TEXT NOT NULL, disclosure_date TEXT NOT NULL, resolution_date TEXT,
        url TEXT, company_name TEXT, buyback_method TEXT, share_type TEXT,
        buyback_amount_yen BIGINT, buyback_shares BIGINT, start_date TEXT, end_date TEXT,
        status TEXT, PRIMARY KEY (code, disclosure_date)
    """,
    "completion": """
        code TEXT NOT NULL, disclosure_date TEXT NOT NULL, resolution_date TEXT,
        url TEXT, company_name TEXT, start_date TEXT, end_date TEXT, shares_acquired FLOAT,
        amount_spent_yen BIGINT, buyback_method TEXT, PRIMARY KEY (code, disclosure_date)
    """,
    "progress": """
        code TEXT NOT NULL, disclosure_date TEXT NOT NULL, url TEXT, company_name TEXT,
        cumulative_shares_acquired BIGINT, cumulative_amount_spent_yen BIGINT,
        period_start TEXT, period_end TEXT, PRIMARY KEY (code, disclosure_date)
    """,
    "retirements": """
        code TEXT NOT NULL, disclosure_date TEXT NOT NULL, retirement_date TEXT NOT NULL,
        url TEXT, company_name TEXT, share_type TEXT, retirement_shares BIGINT,
        PRIMARY KEY (code, disclosure_date, retirement_date)
    """,
}


def _old_engine():
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as connection:
        for table_name, definition in _OLD_TABLES.items():
            connection.execute(text(f"CREATE TABLE {table_name} ({definition})"))
    return engine


def test_migrate_url_primary_keys_preserves_same_code_same_day_rows():
    engine = _old_engine()
    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO announcements (code, disclosure_date, url, company_name)
            VALUES ('1803', '2026-09-24', 'https://example.test/one.pdf', '清水建設')
        """))

    assert migrate_url_primary_keys(engine) == list(_OLD_TABLES)

    inspector = inspect(engine)
    assert inspector.get_pk_constraint("announcements")["constrained_columns"] == ["url"]
    assert {index["name"] for index in inspector.get_indexes("announcements")} >= {
        "ix_announcements_code",
        "ix_announcements_disclosure_date",
    }
    with engine.connect() as connection:
        assert "bk_announcements" not in inspect(connection).get_table_names()

    # 旧PKでは弾かれた同一銘柄・同一開示日の別URLを保存できる。
    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO announcements (code, disclosure_date, url, company_name)
            VALUES ('1803', '2026-09-24', 'https://example.test/two.pdf', '清水建設')
        """))
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM announcements")).scalar_one() == 2


def test_migrate_url_primary_keys_rejects_duplicate_urls_without_changes():
    engine = _old_engine()
    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO announcements (code, disclosure_date, url)
            VALUES ('1111', '2026-09-24', 'https://example.test/duplicate.pdf')
        """))
        connection.execute(text("""
            INSERT INTO completion (code, disclosure_date, url)
            VALUES ('2222', '2026-09-24', 'https://example.test/duplicate.pdf')
        """))
        connection.execute(text("""
            INSERT INTO progress (code, disclosure_date, url)
            VALUES ('3333', '2026-09-24', 'https://example.test/progress.pdf')
        """))
        connection.execute(text("""
            INSERT INTO retirements (code, disclosure_date, retirement_date, url)
            VALUES ('4444', '2026-09-24', '2026-09-24', 'https://example.test/retirement.pdf')
        """))

    # テーブル内で重複させる（旧PKの範囲では許容される）。
    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO announcements (code, disclosure_date, url)
            VALUES ('1111', '2026-09-25', 'https://example.test/duplicate.pdf')
        """))

    with pytest.raises(ValueError, match="announcements"):
        migrate_url_primary_keys(engine)

    assert inspect(engine).get_pk_constraint("announcements")["constrained_columns"] == [
        "code", "disclosure_date"
    ]


def test_migrate_adds_parse_status_and_url_unique_index_to_legacy_is_checked():
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE is_checked (
                id INTEGER PRIMARY KEY, code TEXT, url TEXT, detected_type TEXT
            )
        """))
        connection.execute(text("""
            INSERT INTO is_checked (id, code, url, detected_type)
            VALUES (1, '1803', 'https://example.test/one.pdf', 'buyback_announcement')
        """))

    assert migrate_url_primary_keys(engine) == ["is_checked"]

    with engine.connect() as connection:
        columns = {row[1]: row for row in connection.execute(text("PRAGMA table_info(is_checked)"))}
        assert columns["parse_status"][3] == 1
        assert connection.execute(text("SELECT parse_status FROM is_checked")).scalar_one() == "saved"
        indexes = {row[1] for row in connection.execute(text("PRAGMA index_list(is_checked)"))}
        assert "uq_is_checked_url" in indexes
