from sqlalchemy import Column, String, Float, BigInteger
from buyback_analysis.models.base import Base


class Completion(Base):
    __tablename__ = "completion"

    url = Column(String, primary_key=True)
    code = Column(String, nullable=False, index=True)
    disclosure_date = Column(String, nullable=False, index=True)
    resolution_date = Column(String)
    company_name = Column(String)
    start_date = Column(String)
    end_date = Column(String)
    shares_acquired = Column(Float)
    amount_spent_yen = Column(BigInteger)
    buyback_method = Column(String)
