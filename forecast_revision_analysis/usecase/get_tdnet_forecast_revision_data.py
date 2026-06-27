from sqlalchemy import create_engine, text
import pandas as pd

from buyback_analysis.interface.logger import Logger

logger = Logger()

FORECAST_REVISION_KEYWORDS = ["修正", "業績"]  # AND条件: 両方含む行のみ

_SELECT_COLUMNS = """
    SELECT
          "public"."tdnet"."time" AS "time"
        , "public"."tdnet"."code" AS "code"
        , "public"."tdnet"."name" AS "name"
        , "public"."tdnet"."title" AS "title"
        , "public"."tdnet"."link" AS "link"
        , "public"."tdnet"."date" AS "date"
    FROM "public"."tdnet"
"""


def get_tdnet_forecast_revision_data_by_urls(
    engine: create_engine,
    urls: list,
) -> pd.DataFrame:
    """指定 URL リストに一致する tdnet レコードを取得する（日付フィルタなし）。"""
    if not urls:
        return pd.DataFrame()
    placeholders = ", ".join([f":u{i}" for i in range(len(urls))])
    query_text = text(
        f'{_SELECT_COLUMNS} WHERE "public"."tdnet"."link" IN ({placeholders})'
        ' ORDER BY "public"."tdnet"."date" ASC'
    )
    params = {f"u{i}": url for i, url in enumerate(urls)}
    try:
        with engine.connect() as connection:
            df = pd.read_sql_query(query_text, connection, params=params)
        return df
    except Exception as e:
        logger.error(f"Error fetching data by URLs: {e}")
        return pd.DataFrame()


def get_tdnet_forecast_revision_data(
    engine: create_engine,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """
    Get TDnet forecast revision data from the database.

    Args:
        engine (create_engine): SQLAlchemy engine to connect to the database.
        start_date (str): Start date in YYYY-MM-DD format.
        end_date (str): End date in YYYY-MM-DD format.
    Returns:
        pd.DataFrame: Forecast revision data.
    """
    query_text = text(
        f'{_SELECT_COLUMNS}'
        ' WHERE "public"."tdnet"."date" <= :end_date'
        ' AND "public"."tdnet"."date" >= :start_date'
        ' ORDER BY "public"."tdnet"."date" ASC'
    )
    try:
        with engine.connect() as connection:
            df = pd.read_sql_query(
                query_text,
                connection,
                params={"end_date": end_date, "start_date": start_date},
            )
        filtered_df = df[
            df["title"].str.contains("修正", na=False)
            & df["title"].str.contains("業績", na=False)
        ]
        return filtered_df
    except Exception as e:
        logger.error(f"Error fetching data: {e}")
        return pd.DataFrame()
