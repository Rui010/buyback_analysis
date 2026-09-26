from sqlalchemy import Column, String, BigInteger, Enum
from buyback_analysis.models.base import Base
import enum


class AnnouncementStatus(enum.Enum):
    no_correction = "no_correction"
    has_correction = "has_correction"
    corrected = "corrected"


class Announcement(Base):
    __tablename__ = "announcements"

    # 開示URLが1本のIRを一意に表す。code/date は検索用の属性として保持する。
    url = Column(String, primary_key=True)
    code = Column(String, nullable=False, index=True)
    disclosure_date = Column(String, nullable=False, index=True)
    resolution_date = Column(String)
    company_name = Column(String)
    buyback_method = Column(String)
    share_type = Column(String)
    buyback_amount_yen = Column(BigInteger)
    buyback_shares = Column(BigInteger)
    start_date = Column(String)
    end_date = Column(String)
    status = Column(
        Enum(AnnouncementStatus),
        nullable=True,  # NULLも許容する場合
        default=AnnouncementStatus.no_correction,
    )
