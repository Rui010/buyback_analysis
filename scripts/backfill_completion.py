"""
完了データ バックフィルスクリプト

buyback_completion テーブルの過去レコードを修正済みプロンプト（completion.md）で
再抽出し、DELETE → INSERT で上書きする。

設計書: docs/backfill-completion-design.md
"""

import os
import datetime
from dotenv import load_dotenv
from sqlalchemy import text

from buyback_analysis.interface.postgresql_engine import get_database_engine
from buyback_analysis.interface.sqlite_engine import SessionLocal, init_db
from buyback_analysis.models.completion import Completion
from buyback_analysis.usecase.get_pdf_data import get_pdf_data
from buyback_analysis.usecase.parse_text_by_llm import parse_text_by_llm
from buyback_analysis.usecase.logger import Logger

load_dotenv()

PDF_DOWNLOAD_PATH = os.getenv("PDF_DOWNLOAD_PATH", "data")
logger = Logger()


def fetch_tdnet_info_by_urls(pg_engine, urls: list[str]) -> dict[str, dict]:
    """PostgreSQL から URL をキーに title・name を取得する。"""
    if not urls:
        return {}

    query = text(
        """
        SELECT link, title, name, date
        FROM public.tdnet
        WHERE link = ANY(:urls)
        """
    )
    with pg_engine.connect() as conn:
        rows = conn.execute(query, {"urls": urls}).fetchall()

    return {row.link: {"title": row.title, "name": row.name, "date": row.date} for row in rows}


def main():
    init_db()
    session = SessionLocal()
    pg_engine = get_database_engine()

    total = 0
    success = 0
    skipped = 0
    failed = 0

    try:
        records = session.query(Completion).all()
        logger.info(f"バックフィル対象レコード数: {len(records)} 件")

        urls = [r.url for r in records if r.url]
        tdnet_map = fetch_tdnet_info_by_urls(pg_engine, urls)

        for record in records:
            total += 1
            url = record.url

            if not url:
                logger.error(f"URL が NULL のためスキップ: code={record.code}, disclosure_date={record.disclosure_date}")
                skipped += 1
                continue

            tdnet = tdnet_map.get(url)
            if not tdnet:
                logger.error(f"TDnet に URL が見つからないためスキップ: {url}")
                skipped += 1
                continue

            date_str = tdnet["date"].strftime("%Y%m%d") if isinstance(tdnet["date"], datetime.date) else str(tdnet["date"]).replace("-", "")

            content = get_pdf_data(url=url, pud_date_str=date_str, save_dir=PDF_DOWNLOAD_PATH)
            if content is None:
                logger.error(f"PDF 取得失敗: {url}")
                failed += 1
                continue

            obj = parse_text_by_llm(
                title=tdnet["title"],
                content=content,
                code=record.code,
                name=tdnet["name"],
                prompt_filename="completion.md",
            )
            if obj is None:
                logger.error(f"Gemini 抽出失敗: {url}")
                failed += 1
                continue

            new_data = obj.get("data", {})
            new_data["url"] = url

            # DELETE → INSERT
            session.delete(record)
            session.flush()

            columns = {c.key for c in Completion.__mapper__.column_attrs}
            filtered = {k: v for k, v in new_data.items() if k in columns}
            session.add(Completion(**filtered))
            session.commit()

            logger.info(f"上書き完了: code={record.code}, disclosure_date={record.disclosure_date}")
            success += 1

    except Exception as e:
        session.rollback()
        logger.error(f"予期しないエラー: {e}")
        raise
    finally:
        session.close()

    logger.info("=" * 60)
    logger.info("【バックフィル サマリー】")
    logger.info(f"  総件数:     {total} 件")
    logger.info(f"  上書き成功: {success} 件")
    logger.info(f"  スキップ:   {skipped} 件")
    logger.info(f"  失敗:       {failed} 件")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
