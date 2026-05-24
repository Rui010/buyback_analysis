from sqlalchemy import create_engine, text
import pandas as pd

from buyback_analysis.interface.logger import Logger

logger = Logger()

MIDTERM_KEYWORDS = ["経営計画", "中計"]


def get_tdnet_midterm_data(
    engine: create_engine,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """
    Get TDnet midterm plan data from the database.

    Args:
        engine (create_engine): SQLAlchemy engine to connect to the database.
        start_date (str): Start date in YYYY-MM-DD format.
        end_date (str): End date in YYYY-MM-DD format.
    Returns:
        pd.DataFrame: Midterm plan data.
    """
    query_text = text(
        """
    SELECT
          "public"."tdnet"."time" AS "time"
        , "public"."tdnet"."code" AS "code"
        , "public"."tdnet"."name" AS "name"
        , "public"."tdnet"."title" AS "title"
        , "public"."tdnet"."link" AS "link"
        , "public"."tdnet"."date" AS "date"
    FROM "public"."tdnet"
    WHERE
        "public"."tdnet"."date" <= :end_date
        AND "public"."tdnet"."date" >= :start_date
    ORDER BY "public"."tdnet"."date" ASC
    """
    )
    try:
        with engine.connect() as connection:
            df = pd.read_sql_query(
                query_text,
                connection,
                params={"end_date": end_date, "start_date": start_date},
            )
        pattern = "|".join(MIDTERM_KEYWORDS)
        filtered_df = df[df["title"].str.contains(pattern, na=False)]
        return filtered_df
    except Exception as e:
        logger.error(f"Error fetching data: {e}")
        return pd.DataFrame()
