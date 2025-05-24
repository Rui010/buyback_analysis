from enum import Enum


class DetectType(Enum):
    BUYBACK_ANNOUNCEMENT = "buyback_announcement"
    BUYBACK_PROGRESS = "buyback_progress"
    BUYBACK_COMPLETION = "buyback_completion"
    EQUITY_COMPENSATION = "equity_compensation"
    STRATEGIC_TRANSACTION = "strategic_transaction"
    OTHER = "other"
