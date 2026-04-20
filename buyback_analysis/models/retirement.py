from sqlalchemy import Column, String, BigInteger
from buyback_analysis.models.base import Base


class Retirement(Base):
    __tablename__ = "retirements"

    code = Column(String, primary_key=True)
    disclosure_date = Column(String, primary_key=True)
    retirement_date = Column(String, primary_key=True)
    url = Column(String)
    company_name = Column(String)
    share_type = Column(String)
    retirement_shares = Column(BigInteger)
