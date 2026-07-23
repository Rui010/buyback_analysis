from sqlalchemy import create_engine, text
import pandas as pd

from buyback_analysis.interface.logger import Logger

logger = Logger()

INCLUDE_KEYWORD = "決算短信"
EXCLUDE_KEYWORDS = ["四半期", "訂正", "一部", "中間"]
TARGET_MARKETS = ["プライム", "スタンダード", "グロース"]

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

_SELECT_COLUMNS_WITH_BRANDS = """
    SELECT
          "public"."tdnet"."time" AS "time"
        , "public"."tdnet"."code" AS "code"
        , "public"."tdnet"."name" AS "name"
        , "public"."tdnet"."title" AS "title"
        , "public"."tdnet"."link" AS "link"
        , "public"."tdnet"."date" AS "date"
    FROM "public"."tdnet"
    JOIN "public"."Brands" ON "public"."Brands"."code" = "public"."tdnet"."code"
"""


def _filter_by_title(df: pd.DataFrame) -> pd.DataFrame:
    filtered_df = df[df["title"].str.contains(INCLUDE_KEYWORD, na=False)]
    for keyword in EXCLUDE_KEYWORDS:
        filtered_df = filtered_df[~filtered_df["title"].str.contains(keyword, na=False)]
    return filtered_df


def get_tdnet_earnings_baseline_data_by_urls(
    engine: create_engine,
    urls: list,
) -> pd.DataFrame:
    """指定 URL リストに一致する tdnet レコードを取得する（日付フィルタ・market絞り込みなし）。"""
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


def get_tdnet_earnings_baseline_data(
    engine: create_engine,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """
    Get TDnet earnings baseline data from the database.

    タイトルに「決算短信」を含み「四半期」「訂正」「一部」「中間」のいずれも含まず、
    Brands.marketがプライム/スタンダード/グロースのいずれかの行のみを対象とする。

    Args:
        engine (create_engine): SQLAlchemy engine to connect to the database.
        start_date (str): Start date in YYYY-MM-DD format.
        end_date (str): End date in YYYY-MM-DD format.
    Returns:
        pd.DataFrame: Earnings baseline data.
    """
    market_placeholders = ", ".join([f":m{i}" for i in range(len(TARGET_MARKETS))])
    query_text = text(
        f'{_SELECT_COLUMNS_WITH_BRANDS}'
        ' WHERE "public"."tdnet"."date" <= :end_date'
        ' AND "public"."tdnet"."date" >= :start_date'
        f' AND "public"."Brands"."market" IN ({market_placeholders})'
        ' ORDER BY "public"."tdnet"."date" ASC'
    )
    params = {"end_date": end_date, "start_date": start_date}
    params.update({f"m{i}": market for i, market in enumerate(TARGET_MARKETS)})
    try:
        with engine.connect() as connection:
            df = pd.read_sql_query(query_text, connection, params=params)
        return _filter_by_title(df)
    except Exception as e:
        logger.error(f"Error fetching data: {e}")
        return pd.DataFrame()
