from sqlalchemy.orm import Session
from buyback_analysis.models.announcement import Announcement
from buyback_analysis.models.progress import Progress
from buyback_analysis.models.completion import Completion
from buyback_analysis.models.is_checked import IsChecked
from buyback_analysis.usecase.logger import Logger


logger = Logger()


def data_exists(session: Session, url: str) -> bool:
    """
    Check if the data already exists in the database.

    Args:
        url (str): The URL of the data to check.

    Returns:
        bool: True if the data exists, False otherwise.
    """

    try:
        if session.query(IsChecked).filter(IsChecked.url == url).first():
            return True
        # Announcement テーブルで URL を検索
        if session.query(Announcement).filter(Announcement.url == url).first():
            return True
        # Progress テーブルで URL を検索
        if session.query(Progress).filter(Progress.url == url).first():
            return True
        # Completion テーブルで URL を検索
        if session.query(Completion).filter(Completion.url == url).first():
            return True
        return False
    except Exception as e:
        logger.error(f"データの存在確認に失敗しました: {e}")
        return False
