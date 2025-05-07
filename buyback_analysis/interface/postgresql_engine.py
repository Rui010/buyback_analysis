from sqlalchemy import create_engine
from dotenv import load_dotenv
import os

load_dotenv()

POSTGRESQL_DB_HOST = os.getenv("POSTGRESQL_DB_HOST")
POSTGRESQL_DB_PORT = os.getenv("POSTGRESQL_DB_PORT")
POSTGRESQL_DB_NAME = os.getenv("POSTGRESQL_DB_NAME")
POSTGRESQL_DB_USER = os.getenv("POSTGRESQL_DB_USER")
POSTGRESQL_DB_PASSWORD = os.getenv("POSTGRESQL_DB_PASSWORD")


def get_database_engine():
    connection_str = f"postgresql://{POSTGRESQL_DB_USER}:{POSTGRESQL_DB_PASSWORD}@{POSTGRESQL_DB_HOST}:{POSTGRESQL_DB_PORT}/{POSTGRESQL_DB_NAME}"
    return create_engine(connection_str)
