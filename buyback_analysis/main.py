from buyback_analysis.interface.postgresql_engine import get_database_engine
from buyback_analysis.interface.sqlite_engine import SessionLocal, init_db
from buyback_analysis.usecase.data_exists import data_exists
from buyback_analysis.usecase.logger import Logger
from buyback_analysis.usecase.post_data import post_data
from buyback_analysis.usecase.get_tdnet_buyback_data import get_tdnet_buyback_data
from buyback_analysis.usecase.get_pdf_data import get_pdf_data
from buyback_analysis.usecase.parse_text_by_llm import parse_text_by_llm
from buyback_analysis.usecase.detect_type import detect_type_by_llm
from buyback_analysis.consts.detect_type import DetectType
from buyback_analysis.usecase.post_url import post_url

logger = Logger()
session = SessionLocal()


def main():
    init_db()  # DBの初期化
    postgresql_engine = get_database_engine()
    df = get_tdnet_buyback_data(
        engine=postgresql_engine,
        start_date="2025-04-01",
        end_date="2025-05-08",
    )
    for index, row in df.iterrows():

        if data_exists(session, row["link"]):
            logger.info(f"データが既に存在します: {row['code']} - {row['date']}")
            continue

        content = get_pdf_data(
            url=row["link"],
            pud_date_str=row["date"].strftime("%Y%m%d"),
        )
        if content is None:
            logger.error(f"PDFの取得に失敗しました: {row['link']}")
            continue

        detect_type_str = detect_type_by_llm(row["title"], content)
        try:
            detect_type_enum = DetectType(detect_type_str)
        except ValueError:
            print(f"タイプの判定に失敗しました: {row['link']}")
            continue
        post_url(
            session,
            row["code"],
            row["link"],
            detect_type_enum.value,
        )
        logger.info(f"{row["code"]} - {row["title"]} - {detect_type_enum.value}")

        if detect_type_enum not in [
            DetectType.BUYBACK_ANNOUNCEMENT,
            DetectType.BUYBACK_PROGRESS,
            DetectType.BUYBACK_COMPLETION,
        ]:
            logger.error(f"対象外: {row['title']}")
            continue

        template_map = {
            DetectType.BUYBACK_ANNOUNCEMENT: "announcement.md",
            DetectType.BUYBACK_PROGRESS: "progress.md",
            DetectType.BUYBACK_COMPLETION: "completion.md",
        }

        obj = parse_text_by_llm(
            row["title"],
            content,
            row["code"],
            row["name"],
            template_map[detect_type_enum],
        )
        if obj is None:
            logger.error(f"LLMによるパースに失敗しました: {row['link']}")
            continue
        obj["data"]["url"] = row["link"]
        post_data(session, obj)
        logger.info(f"データを保存しました: {row['code']} - {row['date']}")

    session.close()
    logger.info("全てのデータを処理しました")


if __name__ == "__main__":
    main()
