from sqlalchemy.orm import Session

from buyback_analysis.models.announcement import Announcement
from buyback_analysis.models.completion import Completion
from buyback_analysis.models.correction import Correction
from buyback_analysis.models.is_checked import IsChecked
from buyback_analysis.models.progress import Progress
from buyback_analysis.models.retirement import Retirement
from buyback_analysis.interface.logger import Logger

logger = Logger()

_IR_MODELS = [Announcement, Progress, Completion, Correction, Retirement]


def delete_by_url(session: Session, url: str) -> None:
    """指定 URL のデータを全 IR テーブルおよび is_checked から削除する。"""
    try:
        for Model in _IR_MODELS:
            session.query(Model).filter(Model.url == url).delete()
        session.query(IsChecked).filter(IsChecked.url == url).delete()
        session.commit()
        logger.info(f"既存データを削除しました（強制再実行）: {url}")
    except Exception as e:
        session.rollback()
        logger.error(f"データの削除に失敗しました: {url} - {e}")
        raise
