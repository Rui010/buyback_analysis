from sqlalchemy import create_engine, text
import pandas as pd

from buyback_analysis.interface.logger import Logger
from buyback_analysis.interface.notifier import notify_success
from earnings_baseline_analysis.usecase.get_tdnet_earnings_baseline_data import TARGET_MARKETS

logger = Logger()

_SELECT_COLUMNS = """
    SELECT
          "public"."tdnet"."code" AS "code"
        , "public"."tdnet"."name" AS "name"
        , "public"."tdnet"."title" AS "title"
        , "public"."tdnet"."link" AS "link"
        , "public"."tdnet"."date" AS "date"
    FROM "public"."tdnet"
    JOIN "public"."Brands" ON "public"."Brands"."code" = "public"."tdnet"."code"
"""


def get_earnings_baseline_corrections(
    engine: create_engine,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """
    決算短信の訂正・一部訂正告知（四半期を除く）を取得する。

    earnings_baseline_analysisの抽出パイプライン（get_tdnet_earnings_baseline_data）は
    タイトルに「訂正」「一部」を含む行を除外しているため、この関数で除外側を別途取得し
    日次Slack通知の対象とする。抽出パイプラインと同様にBrands.marketをプライム/スタンダード/
    グロースに絞り込む（絞り込まないと抽出対象外の市場の訂正まで通知に混ざるため）。

    Args:
        engine: SQLAlchemy engine
        start_date: 開始日（YYYY-MM-DD）
        end_date: 終了日（YYYY-MM-DD）
    Returns:
        pd.DataFrame: 訂正告知データ
    """
    market_placeholders = ", ".join([f":m{i}" for i in range(len(TARGET_MARKETS))])
    query_text = text(
        f'{_SELECT_COLUMNS}'
        ' WHERE "public"."tdnet"."date" <= :end_date'
        ' AND "public"."tdnet"."date" >= :start_date'
        f' AND "public"."Brands"."market" IN ({market_placeholders})'
        ' ORDER BY "public"."tdnet"."date" ASC'
    )
    params = {"end_date": end_date, "start_date": start_date}
    params.update({f"m{i}": market for i, market in enumerate(TARGET_MARKETS)})
    try:
        with engine.connect() as connection:
            df = pd.read_sql_query(
                query_text,
                connection,
                params=params,
            )
        filtered_df = df[
            df["title"].str.contains("決算短信", na=False)
            & ~df["title"].str.contains("四半期", na=False)
            & (
                df["title"].str.contains("訂正", na=False)
                | df["title"].str.contains("一部", na=False)
            )
        ]
        return filtered_df
    except Exception as e:
        logger.error(f"Error fetching data: {e}")
        return pd.DataFrame()


def notify_earnings_baseline_corrections(
    engine: create_engine,
    start_date: str,
    end_date: str,
) -> int:
    """
    決算短信の訂正・一部訂正告知を日次サマリーとしてSlack通知する。

    LLM抽出・DB保存は行わない軽量チェック（interface/notifier.pyのnotify_successを使用）。
    該当0件の場合は通知しない。

    Returns:
        通知した件数
    """
    df = get_earnings_baseline_corrections(engine, start_date, end_date)
    if len(df) == 0:
        return 0

    lines = [f"{row['code']} {row['title']}\n{row['link']}" for _, row in df.iterrows()]
    detail = f"本日の決算短信訂正: {len(df)}件\n" + "\n".join(lines)
    notify_success("earnings_baseline_corrections", detail)
    return len(df)
