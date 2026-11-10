import os

os.environ.setdefault("LOG_FILE", "midterm_plan_analysis.log")

import datetime
from dotenv import load_dotenv

from buyback_analysis.interface.postgresql_engine import get_database_engine
from buyback_analysis.interface.sqlite_engine import SessionLocal, init_db
from buyback_analysis.interface.logger import Logger
from midterm_plan_analysis.models.midterm_plan import MidtermPlan  # init_db() に登録するためインポート
from midterm_plan_analysis.models.midterm_plan_keyword import MidtermPlanKeyword  # noqa: F401 init_db() に登録するためインポート
from midterm_plan_analysis.usecase.get_tdnet_midterm_data import (
    get_tdnet_midterm_data,
    get_tdnet_midterm_data_by_urls,
)
from midterm_plan_analysis.usecase.determine_midterm_status import determine_midterm_status
from midterm_plan_analysis.usecase.save_midterm_result import (
    KEYWORDS_NOT_REQUESTED,
    MIDTERM_TABLES,
    save_midterm_result,
)
from midterm_plan_analysis.usecase.run_midterm_stages import (
    run_midterm_classification,
    run_midterm_keywords,
    run_midterm_metrics,
)
from buyback_analysis.interface.notifier import notify_success, notify_error
from tdnet_provenance.usecase.adopt_result import current_is_failed, require_provenance_for_rerun
from tdnet_provenance.usecase.prepare_pdf_input import prepare_pdf_input
from tdnet_provenance.usecase.provenance_recorder import ProvenanceRecorder

load_dotenv()

PDF_DOWNLOAD_PATH = os.getenv("PDF_DOWNLOAD_PATH")
DAYS_BACK = int(os.getenv("DAYS_BACK", "5"))
SYSTEM_START_DATE = os.getenv("SYSTEM_START_DATE")
SYSTEM_END_DATE = os.getenv("SYSTEM_END_DATE")

USE_NATIVE_PDF = os.getenv("MIDTERM_USE_NATIVE_PDF", "false").lower() == "true"
EXTRACT_KEYWORDS = os.getenv("MIDTERM_EXTRACT_KEYWORDS", "false").lower() == "true"
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
    failed_save = 0

    try:
        init_db()
        recorder = ProvenanceRecorder.from_env(session)
        require_provenance_for_rerun(recorder, RERUN_URLS)
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
            # 旧結果は削除しない。新しい抽出が成功した場合だけ採用版を切り替える
            logger.info(f"強制再実行モード: {len(RERUN_URLS)}件のURLを再処理します（成功時のみ採用版を切り替え）")
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

            if not RERUN_URLS and _already_exists(session, code, url):
                logger.info(f"処理済みのためスキップ: {code} - {url}")
                skipped_duplicates += 1
                continue

            title = row["title"]
            name = row["name"]
            if recorder is not None:
                recorder.start_document(url, retry=current_is_failed(session, MIDTERM_TABLES, url))

            # provenance有効時は台帳照合済みのPDFだけをnative/textの両経路で使う
            pdf_input = prepare_pdf_input(
                recorder, url=url, disclosure_date=row["date"], time=row["time"],
                pud_date_str=row["date"].strftime("%Y%m%d"), pdf_root=PDF_DOWNLOAD_PATH,
                use_native=USE_NATIVE_PDF, stage="metrics",
                page_markers=True,  # text方式ではmetricsにページの目印入りの本文を送る（keywords等は従来の本文）
            )
            if pdf_input is None:
                logger.error(f"PDFの取得に失敗しました: {url}")
                save_midterm_result(
                    session, recorder, code=code, url=url, disclosure_date=disclosure_date,
                    data={}, extraction_status="failed",
                )
                failed_pdf += 1
                continue

            obj = run_midterm_metrics(recorder, pdf_input, title=title, code=code, name=name)

            if obj is None:
                logger.error(f"LLMによるパースに失敗しました: {url}")
                save_midterm_result(
                    session, recorder, code=code, url=url, disclosure_date=disclosure_date,
                    data={}, extraction_status="failed",
                )
                failed_parse += 1
                continue

            keywords = KEYWORDS_NOT_REQUESTED
            if EXTRACT_KEYWORDS:
                keywords_obj = run_midterm_keywords(recorder, pdf_input, title=title, code=code, name=name)
                if keywords_obj is None:
                    logger.error(f"[Keywords] キーワード抽出に失敗しました: {url}")
                keywords = (keywords_obj or {}).get("data", {}).get("keywords")

            extraction_status = determine_midterm_status(
                title,
                obj.get("data", {}).get("metrics"),
                classify=lambda: run_midterm_classification(
                    recorder, pdf_input, title=title, code=code, name=name
                ),
            )

            # キーワード→計画の順に保存する（provenance有効時は1つの版として採用）
            saved = save_midterm_result(
                session, recorder, code=code, url=url, disclosure_date=disclosure_date,
                data=obj, extraction_status=extraction_status, keywords=keywords,
            )
            if saved:
                logger.info(f"保存完了 [{extraction_status}]: {code} - {title}")
                successful_saves += 1
            else:
                logger.error(f"保存失敗 [{extraction_status}]: {code} - {title}")
                failed_save += 1

        logger.info("=" * 60)
        logger.info("【処理サマリー】")
        logger.info(f"  総処理件数:      {total_processed}件")
        logger.info(f"  正常保存:        {successful_saves}件")
        logger.info(f"  重複スキップ:    {skipped_duplicates}件")
        logger.info(f"  PDF取得失敗:     {failed_pdf}件")
        logger.info(f"  パース/判定失敗: {failed_parse}件")
        logger.info(f"  保存失敗:        {failed_save}件")
        logger.info("=" * 60)

        summary = (
            f"総処理:{total_processed}件 / 保存:{successful_saves}件 / "
            f"重複スキップ:{skipped_duplicates}件 / "
            f"PDF失敗:{failed_pdf}件 / パース失敗:{failed_parse}件 / "
            f"保存失敗:{failed_save}件"
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
