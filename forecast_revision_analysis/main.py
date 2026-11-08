import os

os.environ.setdefault("LOG_FILE", "forecast_revision_analysis.log")

import datetime
import pandas as pd
from dotenv import load_dotenv

from buyback_analysis.interface.postgresql_engine import get_database_engine
from buyback_analysis.interface.sqlite_engine import SessionLocal, init_db
from buyback_analysis.interface.logger import Logger
from buyback_analysis.interface.notifier import notify_success, notify_error
from forecast_revision_analysis.models.forecast_revision_detail import ForecastRevisionDetail  # noqa: F401 init_db() に登録するためインポート
from forecast_revision_analysis.models.forecast_revision_metric import ForecastRevisionMetric  # noqa: F401 init_db() に登録するためインポート
from forecast_revision_analysis.usecase.get_tdnet_forecast_revision_data import (
    get_tdnet_forecast_revision_data,
    get_tdnet_forecast_revision_data_by_urls,
)
from forecast_revision_analysis.usecase.post_forecast_revision import check_missing_fields, _to_float
from forecast_revision_analysis.usecase.retry_failed import already_processed, get_failed_urls
from forecast_revision_analysis.usecase.run_forecast_revision_stages import (
    record_withdrawn_route,
    run_stage1_and_stage2,
)
from forecast_revision_analysis.usecase.save_forecast_result import FORECAST_TABLES, save_forecast_result
from tdnet_provenance.usecase.adopt_result import current_is_failed, require_provenance_for_rerun
from tdnet_provenance.usecase.prepare_pdf_input import prepare_pdf_input
from tdnet_provenance.usecase.provenance_recorder import ProvenanceRecorder

load_dotenv()

PDF_DOWNLOAD_PATH = os.getenv("PDF_DOWNLOAD_PATH")
DAYS_BACK = int(os.getenv("DAYS_BACK", "5"))
SYSTEM_START_DATE = os.getenv("SYSTEM_START_DATE")
SYSTEM_END_DATE = os.getenv("SYSTEM_END_DATE")
USE_NATIVE_PDF = os.getenv("FORECAST_REVISION_USE_NATIVE_PDF", "false").lower() == "true"
RERUN_URLS = [u.strip() for u in os.getenv("RERUN_URLS", "").split(",") if u.strip()]

CORRECTION_KEYWORDS = ["訂正"]

logger = Logger()


def _already_exists(session, code: str, url: str) -> bool:
    return already_processed(session, code, url)


def _determine_extraction_status(obj: dict | None) -> str:
    if obj is None:
        return "failed"
    periods = obj.get("data", {}).get("periods", [])
    if any(_to_float(p.get("prev_value")) != _to_float(p.get("curr_value")) for p in periods):
        return "ok"
    return "no_periods"


def main():
    session = SessionLocal()

    total_processed = 0
    successful_saves = 0
    skipped_duplicates = 0
    failed_pdf = 0
    failed_parse = 0
    missing_fields_count = 0
    missing_details = []
    failed_saves = 0

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
            df = get_tdnet_forecast_revision_data_by_urls(engine=postgresql_engine, urls=RERUN_URLS)
        else:
            df = get_tdnet_forecast_revision_data(
                engine=postgresql_engine,
                start_date=start_date,
                end_date=end_date,
            )
            failed_urls = get_failed_urls(session)
            if failed_urls:
                retry_df = get_tdnet_forecast_revision_data_by_urls(
                    engine=postgresql_engine, urls=failed_urls,
                )
                logger.info(f"failed再試行候補: {len(failed_urls)}件 / TDnet取得: {len(retry_df)}件")
                df = pd.concat([df, retry_df], ignore_index=True).drop_duplicates(subset=["code", "link"])
        logger.info(f"取得対象レコード数: {len(df)}件")

        for _, row in df.iterrows():
            total_processed += 1
            code = str(row["code"])
            url = row["link"]
            disclosure_date = row["date"].strftime("%Y-%m-%d")
            title = row["title"]
            name = row["name"]
            date_str = row["date"].strftime("%Y%m%d")

            if not RERUN_URLS and _already_exists(session, code, url):
                logger.info(f"処理済みのためスキップ: {code} - {url}")
                skipped_duplicates += 1
                continue
            if recorder is not None:
                recorder.start_document(url, retry=current_is_failed(session, FORECAST_TABLES, url))

            if record_withdrawn_route(recorder, url=url, title=title):
                saved = save_forecast_result(
                    session, recorder, code=code, url=url, disclosure_date=disclosure_date,
                    data={}, extraction_status="withdrawn",
                )
                if saved:
                    logger.info(f"保存完了 [withdrawn]: {code} - {title}")
                    successful_saves += 1
                else:
                    logger.error(f"保存失敗 [withdrawn]: {code} - {title}")
                    failed_parse += 1
                continue

            # provenance有効時は台帳照合済みのPDFだけをnative/textの両経路で使う
            pdf_input = prepare_pdf_input(
                recorder, url=url, disclosure_date=row["date"], time=row["time"],
                pud_date_str=date_str, pdf_root=PDF_DOWNLOAD_PATH,
                use_native=USE_NATIVE_PDF, stage="stage1",
            )
            if pdf_input is None:
                logger.error(f"PDFの取得に失敗しました: {url}")
                saved = save_forecast_result(
                    session, recorder, code=code, url=url, disclosure_date=disclosure_date,
                    data={}, extraction_status="failed",
                )
                if saved:
                    failed_saves += 1
                else:
                    logger.error(f"failed状態の保存失敗: {code} - {url}")
                failed_pdf += 1
                continue

            obj = run_stage1_and_stage2(recorder, pdf_input, title=title, code=code, name=name)

            if obj is not None and any(kw in title for kw in CORRECTION_KEYWORDS):
                extraction_status = "correction"
            else:
                extraction_status = _determine_extraction_status(obj)

            if extraction_status == "failed":
                logger.error(f"LLMによるパースに失敗しました: {url}")
                failed_parse += 1

            saved = save_forecast_result(
                session, recorder, code=code, url=url, disclosure_date=disclosure_date,
                data=obj or {}, extraction_status=extraction_status,
            )
            if saved:
                logger.info(f"保存完了 [{extraction_status}]: {code} - {title}")
                if extraction_status == "failed":
                    failed_saves += 1
                else:
                    successful_saves += 1
                if extraction_status == "ok" and check_missing_fields(obj or {}, code, url, details=missing_details):
                    missing_fields_count += 1
            else:
                logger.error(f"保存失敗: {code} - {title}")
                failed_parse += 1

        summary = (
            f"総処理:{total_processed}件 / 保存（failed除外）:{successful_saves}件 / failed保存:{failed_saves}件 / "
            f"重複スキップ:{skipped_duplicates}件 / "
            f"PDF失敗:{failed_pdf}件 / パース失敗:{failed_parse}件 / "
            f"欠損データ:{missing_fields_count}件"
        )
        notify_success("forecast_revision_analysis", summary)

    except SystemExit as e:
        logger.error(f"パイプラインが強制終了しました: {e}")
        notify_error("forecast_revision_analysis", str(e))
        raise
    except Exception as e:
        logger.error(f"パイプラインで予期しないエラーが発生しました: {e}")
        notify_error("forecast_revision_analysis", str(e))
        raise

    finally:
        try:
            logger.info("=" * 60)
            logger.info("【処理サマリー】")
            logger.info(f"  総処理件数:      {total_processed}件")
            logger.info(f"  保存（failed除外）:        {successful_saves}件")
            logger.info(f"  重複スキップ:    {skipped_duplicates}件")
            logger.info(f"  PDF取得失敗:     {failed_pdf}件")
            logger.info(f"  パース/判定失敗: {failed_parse}件")
            logger.info(f"  欠損データ:      {missing_fields_count}件")
            logger.info(f"  failed状態の保存: {failed_saves}件")
            for detail in missing_details:
                logger.info(f"  [欠損内訳] {detail}")
            logger.info("=" * 60)
        finally:
            session.close()


if __name__ == "__main__":
    main()
