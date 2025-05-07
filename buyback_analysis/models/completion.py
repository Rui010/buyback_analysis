from sqlalchemy import Column, String, Date, Float, BigInteger
from buyback_analysis.models.base import Base


class Completion(Base):
    __tablename__ = "completion"

    code = Column(String, primary_key=True)
    disclosure_date = Column(Date, primary_key=True)
    company_name = Column(String)
    tender_offer_start = Column(Date)
    tender_offer_end = Column(Date)
    tender_offer_price = Column(Float)
    tender_offer_shares_acquired = Column(BigInteger)
    remaining_budget_after_tender_offer_yen = Column(BigInteger)
    planned_follow_up_method = Column(String)
