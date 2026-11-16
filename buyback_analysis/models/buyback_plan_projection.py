from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    String,
)

from buyback_analysis.models.base import Base


def _utc_now():
    return datetime.now(timezone.utc)


class BuybackPlanProjection(Base):
    __tablename__ = "buyback_plan_projections"
    __table_args__ = (
        CheckConstraint(
            "plan_status IN ('planned', 'in_progress', 'completed')",
            name="ck_buyback_plan_projection_status",
        ),
    )

    buyback_plan_id = Column(
        String, ForeignKey("buyback_plans.buyback_plan_id"), primary_key=True
    )
    original_shares = Column(BigInteger)
    original_amount_yen = Column(BigInteger)
    original_start_date = Column(String)
    original_end_date = Column(String)
    original_method = Column(String)
    current_shares = Column(BigInteger)
    current_amount_yen = Column(BigInteger)
    current_start_date = Column(String)
    current_end_date = Column(String)
    current_method = Column(String)
    cumulative_shares_acquired = Column(BigInteger)
    cumulative_amount_spent_yen = Column(BigInteger)
    completion_shares_acquired = Column(Float)
    completion_amount_spent_yen = Column(BigInteger)
    plan_status = Column(String, nullable=False)
    lifecycle_status = Column(String, nullable=False)
    is_publishable = Column(Boolean, nullable=False, default=False)
    input_fingerprint = Column(String, nullable=False)
    aggregation_rule_version = Column(String, nullable=False)
    calculated_at = Column(DateTime(timezone=True), nullable=False, default=_utc_now)
