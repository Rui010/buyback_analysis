from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Column, DateTime, String

from buyback_analysis.models.base import Base


def _utc_now():
    return datetime.now(timezone.utc)


class BuybackPlan(Base):
    __tablename__ = "buyback_plans"
    __table_args__ = (
        CheckConstraint(
            "lifecycle_status IN ('ACTIVE', 'INVALIDATED_ORIGIN')",
            name="ck_buyback_plan_lifecycle_status",
        ),
    )

    buyback_plan_id = Column(String, primary_key=True)
    code = Column(String, nullable=False, index=True)
    origin_event_uid = Column(String, nullable=False, unique=True)
    lifecycle_status = Column(String, nullable=False, default="ACTIVE")
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utc_now)
