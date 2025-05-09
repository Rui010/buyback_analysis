from sqlalchemy.orm import Session
from buyback_analysis.models.announcement import Announcement
from buyback_analysis.models.progress import Progress
from buyback_analysis.models.completion import Completion


def data_exists(session: Session, url: str) -> bool:
    """
    Check if the data already exists in the database.

    Args:
        url (str): The URL of the data to check.

    Returns:
        bool: True if the data exists, False otherwise.
    """

    try:
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
    finally:
        session.close()
