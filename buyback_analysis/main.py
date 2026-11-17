import os

os.environ.setdefault("LOG_FILE", "buyback_analysis.log")

import datetime
from dotenv import load_dotenv
from buyback_analysis.interface.postgresql_engine import get_database_engine
from buyback_analysis.interface.sqlite_engine import SessionLocal, init_db
from buyback_analysis.usecase.data_exists import data_exists_in_ir_tables
from buyback_analysis.interface.logger import Logger
from buyback_analysis.usecase.get_tdnet_buyback_data import get_tdnet_buyback_data
from buyback_analysis.usecase.get_pdf_data import get_pdf_data
from buyback_analysis.usecase.get_pdf_path import get_pdf_path
from buyback_analysis.usecase.parse_text_by_llm import parse_text_by_llm
from buyback_analysis.usecase.parse_pdf_by_llm import parse_pdf_by_llm
from buyback_analysis.usecase.detect_type import (
    detect_type_by_llm,
    get_detect_type_in_db,
)
from buyback_analysis.consts.detect_type import DetectType
from buyback_analysis.usecase.post_url import update_parse_status
from buyback_analysis.usecase.buyback_result_writer import BuybackResultWriter
from buyback_analysis.usecase.get_tdnet_buyback_data import get_tdnet_buyback_data_by_urls
from buyback_analysis.interface.notifier import notify_success, notify_error
from buyback_analysis.usecase.process_buyback_event_document import (
    process_buyback_event_document,
)
from buyback_analysis.usecase.save_buyback_event_result import (
    has_buyback_event_result,
)
from buyback_analysis.usecase.save_legacy_buyback_compatibility import (
    requires_legacy_llm,
    save_legacy_buyback_compatibility,
)
from tdnet_provenance.usecase.adopt_result import require_provenance_for_rerun
from tdnet_provenance.usecase.prepare_pdf_input import prepare_pdf_input
from tdnet_provenance.usecase.provenance_recorder import ProvenanceRecorder

load_dotenv()

PDF_DOWNLOAD_PATH = os.getenv("PDF_DOWNLOAD_PATH")

# データ取得期間の柔軟化：環境変数で指定可能
DAYS_BACK = int(os.getenv("DAYS_BACK", "5"))  # デフォルト5日
SYSTEM_START_DATE = os.getenv("SYSTEM_START_DATE")  # YYYY-MM-DD形式
SYSTEM_END_DATE = os.getenv("SYSTEM_END_DATE")    # YYYY-MM-DD形式

USE_NATIVE_PDF = os.getenv("BUYBACK_USE_NATIVE_PDF", "false").lower() == "true"
RERUN_URLS = [u.strip() for u in os.getenv("RERUN_URLS", "").split(",") if u.strip()]
SINGLE_LLM_ENABLED = os.getenv("BUYBACK_SINGLE_LLM_ENABLED", "false").lower() == "true"

REQUIRED_FIELDS = {
    DetectType.BUYBACK_ANNOUNCEMENT: ["buyback_shares", "buyback_amount_yen"],
    DetectType.BUYBACK_PROGRESS: ["cumulative_shares_acquired", "cumulative_amount_spent_yen"],
    DetectType.BUYBACK_COMPLETION: ["shares_acquired", "amount_spent_yen"],
    DetectType.RETIREMENT: ["retirement_date"],
    DetectType.CORRECTION: ["original_announcement_date"],
}

logger = Logger()


def _needs_native_fallback(obj, detect_type_enum: DetectType) -> bool:
    """テキストパース結果がネイティブPDFフォールバックを要するか判定する。"""
    if obj is None or obj.get("data") is None:
        return True
    data = obj["data"]
    for field in REQUIRED_FIELDS.get(detect_type_enum, []):
        if data.get(field) is None:
            return True
    return False


def main():
    session = SessionLocal()

    # 処理サマリー用カウンター
    total_processed = 0
    successful_saves = 0
    skipped_duplicates = 0
    skipped_out_of_scope = 0
    failed_pdf = 0
    failed_parse = 0
    failed_integrity = 0
    failed_event = 0

    try:
        init_db()  # DBの初期化
        recorder = ProvenanceRecorder.from_env(session)
        if SINGLE_LLM_ENABLED and recorder is None:
            raise RuntimeError(
                "BUYBACK_SINGLE_LLM_ENABLED=trueにはTDNET_PROVENANCE_ENABLED=trueが必要です"
            )
        require_provenance_for_rerun(recorder, RERUN_URLS)
        writer = BuybackResultWriter(session, rerun=bool(RERUN_URLS))
        postgresql_engine = get_database_engine()

        # 開始日・終了日の決定
        if SYSTEM_START_DATE and SYSTEM_END_DATE:
            # 環境変数で明示的に指定された場合
            start_date = SYSTEM_START_DATE
            end_date = SYSTEM_END_DATE
            logger.info(f"データ取得期間（環境変数指定）: {start_date} ～ {end_date}")
        else:
            # デフォルト：過去N日
            today = datetime.date.today()
            start_date = (today - datetime.timedelta(days=DAYS_BACK)).strftime("%Y-%m-%d")
            end_date = today.strftime("%Y-%m-%d")
            logger.info(f"データ取得期間（過去{DAYS_BACK}日）: {start_date} ～ {end_date}")

        if RERUN_URLS:
            # 旧結果は削除しない。文書種別の判定からやり直し、成功した場合だけ採用版を切り替える
            logger.info(f"強制再実行モード: {len(RERUN_URLS)}件のURLを再処理します（成功時のみ採用版を切り替え）")
            df = get_tdnet_buyback_data_by_urls(engine=postgresql_engine, urls=RERUN_URLS)
        else:
            df = get_tdnet_buyback_data(
                engine=postgresql_engine,
                start_date=start_date,
                end_date=end_date,
            )

        logger.info(f"取得対象レコード数: {len(df)}件")

        for _, row in df.iterrows():
            total_processed += 1
            code = str(row["code"])
            url = row["link"]
            event_result_exists = (
                recorder is not None and has_buyback_event_result(session, url)
            )
            needs_event_processing = (
                recorder is not None
                and not (SINGLE_LLM_ENABLED and requires_legacy_llm(row["title"]))
                and (bool(RERUN_URLS) or not event_result_exists)
            )

            # saved/skipped は PDF取得前にスキップ（不要なダウンロードを回避）
            # RERUN時はDBの判定結果を使わず、種別判定からやり直す
            detect_type_str = None if RERUN_URLS else get_detect_type_in_db(session, url)
            if detect_type_str is not None:
                try:
                    detect_type_enum = DetectType(detect_type_str)
                except ValueError:
                    logger.error(f"DBに登録されているタイプ値が不正です: {row['link']}")
                    failed_parse += 1
                    continue
                if data_exists_in_ir_tables(session, url) and not needs_event_processing:
                    logger.info(f"データが既に存在します: {row['code']} - {row['date']}")
                    update_parse_status(session, url, "saved")
                    skipped_duplicates += 1
                    continue
                if detect_type_enum not in [
                    DetectType.BUYBACK_ANNOUNCEMENT,
                    DetectType.BUYBACK_PROGRESS,
                    DetectType.BUYBACK_COMPLETION,
                    DetectType.CORRECTION,
                    DetectType.RETIREMENT,
                ] and not needs_event_processing:
                    logger.info(f"対象外スキップ: {row['title']}")
                    update_parse_status(session, row["link"], "skipped")
                    skipped_out_of_scope += 1
                    continue

            pdf_input = None
            if needs_event_processing:
                recorder.start_document(url)
                pdf_input = prepare_pdf_input(
                    recorder,
                    url=url,
                    disclosure_date=row["date"],
                    time=row["time"],
                    pud_date_str=row["date"].strftime("%Y%m%d"),
                    pdf_root=PDF_DOWNLOAD_PATH,
                    use_native=False,
                    stage="events",
                )
                content = None if pdf_input is None else pdf_input.content
            else:
                content = get_pdf_data(
                    url=url,
                    pud_date_str=row["date"].strftime("%Y%m%d"),
                    save_dir=PDF_DOWNLOAD_PATH,
                )
            if content is None:
                logger.error(f"PDFの取得に失敗しました: {url}")
                failed_pdf += 1
                continue

            if needs_event_processing:
                disclosure_datetime = f"{row['date'].strftime('%Y-%m-%d')}T{row['time']}"
                event_saved = process_buyback_event_document(
                    session,
                    recorder,
                    pdf_input.source,
                    title=row["title"],
                    content=content,
                    code=code,
                    name=row["name"],
                    url=url,
                    disclosure_datetime=disclosure_datetime,
                )
                if event_saved:
                    logger.info(f"[BuybackEvents] 保存・紐づけ完了: {code} - {url}")
                else:
                    logger.error(f"[BuybackEvents] 保存・紐づけ失敗: {code} - {url}")
                    failed_event += 1

                if (
                    SINGLE_LLM_ENABLED
                    and event_saved
                    and not requires_legacy_llm(row["title"])
                ):
                    compatibility_saved = save_legacy_buyback_compatibility(
                        session,
                        code=code,
                        url=url,
                        disclosure_date=row["date"].strftime("%Y-%m-%d"),
                        company_name=row["name"],
                        rerun=bool(RERUN_URLS),
                    )
                    if compatibility_saved:
                        logger.info(
                            f"[LegacyCompatibility] LLMなしで互換保存完了: {code} - {url}"
                        )
                        successful_saves += 1
                        continue
                    logger.error(
                        f"[LegacyCompatibility] 互換保存失敗、従来LLMへフォールバック: {code} - {url}"
                    )

            if not RERUN_URLS and data_exists_in_ir_tables(session, url):
                logger.info(f"従来形式は処理済みのためスキップ: {code} - {row['date']}")
                update_parse_status(session, url, "saved")
                skipped_duplicates += 1
                continue

            if detect_type_str is None:
                detect_type_str = detect_type_by_llm(row["title"], content)
                try:
                    detect_type_enum = DetectType(detect_type_str)
                except ValueError:
                    logger.error(f"タイプの判定に失敗しました: {row['link']}")
                    failed_parse += 1
                    continue
                writer.register_type(row["code"], row["link"], detect_type_enum.value)
                logger.info(f"{row["code"]} - {row["title"]} - {detect_type_enum.value}")
            else:
                try:
                    detect_type_enum = DetectType(detect_type_str)
                except ValueError:
                    logger.error(f"DBに登録されているタイプ値が不正です: {row['link']}")
                    failed_parse += 1
                    continue

            if not RERUN_URLS and data_exists_in_ir_tables(session, row["link"]):
                logger.info(f"データが既に存在します: {row['code']} - {row['date']}")
                update_parse_status(session, row["link"], "saved")
                skipped_duplicates += 1
                continue

            if detect_type_enum not in [
                DetectType.BUYBACK_ANNOUNCEMENT,
                DetectType.BUYBACK_PROGRESS,
                DetectType.BUYBACK_COMPLETION,
                DetectType.CORRECTION,
                DetectType.RETIREMENT,
            ]:
                logger.info(f"対象外スキップ: {row['title']}")
                writer.mark(row["link"], "skipped")
                skipped_out_of_scope += 1
                continue

            template_map = {
                DetectType.BUYBACK_ANNOUNCEMENT: "announcement.md",
                DetectType.BUYBACK_PROGRESS: "progress.md",
                DetectType.BUYBACK_COMPLETION: "completion.md",
                DetectType.CORRECTION: "correction.md",
                DetectType.RETIREMENT: "retirement.md",
            }
            native_template_map = {
                DetectType.BUYBACK_ANNOUNCEMENT: "announcement_native.md",
                DetectType.BUYBACK_PROGRESS: "progress_native.md",
                DetectType.BUYBACK_COMPLETION: "completion_native.md",
                DetectType.CORRECTION: "correction_native.md",
                DetectType.RETIREMENT: "retirement_native.md",
            }

            if USE_NATIVE_PDF:
                pdf_path = get_pdf_path(
                    url=row["link"],
                    pud_date_str=row["date"].strftime("%Y%m%d"),
                    save_dir=PDF_DOWNLOAD_PATH,
                )
                obj = parse_pdf_by_llm(
                    row["title"],
                    pdf_path,
                    row["code"],
                    row["name"],
                    native_template_map[detect_type_enum],
                )
            else:
                obj = parse_text_by_llm(
                    row["title"],
                    content,
                    row["code"],
                    row["name"],
                    template_map[detect_type_enum],
                )
                # パース失敗または必須フィールド不足時はネイティブPDFでフォールバック
                if _needs_native_fallback(obj, detect_type_enum):
                    pdf_path = get_pdf_path(
                        url=row["link"],
                        pud_date_str=row["date"].strftime("%Y%m%d"),
                        save_dir=PDF_DOWNLOAD_PATH,
                    )
                    if pdf_path:
                        logger.info(f"テキストパース失敗、ネイティブPDFで再試行: {row['link']}")
                        obj = parse_pdf_by_llm(
                            row["title"],
                            pdf_path,
                            row["code"],
                            row["name"],
                            native_template_map[detect_type_enum],
                        )
            logger.info(f"Parsed object: {obj}")
            if obj is None or obj.get("data") is None:
                logger.error(f"LLMによるパースに失敗しました: {row['link']}")
                writer.mark(row["link"], "failed")
                failed_parse += 1
                continue
            obj["data"]["url"] = row["link"]
            obj["data"]["disclosure_date"] = row["date"].strftime("%Y-%m-%d")
            try:
                saved = writer.save(row["link"], obj)
            except Exception as e:
                logger.error(f"データの保存に失敗しました: {row['link']} - {e}")
                writer.mark(row["link"], "failed")
                failed_parse += 1
                continue
            if not saved:
                logger.error(f"DB制約違反によりデータを保存できませんでした: {row['link']}")
                writer.mark(row["link"], "failed")
                failed_integrity += 1
                continue
            writer.mark(row["link"], "saved")
            logger.info(f"データを保存しました: {row['code']} - {row['date']}")
            successful_saves += 1

        # 処理サマリーをログ出力
        logger.info("=" * 60)
        logger.info("【処理サマリー】")
        logger.info(f"  総処理件数:      {total_processed}件")
        logger.info(f"  正常保存:        {successful_saves}件")
        logger.info(f"  重複スキップ:    {skipped_duplicates}件")
        logger.info(f"  対象外スキップ:  {skipped_out_of_scope}件")
        logger.info(f"  PDF取得失敗:     {failed_pdf}件")
        logger.info(f"  パース/判定失敗: {failed_parse}件")
        logger.info(f"  制約違反:        {failed_integrity}件")
        logger.info(f"  イベント処理失敗:{failed_event}件")
        logger.info("=" * 60)

        summary = (
            f"総処理:{total_processed}件 / 保存:{successful_saves}件 / "
            f"重複スキップ:{skipped_duplicates}件 / 対象外:{skipped_out_of_scope}件 / "
            f"PDF失敗:{failed_pdf}件 / パース失敗:{failed_parse}件 / "
            f"制約違反:{failed_integrity}件"
            f" / イベント失敗:{failed_event}件"
        )
        if failed_parse > 0 or failed_pdf > 0 or failed_integrity > 0 or failed_event > 0:
            notify_error("buyback_analysis", summary)
        else:
            notify_success("buyback_analysis", summary)

    except SystemExit as e:
        logger.error(f"パイプラインが強制終了しました: {e}")
        notify_error("buyback_analysis", str(e))
        raise
    except Exception as e:
        logger.error(f"パイプラインで予期しないエラーが発生しました: {e}")
        notify_error("buyback_analysis", str(e))
        raise

    finally:
        session.close()


if __name__ == "__main__":
    main()
