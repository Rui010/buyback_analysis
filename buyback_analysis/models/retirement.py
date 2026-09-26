from sqlalchemy import Column, String, BigInteger
from buyback_analysis.models.base import Base


class Retirement(Base):
    __tablename__ = "retirements"

    url = Column(String, primary_key=True)
    code = Column(String, nullable=False, index=True)
    disclosure_date = Column(String, nullable=False, index=True)
    retirement_date = Column(String, nullable=False)
    company_name = Column(String)
    share_type = Column(String)
    retirement_shares = Column(BigInteger)
