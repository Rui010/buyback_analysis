from dotenv import load_dotenv
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from buyback_analysis.models.base import Base


load_dotenv()
DATABASE_URL = os.getenv("SQLITE_DB_URL")
if not DATABASE_URL:
    raise Exception("DATABASE_URL が設定されていません")
# エンジン作成（echo=True にするとSQLログが表示されて便利）
engine = create_engine(DATABASE_URL, echo=False, future=True)

# セッションのファクトリ
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


# テーブルを作成（なければ）
def init_db():
    Base.metadata.create_all(bind=engine)
