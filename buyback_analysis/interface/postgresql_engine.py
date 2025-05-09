from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from dotenv import load_dotenv
import os

from buyback_analysis.usecase.logger import Logger

load_dotenv()

POSTGRESQL_DB_HOST = os.getenv("POSTGRESQL_DB_HOST")
POSTGRESQL_DB_PORT = os.getenv("POSTGRESQL_DB_PORT")
POSTGRESQL_DB_NAME = os.getenv("POSTGRESQL_DB_NAME")
POSTGRESQL_DB_USER = os.getenv("POSTGRESQL_DB_USER")
POSTGRESQL_DB_PASSWORD = os.getenv("POSTGRESQL_DB_PASSWORD")

logger = Logger()


def get_database_engine():
    connection_str = f"postgresql://{POSTGRESQL_DB_USER}:{POSTGRESQL_DB_PASSWORD}@{POSTGRESQL_DB_HOST}:{POSTGRESQL_DB_PORT}/{POSTGRESQL_DB_NAME}"
    try:
        engine = create_engine(connection_str)
        # 接続テスト
        with engine.connect() as connection:
            logger.info("データベースへの接続に成功しました")
        return engine
    except OperationalError as e:
        logger.error(f"データベースへの接続に失敗しました: {e}")
        raise RuntimeError(
            "データベースへの接続に失敗しました。設定を確認してください。"
        )
