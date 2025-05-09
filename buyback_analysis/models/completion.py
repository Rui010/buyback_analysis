from sqlalchemy import Column, String, Date, Float, BigInteger
from buyback_analysis.models.base import Base


class Completion(Base):
    __tablename__ = "completion"

    code = Column(String, primary_key=True)
    disclosure_date = Column(String, primary_key=True)
    url = Column(String)
    company_name = Column(String)
    tender_offer_start = Column(String)
    tender_offer_end = Column(String)
    tender_offer_price = Column(Float)
    tender_offer_shares_acquired = Column(BigInteger)
    tender_offer_amount_spent_yen_acquired = Column(BigInteger)
