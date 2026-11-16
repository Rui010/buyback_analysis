from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    String,
    text,
)

from buyback_analysis.models.base import Base
from buyback_analysis.models.buyback_plan import BuybackPlan  # noqa: F401


def _utc_now():
    return datetime.now(timezone.utc)


class BuybackEventLinkDecision(Base):
    __tablename__ = "buyback_event_link_decisions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('LINKED', 'UNRESOLVED', 'AMBIGUOUS')",
            name="ck_buyback_event_link_status",
        ),
        CheckConstraint(
            "decision_kind IN ('NORMAL', 'EXPIRATION')",
            name="ck_buyback_event_decision_kind",
        ),
        CheckConstraint(
            "(status = 'LINKED' AND linked_plan_id IS NOT NULL) OR "
            "(status != 'LINKED' AND linked_plan_id IS NULL)",
            name="ck_buyback_event_linked_plan_status",
        ),
        CheckConstraint(
            "(decision_kind = 'NORMAL' AND input_fingerprint IS NOT NULL) OR "
            "(decision_kind = 'EXPIRATION' AND status = 'UNRESOLVED' "
            "AND linked_plan_id IS NULL AND input_fingerprint IS NULL "
            "AND rule_version = 'expire:v1')",
            name="ck_buyback_event_decision_contract",
        ),
        Index(
            "uq_buyback_event_normal_decision_input",
            "event_uid",
            "rule_version",
            "input_fingerprint",
            unique=True,
            sqlite_where=text("decision_kind = 'NORMAL'"),
        ),
        Index(
            "uq_buyback_event_current_decision",
            "event_uid",
            unique=True,
            sqlite_where=text("is_current = 1"),
        ),
    )

    decision_id = Column(String, primary_key=True)
    event_uid = Column(
        String,
        ForeignKey("buyback_events.event_uid"),
        nullable=False,
        index=True,
    )
    status = Column(String, nullable=False)
    decision_kind = Column(String, nullable=False)
    linked_plan_id = Column(String, ForeignKey("buyback_plans.buyback_plan_id"))
    candidates = Column(JSON, nullable=False, default=list)
    reason_codes = Column(JSON, nullable=False, default=list)
    rule_version = Column(String, nullable=False)
    input_fingerprint = Column(String)
    decided_at = Column(DateTime(timezone=True), nullable=False, default=_utc_now)
    supersedes_decision_id = Column(
        String,
        ForeignKey("buyback_event_link_decisions.decision_id"),
    )
    is_current = Column(Boolean, nullable=False, default=True)
