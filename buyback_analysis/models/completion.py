from sqlalchemy import Column, String, Date, Float, BigInteger
from buyback_analysis.models.base import Base


class Completion(Base):
    __tablename__ = "completion"

    code = Column(String, primary_key=True)
    disclosure_date = Column(String, primary_key=True)
    url = Column(String)
    company_name = Column(String)
    start_date = Column(String)
    end_date = Column(String)
    shares_acquired = Column(Float)
    amount_spent_yen = Column(BigInteger)
    buyback_method = Column(BigInteger)
