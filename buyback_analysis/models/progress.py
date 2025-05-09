from sqlalchemy import Column, String, Date, BigInteger
from buyback_analysis.models.base import Base


class Progress(Base):
    __tablename__ = "progress"

    code = Column(String, primary_key=True)
    disclosure_date = Column(String, primary_key=True)
    url = Column(String)
    company_name = Column(String)
    cumulative_shares_acquired = Column(BigInteger)
    cumulative_amount_spent_yen = Column(BigInteger)
    period_start = Column(String)
    period_end = Column(String)
