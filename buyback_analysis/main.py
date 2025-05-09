from buyback_analysis.interface.postgresql_engine import get_database_engine
from buyback_analysis.interface.sqlite_engine import init_db
from buyback_analysis.usecase.data_exists import data_exists
from buyback_analysis.usecase.logger import Logger
from buyback_analysis.usecase.post_data import post_data
from buyback_analysis.usecase.get_tdnet_buyback_data import get_tdnet_buyback_data
from buyback_analysis.usecase.get_pdf_data import get_pdf_data
from buyback_analysis.usecase.parse_text_by_llm import parse_text_by_llm
from buyback_analysis.usecase.detect_type import detect_type_by_llm

logger = Logger()


def main():
    init_db()  # DBの初期化
    postgresql_engine = get_database_engine()
    df = get_tdnet_buyback_data(
        engine=postgresql_engine,
        start_date="2025-05-01",
        end_date="2025-05-07",
    )
    for index, row in df.iterrows():

        if data_exists(row["link"]):
            logger.info(f"データが既に存在します: {row['code']} - {row['date']}")
            continue

        content = get_pdf_data(
            url=row["link"],
            pud_date_str=row["date"].strftime("%Y%m%d"),
        )
        if content is None:
            logger.error(f"PDFの取得に失敗しました: {row['link']}")
            continue
        detect_type = detect_type_by_llm(row["title"], content)

        if detect_type == "announcement":
            obj = parse_text_by_llm(
                row["title"], content, row["code"], row["name"], "announcement.md"
            )
        elif detect_type == "progress":
            obj = parse_text_by_llm(
                row["title"], content, row["code"], row["name"], "progress.md"
            )
        elif detect_type == "completion":
            obj = parse_text_by_llm(
                row["title"], content, row["code"], row["name"], "completion.md"
            )
        else:
            print(f"タイプの判定に失敗しました: {row['link']}")
            continue

        obj["url"] = row["link"]
        post_data(obj)


if __name__ == "__main__":
    main()
