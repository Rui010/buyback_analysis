import os

os.environ.setdefault("LOG_FILE", "midterm_plan_analysis.log")

from dotenv import load_dotenv

from buyback_analysis.interface.postgresql_engine import get_database_engine
from buyback_analysis.interface.sqlite_engine import SessionLocal, init_db
from buyback_analysis.usecase.get_pdf_data import get_pdf_data
from buyback_analysis.usecase.get_pdf_path import get_pdf_path
from buyback_analysis.interface.logger import Logger
from buyback_analysis.interface.notifier import notify_success, notify_error
from midterm_plan_analysis.models.midterm_plan import MidtermPlan  # noqa: F401 init_db() に登録するためインポート
from midterm_plan_analysis.models.midterm_plan_keyword import MidtermPlanKeyword  # noqa: F401 init_db() に登録するためインポート
from midterm_plan_analysis.usecase.get_midterm_plans_missing_keywords import (
    get_midterm_plans_missing_keywords,
)
from midterm_plan_analysis.usecase.get_tdnet_midterm_data import get_tdnet_midterm_data_by_urls
from midterm_plan_analysis.usecase.extract_midterm_keywords import extract_midterm_keywords
from midterm_plan_analysis.usecase.extract_midterm_keywords_native import extract_midterm_keywords_native
from midterm_plan_analysis.usecase.post_midterm_keywords import post_midterm_keywords

load_dotenv()

PDF_DOWNLOAD_PATH = os.getenv("PDF_DOWNLOAD_PATH")
USE_NATIVE_PDF = os.getenv("MIDTERM_USE_NATIVE_PDF", "false").lower() == "true"
BACKFILL_LIMIT = int(os.getenv("MIDTERM_BACKFILL_KEYWORDS_LIMIT", "50"))

logger = Logger()


def main():
    """
    metrics抽出は既に成功しているがkeyword抽出が未実施のmidterm_plans行に対し、
    keyword抽出だけを実行してmidterm_plan_keywordsを埋める（過去データのバックフィル用）。

    1回の実行あたりの対象件数はBACKFILL_LIMITで制御する。処理済みの行は次回呼び出し時に
    自動的に対象から外れるため、同じコマンドを繰り返し実行するだけで続きから再開できる。
    """
    session = SessionLocal()

    total_processed = 0
    succeeded = 0
    failed_pdf = 0
    failed_extract = 0
    skipped_missing_source = 0

    try:
        init_db()

        targets = get_midterm_plans_missing_keywords(session=session, limit=BACKFILL_LIMIT)
        logger.info(f"[Backfill] 対象件数: {len(targets)}件（上限{BACKFILL_LIMIT}件・開示日が新しい順）")

        if not targets:
            notify_success("midterm_plan_analysis(keywords backfill)", "対象0件")
            return

        postgresql_engine = get_database_engine()
        urls = [plan.url for plan in targets]
        df = get_tdnet_midterm_data_by_urls(engine=postgresql_engine, urls=urls)
        title_name_by_url = {row["link"]: (row["title"], row["name"]) for _, row in df.iterrows()}

        for plan in targets:
            total_processed += 1

            if plan.url not in title_name_by_url:
                logger.error(f"[Backfill] tdnetにソースが見つかりませんでした: {plan.url}")
                skipped_missing_source += 1
                continue
            title, name = title_name_by_url[plan.url]
            pud_date_str = (plan.disclosure_date or "").replace("-", "")

            if USE_NATIVE_PDF:
                pdf_path = get_pdf_path(url=plan.url, pud_date_str=pud_date_str, save_dir=PDF_DOWNLOAD_PATH)
                if pdf_path is None:
                    logger.error(f"[Backfill] PDFの取得に失敗しました: {plan.url}")
                    failed_pdf += 1
                    continue
                keywords_obj = extract_midterm_keywords_native(
                    title=title, pdf_path=pdf_path, code=plan.code, name=name
                )
            else:
                content = get_pdf_data(url=plan.url, pud_date_str=pud_date_str, save_dir=PDF_DOWNLOAD_PATH)
                if content is None:
                    logger.error(f"[Backfill] PDFの取得に失敗しました: {plan.url}")
                    failed_pdf += 1
                    continue
                keywords_obj = extract_midterm_keywords(
                    title=title, content=content, code=plan.code, name=name
                )

            if keywords_obj is None:
                logger.error(f"[Backfill] キーワード抽出に失敗しました: {plan.url}")
                failed_extract += 1
                continue

            post_midterm_keywords(
                session=session,
                code=plan.code,
                url=plan.url,
                disclosure_date=plan.disclosure_date,
                keywords=keywords_obj.get("data", {}).get("keywords"),
            )
            succeeded += 1

        summary = (
            f"対象:{total_processed}件 / 成功:{succeeded}件 / "
            f"PDF失敗:{failed_pdf}件 / 抽出失敗:{failed_extract}件 / "
            f"ソース不明:{skipped_missing_source}件"
        )
        logger.info(f"[Backfill] {summary}")
        notify_success("midterm_plan_analysis(keywords backfill)", summary)

    except SystemExit as e:
        logger.error(f"[Backfill] 強制終了しました: {e}")
        notify_error("midterm_plan_analysis(keywords backfill)", str(e))
        raise
    except Exception as e:
        logger.error(f"[Backfill] 予期しないエラーが発生しました: {e}")
        notify_error("midterm_plan_analysis(keywords backfill)", str(e))
        raise

    finally:
        session.close()


if __name__ == "__main__":
    main()
