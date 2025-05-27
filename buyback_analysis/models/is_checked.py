from sqlalchemy import Column, String, Integer
from buyback_analysis.models.base import Base


class IsChecked(Base):
    __tablename__ = "is_checked"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String)
    url = Column(String)
    detected_type = Column(String)
