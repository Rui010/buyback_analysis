from sqlalchemy import Column, String, Integer, UniqueConstraint
from buyback_analysis.models.base import Base


class IsChecked(Base):
    __tablename__ = "is_checked"
    __table_args__ = (UniqueConstraint("url", name="uq_is_checked_url"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String)
    url = Column(String)
    detected_type = Column(String)
    parse_status = Column(String, default="saved")  # saved / failed / pending / skipped
