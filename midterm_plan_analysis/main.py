import os

os.environ.setdefault("LOG_FILE", "midterm_plan_analysis.log")

import datetime
from dotenv import load_dotenv

from buyback_analysis.interface.postgresql_engine import get_database_engine
from buyback_analysis.interface.sqlite_engine import SessionLocal, init_db
from buyback_analysis.usecase.get_pdf_data import get_pdf_data
from buyback_analysis.usecase.get_pdf_path import get_pdf_path
from buyback_analysis.usecase.parse_text_by_llm import parse_text_by_llm
from buyback_analysis.usecase.parse_pdf_by_llm import parse_pdf_by_llm
from buyback_analysis.interface.logger import Logger
from midterm_plan_analysis.models.midterm_plan import MidtermPlan  # init_db() に登録するためインポート
from midterm_plan_analysis.usecase.get_tdnet_midterm_data import (
    get_tdnet_midterm_data,
    get_tdnet_midterm_data_by_urls,
)
from midterm_plan_analysis.usecase.post_midterm_plan import post_midterm_plan
from buyback_analysis.usecase.classify_midterm_by_llm import classify_midterm_by_llm
from buyback_analysis.interface.notifier import notify_success, notify_error

load_dotenv()

PDF_DOWNLOAD_PATH = os.getenv("PDF_DOWNLOAD_PATH")
DAYS_BACK = int(os.getenv("DAYS_BACK", "5"))
SYSTEM_START_DATE = os.getenv("SYSTEM_START_DATE")
SYSTEM_END_DATE = os.getenv("SYSTEM_END_DATE")

USE_NATIVE_PDF = os.getenv("MIDTERM_USE_NATIVE_PDF", "false").lower() == "true"
RERUN_URLS = [u.strip() for u in os.getenv("RERUN_URLS", "").split(",") if u.strip()]

logger = Logger()


def _already_exists(session, code: str, url: str) -> bool:
    return session.get(MidtermPlan, {"code": code, "url": url}) is not None


def main():
    session = SessionLocal()

    total_processed = 0
    successful_saves = 0
    skipped_duplicates = 0
    failed_pdf = 0
    failed_parse = 0

    try:
        init_db()
        postgresql_engine = get_database_engine()

        if SYSTEM_START_DATE and SYSTEM_END_DATE:
            start_date = SYSTEM_START_DATE
            end_date = SYSTEM_END_DATE
            logger.info(f"データ取得期間（環境変数指定）: {start_date} ～ {end_date}")
        else:
            today = datetime.date.today()
            start_date = (today - datetime.timedelta(days=DAYS_BACK)).strftime("%Y-%m-%d")
            end_date = today.strftime("%Y-%m-%d")
            logger.info(f"データ取得期間（過去{DAYS_BACK}日）: {start_date} ～ {end_date}")

        if RERUN_URLS:
            logger.info(f"強制再実行モード: {len(RERUN_URLS)}件のURLを対象に既存データを削除して再処理します")
            for url in RERUN_URLS:
                session.query(MidtermPlan).filter(MidtermPlan.url == url).delete()
            session.commit()
            df = get_tdnet_midterm_data_by_urls(engine=postgresql_engine, urls=RERUN_URLS)
        else:
            df = get_tdnet_midterm_data(
                engine=postgresql_engine,
                start_date=start_date,
                end_date=end_date,
            )
        logger.info(f"取得対象レコード数: {len(df)}件")

        for _, row in df.iterrows():
            total_processed += 1
            code = str(row["code"])
            url = row["link"]
            disclosure_date = row["date"].strftime("%Y-%m-%d")

            if _already_exists(session, code, url):
                logger.info(f"処理済みのためスキップ: {code} - {url}")
                skipped_duplicates += 1
                continue

            title = row["title"]
            name = row["name"]

            if USE_NATIVE_PDF:
                pdf_path = get_pdf_path(
                    url=url,
                    pud_date_str=row["date"].strftime("%Y%m%d"),
                    save_dir=PDF_DOWNLOAD_PATH,
                )
                if pdf_path is None:
                    logger.error(f"PDFの取得に失敗しました: {url}")
                    post_midterm_plan(
                        session=session, data={}, code=code, url=url,
                        disclosure_date=disclosure_date, extraction_status="failed",
                    )
                    failed_pdf += 1
                    continue
                obj = parse_pdf_by_llm(
                    title=title,
                    pdf_path=pdf_path,
                    code=code,
                    name=name,
                    prompt_filename="midterm_plan_native.md",
                )
                content = None
            else:
                content = get_pdf_data(
                    url=url,
                    pud_date_str=row["date"].strftime("%Y%m%d"),
                    save_dir=PDF_DOWNLOAD_PATH,
                )
                if content is None:
                    logger.error(f"PDFの取得に失敗しました: {url}")
                    post_midterm_plan(
                        session=session, data={}, code=code, url=url,
                        disclosure_date=disclosure_date, extraction_status="failed",
                    )
                    failed_pdf += 1
                    continue
                obj = parse_text_by_llm(
                    title=title,
                    content=content,
                    code=code,
                    name=name,
                    prompt_filename="midterm_plan.md",
                )

            if obj is None:
                logger.error(f"LLMによるパースに失敗しました: {url}")
                post_midterm_plan(
                    session=session, data={}, code=code, url=url,
                    disclosure_date=disclosure_date, extraction_status="failed",
                )
                failed_parse += 1
                continue

            metrics = obj.get("data", {}).get("metrics")
            has_metrics = bool(metrics) and any(
                m.get("value") is not None for m in metrics
            )

            WITHDRAWN_KEYWORDS = ["取り下げ", "廃止", "撤回"]
            POSTPONED_KEYWORDS = ["延期", "見送り"]
            if any(kw in title for kw in WITHDRAWN_KEYWORDS):
                extraction_status = "withdrawn"
            elif has_metrics:
                extraction_status = "ok"
            elif any(kw in title for kw in POSTPONED_KEYWORDS):
                extraction_status = "postponed"
            else:
                classify_content = content or ""
                extraction_status = classify_midterm_by_llm(
                    title=title, content=classify_content, code=code, name=name
                )

            post_midterm_plan(
                session=session,
                data=obj,
                code=code,
                url=url,
                disclosure_date=disclosure_date,
                extraction_status=extraction_status,
            )
            logger.info(f"保存完了 [{extraction_status}]: {code} - {title}")
            successful_saves += 1

        logger.info("=" * 60)
        logger.info("【処理サマリー】")
        logger.info(f"  総処理件数:      {total_processed}件")
        logger.info(f"  正常保存:        {successful_saves}件")
        logger.info(f"  重複スキップ:    {skipped_duplicates}件")
        logger.info(f"  PDF取得失敗:     {failed_pdf}件")
        logger.info(f"  パース/判定失敗: {failed_parse}件")
        logger.info("=" * 60)

        summary = (
            f"総処理:{total_processed}件 / 保存:{successful_saves}件 / "
            f"重複スキップ:{skipped_duplicates}件 / "
            f"PDF失敗:{failed_pdf}件 / パース失敗:{failed_parse}件"
        )
        notify_success("midterm_plan_analysis", summary)

    except SystemExit as e:
        logger.error(f"パイプラインが強制終了しました: {e}")
        notify_error("midterm_plan_analysis", str(e))
        raise
    except Exception as e:
        logger.error(f"パイプラインで予期しないエラーが発生しました: {e}")
        notify_error("midterm_plan_analysis", str(e))
        raise

    finally:
        session.close()


if __name__ == "__main__":
    main()
