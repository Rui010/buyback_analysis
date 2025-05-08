from buyback_analysis.interface.postgresql_engine import get_database_engine
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

    title = "自己株式取得に係る事項の決定に関するお知らせ"
    content = get_pdf_data(
        url="https://www.release.tdnet.info/inbs/140120250430528070.pdf",
        pud_date_str="2025430",
    )
    code = "4362"
    name = "日本精化"
    print(parse_text_by_llm(title, content, code, name, "buyback.md"))
