from buyback_analysis.models.announcement import Announcement
from buyback_analysis.models.progress import Progress
from buyback_analysis.models.completion import Completion


def data_exists(url: str) -> bool:
    """
    Check if the data already exists in the database.

    Args:
        url (str): The URL of the data to check.

    Returns:
        bool: True if the data exists, False otherwise.
    """

    if Announcement.select().where(Announcement.url == url).exists():
        return True
    if Progress.select().where(Progress.url == url).exists():
        return True
    if Completion.select().where(Completion.url == url).exists():
        return True
    return False
