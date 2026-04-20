"""
完了データ バックフィルスクリプト

buyback_completion テーブルの過去レコードを修正済みプロンプト（completion.md）で
再抽出し、DELETE → INSERT で上書きする。

再実行時は checkpoint ファイル（backfill_completion_checkpoint.txt）に記録済みの
URL をスキップするため、途中失敗後の再実行が安全に行える。

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
CHECKPOINT_FILE = os.path.join(os.path.dirname(__file__), "backfill_completion_checkpoint.txt")
logger = Logger()


def load_checkpoint() -> set[str]:
    if not os.path.exists(CHECKPOINT_FILE):
        return set()
    with open(CHECKPOINT_FILE, encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def save_checkpoint(url: str) -> None:
    with open(CHECKPOINT_FILE, "a", encoding="utf-8") as f:
        f.write(url + "\n")


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

    done_urls = load_checkpoint()
    if done_urls:
        logger.info(f"チェックポイント読み込み: {len(done_urls)} 件スキップ")

    total = 0
    success = 0
    skipped = 0
    failed = 0

    completion_columns = {c.key for c in Completion.__mapper__.column_attrs}

    try:
        records = session.query(Completion).all()
        logger.info(f"completion テーブル総件数: {len(records)} 件")

        urls = [r.url for r in records if r.url]
        tdnet_map = fetch_tdnet_info_by_urls(pg_engine, urls)

        for record in records:
            total += 1
            url = record.url

            if not url:
                logger.error(f"URL が NULL のためスキップ: code={record.code}, disclosure_date={record.disclosure_date}")
                skipped += 1
                continue

            if url in done_urls:
                logger.info(f"処理済みのためスキップ: {url}")
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

            code, disclosure_date = record.code, record.disclosure_date

            # DELETE → INSERT（resolution_date が NULL のレコードに対応するため生SQLで削除）
            session.execute(text("DELETE FROM completion WHERE url = :url"), {"url": url})
            session.flush()
            session.expunge(record)  # セッションの追跡から切り離す

            filtered = {k: v for k, v in new_data.items() if k in completion_columns}
            session.add(Completion(**filtered))
            session.commit()

            save_checkpoint(url)
            logger.info(f"上書き完了: code={code}, disclosure_date={disclosure_date}")
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

    if failed == 0:
        logger.info("全件完了。チェックポイントファイルを削除しても安全です。")


if __name__ == "__main__":
    main()
