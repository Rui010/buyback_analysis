from sqlalchemy import Column, String, Date, BigInteger
from buyback_analysis.models.base import Base


class Announcement(Base):
    __tablename__ = "announcements"

    code = Column(String, primary_key=True)
    disclosure_date = Column(Date, primary_key=True)
    company_name = Column(String)
    buyback_method = Column(String)
    share_type = Column(String)
    buyback_amount_yen = Column(BigInteger)
    buyback_shares = Column(BigInteger)
    start_date = Column(Date)
    end_date = Column(Date)
