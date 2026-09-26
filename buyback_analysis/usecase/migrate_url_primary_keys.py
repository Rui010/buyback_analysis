"""自己株買い4テーブルをURL主キーへ移行するSQLite専用ユーティリティ。"""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from buyback_analysis.models.announcement import Announcement
from buyback_analysis.models.completion import Completion
from buyback_analysis.models.progress import Progress
from buyback_analysis.models.retirement import Retirement


_MODELS = (Announcement, Completion, Progress, Retirement)


def migrate_url_primary_keys(engine: Engine) -> list[str]:
    """既存行を保持したまま、対象テーブルの主キーをURLへ置換する。

    移行前にURLのNULL/空文字と重複、前回失敗時の ``bk_`` 退避表を検査する。
    問題があれば一切変更せず ``ValueError`` を送出する。
    """
    if engine.dialect.name != "sqlite":
        raise ValueError("URL主キー移行はSQLiteでのみ実行できます")

    existing_tables = set(inspect(engine).get_table_names())
    targets = [model for model in _MODELS if model.__tablename__ in existing_tables]
    has_is_checked = "is_checked" in existing_tables
    if not targets and not has_is_checked:
        return []

    for model in targets:
        table_name = model.__tablename__
        backup_name = f"bk_{table_name}"
        if backup_name in existing_tables:
            raise ValueError(
                f"退避テーブル {backup_name} が残っているため移行を中止しました"
            )
        with engine.connect() as connection:
            invalid_urls = connection.execute(
                text(f"SELECT COUNT(*) FROM {table_name} WHERE url IS NULL OR TRIM(url) = ''")
            ).scalar_one()
            duplicate_urls = connection.execute(
                text(
                    f"SELECT COUNT(*) FROM ("
                    f"SELECT url FROM {table_name} GROUP BY url HAVING COUNT(*) > 1"
                    f")"
                )
            ).scalar_one()
        if invalid_urls or duplicate_urls:
            raise ValueError(
                f"{table_name}: URL不正 {invalid_urls}件、URL重複 {duplicate_urls}件のため移行を中止しました"
            )

    if has_is_checked:
        with engine.connect() as connection:
            duplicate_urls = connection.execute(
                text(
                    "SELECT COUNT(*) FROM ("
                    "SELECT url FROM is_checked WHERE url IS NOT NULL "
                    "GROUP BY url HAVING COUNT(*) > 1"
                    ")"
                )
            ).scalar_one()
        if duplicate_urls:
            raise ValueError(
                f"is_checked: URL重複 {duplicate_urls}件のため移行を中止しました"
            )

    migrated = []
    with engine.begin() as connection:
        if has_is_checked:
            is_checked_columns = {
                column["name"] for column in inspect(connection).get_columns("is_checked")
            }
            if "parse_status" not in is_checked_columns:
                connection.execute(
                    text(
                        "ALTER TABLE is_checked ADD COLUMN parse_status VARCHAR "
                        "NOT NULL DEFAULT 'saved'"
                    )
                )
            connection.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS uq_is_checked_url ON is_checked (url)")
            )
            migrated.append("is_checked")

        for model in targets:
            table_name = model.__tablename__
            backup_name = f"bk_{table_name}"
            columns = ", ".join(column.name for column in model.__table__.columns)

            connection.execute(text(f"ALTER TABLE {table_name} RENAME TO {backup_name}"))
            model.__table__.create(bind=connection, checkfirst=False)
            connection.execute(
                text(f"INSERT INTO {table_name} ({columns}) SELECT {columns} FROM {backup_name}")
            )
            connection.execute(text(f"DROP TABLE {backup_name}"))
            migrated.append(table_name)

    return migrated
