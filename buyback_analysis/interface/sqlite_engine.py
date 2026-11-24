from dotenv import load_dotenv
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from buyback_analysis.models.base import Base
# init_db()単独でもPhase 1の新規テーブルをmetadataへ登録する。
from buyback_analysis.models.buyback_event import BuybackEvent  # noqa: F401
from buyback_analysis.models.buyback_event_link_decision import (  # noqa: F401
    BuybackEventLinkDecision,
)
from buyback_analysis.models.buyback_plan import BuybackPlan  # noqa: F401
from buyback_analysis.models.buyback_plan_projection import (  # noqa: F401
    BuybackPlanProjection,
)
# フロント提供用の派生表。init_db()のcreate_all()で本番にも作られる（migration不要）
from buyback_analysis.models.announcement_plan_status import (  # noqa: F401
    AnnouncementPlanStatus,
)


load_dotenv()
DATABASE_URL = os.getenv("SQLITE_DB_URL")
if not DATABASE_URL:
    raise Exception("SQLITE_DB_URL が設定されていません")
# エンジン作成（echo=True にするとSQLログが表示されて便利）
engine = create_engine(DATABASE_URL, echo=False, future=True)

# セッションのファクトリ
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


# テーブルを作成（なければ）
def init_db():
    Base.metadata.create_all(bind=engine)
