from buyback_analysis.interface.postgresql_engine import get_database_engine
from buyback_analysis.interface.sqlite_engine import init_db
from buyback_analysis.usecase.post_data import post_data
from buyback_analysis.usecase.get_tdnet_buyback_data import get_tdnet_buyback_data
from buyback_analysis.usecase.get_pdf_data import get_pdf_data
from buyback_analysis.usecase.parse_text_by_llm import parse_text_by_llm


def main():
    postgresql_engine = get_database_engine()
    df = get_tdnet_buyback_data(
        engine=postgresql_engine,
        start_date="2025-04-01",
        end_date="2025-05-07",
    )
    print(df.head())


if __name__ == "__main__":
    init_db()  # DBの初期化
    postgresql_engine = get_database_engine()
    df = get_tdnet_buyback_data(
        engine=postgresql_engine,
        start_date="2025-05-01",
        end_date="2025-05-07",
    )
    for index, row in df.iterrows():
        content = get_pdf_data(
            url=row["link"],
            pud_date_str=row["date"].strftime("%Y%m%d"),
        )
        if content is None:
            print(f"PDFの取得に失敗しました: {row['link']}")
            continue
        obj = parse_text_by_llm(
            row["title"], content, row["code"], row["name"], "buyback.md"
        )
        post_data(obj)
