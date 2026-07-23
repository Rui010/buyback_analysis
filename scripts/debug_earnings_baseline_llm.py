"""
決算短信起点データ LLM 応答 Dry run スクリプト

PostgreSQL から直接データを取得し、DB への書き込みなしで
parse_pdf_by_llm() の返り値を確認する（ネイティブPDF方式のみ）。

使い方:
    python -m scripts.debug_earnings_baseline_llm          # 直近3件
    python -m scripts.debug_earnings_baseline_llm --limit 5
    python -m scripts.debug_earnings_baseline_llm --url https://...
"""

import argparse
import json
import os
from dotenv import load_dotenv
from sqlalchemy import text

from buyback_analysis.interface.postgresql_engine import get_database_engine
from buyback_analysis.usecase.get_pdf_path import get_pdf_path
from buyback_analysis.usecase.parse_pdf_by_llm import parse_pdf_by_llm
from buyback_analysis.interface.logger import Logger
from earnings_baseline_analysis.usecase.get_tdnet_earnings_baseline_data import get_tdnet_earnings_baseline_data

load_dotenv()

logger = Logger()
PDF_DOWNLOAD_PATH = os.getenv("PDF_DOWNLOAD_PATH")
DAYS_BACK = int(os.getenv("DAYS_BACK", "5"))


def run(limit: int, url: str | None) -> None:
    pg_engine = get_database_engine()

    if url:
        query = text(
            """
            SELECT code, name, title, link, date
            FROM public.tdnet
            WHERE link = :url
            LIMIT 1
            """
        )
        with pg_engine.connect() as conn:
            row = conn.execute(query, {"url": url}).mappings().first()
        rows = [dict(row)] if row else []
    else:
        import datetime
        today = datetime.date.today()
        start_date = (today - datetime.timedelta(days=DAYS_BACK)).strftime("%Y-%m-%d")
        end_date = today.strftime("%Y-%m-%d")
        df = get_tdnet_earnings_baseline_data(pg_engine, start_date=start_date, end_date=end_date)
        rows = df.head(limit).to_dict(orient="records")

    if not rows:
        logger.info("対象レコードが見つかりませんでした")
        return

    logger.info(f"対象: {len(rows)} 件")

    for row in rows:
        logger.info(f"--- {row['code']} | {row['title']}")

        pdf_path = get_pdf_path(
            url=row["link"],
            pud_date_str=row["date"].strftime("%Y%m%d"),
            save_dir=PDF_DOWNLOAD_PATH,
        )
        if pdf_path is None:
            logger.error(f"PDF 取得失敗: {row['link']}")
            continue

        result = parse_pdf_by_llm(
            title=row["title"],
            pdf_path=pdf_path,
            code=str(row["code"]),
            name=row["name"],
            prompt_filename="earnings_baseline_native.md",
        )

        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=3, help="取得件数（デフォルト: 3）")
    parser.add_argument("--url", type=str, default=None, help="特定の URL を指定")
    args = parser.parse_args()

    run(limit=args.limit, url=args.url)
