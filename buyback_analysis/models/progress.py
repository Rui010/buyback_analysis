from sqlalchemy import Column, String, Date, BigInteger
from buyback_analysis.models.base import Base


class Progress(Base):
    __tablename__ = "progress"

    url = Column(String, primary_key=True)
    code = Column(String, nullable=False, index=True)
    disclosure_date = Column(String, nullable=False, index=True)
    company_name = Column(String)
    cumulative_shares_acquired = Column(BigInteger)
    cumulative_amount_spent_yen = Column(BigInteger)
    period_start = Column(String)
    period_end = Column(String)
