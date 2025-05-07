from buyback_analysis.interface.postgresql_engine import get_database_engine
from buyback_analysis.usecase.get_tdnet_buyback_data import get_tdnet_buyback_data


def main():
    postgresql_engine = get_database_engine()
    df = get_tdnet_buyback_data(
        engine=postgresql_engine,
        start_date="2025-04-01",
        end_date="2025-05-07",
    )
    print(df.head())


if __name__ == "__main__":
    main()
