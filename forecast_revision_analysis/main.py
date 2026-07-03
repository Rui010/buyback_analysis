import os

os.environ.setdefault("LOG_FILE", "forecast_revision_analysis.log")

import datetime
from dotenv import load_dotenv

from buyback_analysis.interface.postgresql_engine import get_database_engine
from buyback_analysis.interface.sqlite_engine import SessionLocal, init_db
from buyback_analysis.usecase.get_pdf_data import get_pdf_data
from buyback_analysis.usecase.get_pdf_path import get_pdf_path
from buyback_analysis.interface.logger import Logger
from buyback_analysis.interface.notifier import notify_success, notify_error
from forecast_revision_analysis.models.forecast_revision_detail import ForecastRevisionDetail  # noqa: F401 init_db() に登録するためインポート
from forecast_revision_analysis.models.forecast_revision_metric import ForecastRevisionMetric  # noqa: F401 init_db() に登録するためインポート
from forecast_revision_analysis.usecase.get_tdnet_forecast_revision_data import (
    get_tdnet_forecast_revision_data,
    get_tdnet_forecast_revision_data_by_urls,
)
from forecast_revision_analysis.usecase.post_forecast_revision import post_forecast_revision, check_missing_fields, _to_float
from forecast_revision_analysis.usecase.extract_forecast_revision_stage1 import extract_forecast_revision_stage1
from forecast_revision_analysis.usecase.extract_forecast_revision_stage1_native import extract_forecast_revision_stage1_native
from forecast_revision_analysis.usecase.build_stage2_context import build_stage2_context
from forecast_revision_analysis.usecase.infer_forecast_revision_stage2 import infer_forecast_revision_stage2
from forecast_revision_analysis.usecase.merge_stage_results import merge_stage_results

load_dotenv()

PDF_DOWNLOAD_PATH = os.getenv("PDF_DOWNLOAD_PATH")
DAYS_BACK = int(os.getenv("DAYS_BACK", "5"))
SYSTEM_START_DATE = os.getenv("SYSTEM_START_DATE")
SYSTEM_END_DATE = os.getenv("SYSTEM_END_DATE")
USE_NATIVE_PDF = os.getenv("FORECAST_REVISION_USE_NATIVE_PDF", "false").lower() == "true"
RERUN_URLS = [u.strip() for u in os.getenv("RERUN_URLS", "").split(",") if u.strip()]

WITHDRAWN_KEYWORDS = ["取り下げ", "廃止", "撤回"]
CORRECTION_KEYWORDS = ["訂正"]

logger = Logger()


def _already_exists(session, code: str, url: str) -> bool:
    return session.get(ForecastRevisionDetail, {"code": code, "url": url}) is not None


def _determine_extraction_status(obj: dict | None) -> str:
    if obj is None:
        return "failed"
    periods = obj.get("data", {}).get("periods", [])
    if any(_to_float(p.get("prev_value")) != _to_float(p.get("curr_value")) for p in periods):
        return "ok"
    return "no_periods"


def _run_stage1_and_stage2(title: str, content: str | None, pdf_path: str | None, code: str, name: str) -> dict | None:
    """Stage1（抽出）を実行し、成功すればStage2（推論）を実行してマージした結果を返す。

    Stage1が失敗した場合はNoneを返す。Stage2が失敗した場合でもStage1のデータは失わない
    （direct_factors等はNoneのまま保存する。詳細はdocs/forecast_revision_llm_pipeline_redesign.md §5）。
    """
    if pdf_path is not None:
        stage1_obj = extract_forecast_revision_stage1_native(title=title, pdf_path=pdf_path, code=code, name=name)
    else:
        stage1_obj = extract_forecast_revision_stage1(title=title, content=content, code=code, name=name)

    if stage1_obj is None:
        return None

    stage2_context = build_stage2_context(stage1_obj, title=title, code=code, name=name)
    stage2_obj = infer_forecast_revision_stage2(stage2_context)
    return merge_stage_results(stage1_obj, stage2_obj)


def main():
    session = SessionLocal()

    total_processed = 0
    successful_saves = 0
    skipped_duplicates = 0
    failed_pdf = 0
    failed_parse = 0
    missing_fields_count = 0

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
                session.query(ForecastRevisionMetric).filter(ForecastRevisionMetric.url == url).delete()
                session.query(ForecastRevisionDetail).filter(ForecastRevisionDetail.url == url).delete()
            session.commit()
            df = get_tdnet_forecast_revision_data_by_urls(engine=postgresql_engine, urls=RERUN_URLS)
        else:
            df = get_tdnet_forecast_revision_data(
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
            title = row["title"]
            name = row["name"]
            date_str = row["date"].strftime("%Y%m%d")

            if _already_exists(session, code, url):
                logger.info(f"処理済みのためスキップ: {code} - {url}")
                skipped_duplicates += 1
                continue

            if any(kw in title for kw in WITHDRAWN_KEYWORDS):
                saved = post_forecast_revision(
                    session=session, data={}, code=code, url=url,
                    disclosure_date=disclosure_date, extraction_status="withdrawn",
                )
                if saved:
                    logger.info(f"保存完了 [withdrawn]: {code} - {title}")
                    successful_saves += 1
                else:
                    logger.error(f"保存失敗 [withdrawn]: {code} - {title}")
                    failed_parse += 1
                continue

            if USE_NATIVE_PDF:
                pdf_path = get_pdf_path(
                    url=url,
                    pud_date_str=date_str,
                    save_dir=PDF_DOWNLOAD_PATH,
                )
                if pdf_path is None:
                    logger.error(f"PDFの取得に失敗しました: {url}")
                    post_forecast_revision(
                        session=session, data={}, code=code, url=url,
                        disclosure_date=disclosure_date, extraction_status="failed",
                    )
                    failed_pdf += 1
                    continue
                obj = _run_stage1_and_stage2(title=title, content=None, pdf_path=pdf_path, code=code, name=name)
            else:
                content = get_pdf_data(
                    url=url,
                    pud_date_str=date_str,
                    save_dir=PDF_DOWNLOAD_PATH,
                )
                if content is None:
                    logger.error(f"PDFの取得に失敗しました: {url}")
                    post_forecast_revision(
                        session=session, data={}, code=code, url=url,
                        disclosure_date=disclosure_date, extraction_status="failed",
                    )
                    failed_pdf += 1
                    continue
                obj = _run_stage1_and_stage2(title=title, content=content, pdf_path=None, code=code, name=name)

            if any(kw in title for kw in CORRECTION_KEYWORDS):
                extraction_status = "correction"
            else:
                extraction_status = _determine_extraction_status(obj)

            if extraction_status == "failed":
                logger.error(f"LLMによるパースに失敗しました: {url}")
                failed_parse += 1

            saved = post_forecast_revision(
                session=session,
                data=obj or {},
                code=code,
                url=url,
                disclosure_date=disclosure_date,
                extraction_status=extraction_status,
            )
            if saved:
                logger.info(f"保存完了 [{extraction_status}]: {code} - {title}")
                successful_saves += 1
                if extraction_status == "ok" and check_missing_fields(obj or {}, code, url):
                    missing_fields_count += 1
            else:
                logger.error(f"保存失敗: {code} - {title}")
                failed_parse += 1

        logger.info("=" * 60)
        logger.info("【処理サマリー】")
        logger.info(f"  総処理件数:      {total_processed}件")
        logger.info(f"  正常保存:        {successful_saves}件")
        logger.info(f"  重複スキップ:    {skipped_duplicates}件")
        logger.info(f"  PDF取得失敗:     {failed_pdf}件")
        logger.info(f"  パース/判定失敗: {failed_parse}件")
        logger.info(f"  欠損データ:      {missing_fields_count}件")
        logger.info("=" * 60)

        summary = (
            f"総処理:{total_processed}件 / 保存:{successful_saves}件 / "
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
        session.close()


if __name__ == "__main__":
    main()
