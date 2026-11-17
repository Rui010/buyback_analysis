"""Persist one adopted multi-event extraction without committing the transaction."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Callable, Sequence

from sqlalchemy.orm import Session

from buyback_analysis.models.buyback_event import BuybackEvent
from buyback_analysis.models.buyback_event_link_decision import (
    BuybackEventLinkDecision,
)
from buyback_analysis.models.buyback_plan import BuybackPlan
from buyback_analysis.usecase.event_identity import ExistingEvent, assign_event_uids
from buyback_analysis.usecase.event_schemas import ExtractedBuybackEvent
from buyback_analysis.usecase.rebuild_plan_projection import rebuild_plan_projection


@dataclass(frozen=True)
class BuybackEventAdoptionResult:
    assigned_event_uids: tuple[str, ...]
    content_changed_uids: tuple[str, ...]
    removed_event_uids: tuple[str, ...]
    reactivated_event_uids: tuple[str, ...]


def _add_expiration(
    session: Session,
    *,
    event_uid: str,
    reason_code: str,
    uid_factory: Callable[[], str],
) -> None:
    current = (
        session.query(BuybackEventLinkDecision)
        .filter(
            BuybackEventLinkDecision.event_uid == event_uid,
            BuybackEventLinkDecision.is_current.is_(True),
        )
        .one_or_none()
    )
    supersedes_id = current.decision_id if current is not None else None
    if current is not None:
        current.is_current = False

    session.add(
        BuybackEventLinkDecision(
            decision_id=uid_factory(),
            event_uid=event_uid,
            status="UNRESOLVED",
            decision_kind="EXPIRATION",
            linked_plan_id=None,
            candidates=[],
            reason_codes=[reason_code],
            rule_version="expire:v1",
            input_fingerprint=None,
            supersedes_decision_id=supersedes_id,
            is_current=True,
        )
    )


def _invalidate_origin_plan(
    session: Session,
    *,
    origin_event_uid: str,
    uid_factory: Callable[[], str],
) -> None:
    plan = (
        session.query(BuybackPlan)
        .filter(BuybackPlan.origin_event_uid == origin_event_uid)
        .one_or_none()
    )
    if plan is None:
        return
    plan.lifecycle_status = "INVALIDATED_ORIGIN"
    linked_event_uids = [
        decision.event_uid
        for decision in session.query(BuybackEventLinkDecision)
        .filter(
            BuybackEventLinkDecision.linked_plan_id == plan.buyback_plan_id,
            BuybackEventLinkDecision.status == "LINKED",
            BuybackEventLinkDecision.is_current.is_(True),
            BuybackEventLinkDecision.event_uid != origin_event_uid,
        )
        .all()
    ]
    for event_uid in linked_event_uids:
        _add_expiration(
            session,
            event_uid=event_uid,
            reason_code="EXPIRED_BY_ORIGIN_INVALIDATION",
            uid_factory=uid_factory,
        )


def _write_event(
    stored: BuybackEvent,
    *,
    version_id: str,
    url: str,
    code: str,
    document_title: str | None,
    disclosure_datetime: str | None,
    event: ExtractedBuybackEvent,
    fingerprint: str,
    source_quote_verified: bool,
) -> None:
    stored.version_id = version_id
    stored.url = url
    stored.document_title = document_title
    stored.disclosure_datetime = disclosure_datetime
    stored.code = code
    stored.event_type = event.event_type.value
    stored.event_fingerprint = fingerprint
    stored.event_date = event.event_date
    stored.resolution_date = event.resolution_date
    stored.referenced_document_date = event.referenced_document_date
    stored.referenced_document_title = event.referenced_document_title
    stored.source_quote = event.source_quote
    stored.source_quote_verified = source_quote_verified
    stored.source_page = event.source_page
    stored.source_section = event.source_section
    stored.payload = event.payload.model_dump(mode="json")
    stored.is_active = True


def adopt_buyback_events(
    session: Session,
    *,
    version_id: str,
    url: str,
    code: str,
    events: Sequence[ExtractedBuybackEvent],
    document_title: str | None = None,
    disclosure_datetime: str | None = None,
    aggregation_rule_version: str = "projection:v1",
    quote_verified: Sequence[bool] | None = None,
    uid_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
) -> BuybackEventAdoptionResult:
    """Replace one URL's current events, leaving commit/rollback to the caller."""

    verified_flags = (
        tuple(quote_verified)
        if quote_verified is not None
        else tuple(False for _ in events)
    )
    if len(verified_flags) != len(events):
        raise ValueError("quote_verified must have one value per event")

    old_events = (
        session.query(BuybackEvent)
        .filter(BuybackEvent.url == url)
        .order_by(BuybackEvent.event_uid)
        .all()
    )
    old_by_uid = {event.event_uid: event for event in old_events}
    identity = assign_event_uids(
        events,
        (
            ExistingEvent(
                event_uid=event.event_uid,
                event_type=event.event_type,
                event_fingerprint=event.event_fingerprint,
                is_active=event.is_active,
            )
            for event in old_events
        ),
        uid_factory=uid_factory,
    )

    changed: list[str] = []
    reactivated: list[str] = []
    for event, assignment, quote_is_verified in zip(
        events, identity.assignments, verified_flags
    ):
        stored = old_by_uid.get(assignment.event_uid)
        quote_became_unverified = bool(
            stored is not None
            and stored.source_quote_verified
            and not quote_is_verified
        )
        if stored is None:
            stored = BuybackEvent(event_uid=assignment.event_uid)
            session.add(stored)
        _write_event(
            stored,
            version_id=version_id,
            url=url,
            code=code,
            document_title=document_title,
            disclosure_datetime=disclosure_datetime,
            event=event,
            fingerprint=assignment.event_fingerprint,
            source_quote_verified=quote_is_verified,
        )
        if assignment.content_changed or quote_became_unverified:
            changed.append(assignment.event_uid)
            _add_expiration(
                session,
                event_uid=assignment.event_uid,
                reason_code=(
                    "EXPIRED_BY_CONTENT_CHANGE"
                    if assignment.content_changed
                    else "EXPIRED_BY_SOURCE_QUOTE_INVALIDATION"
                ),
                uid_factory=uid_factory,
            )
            _invalidate_origin_plan(
                session,
                origin_event_uid=assignment.event_uid,
                uid_factory=uid_factory,
            )
        if assignment.reactivated:
            reactivated.append(assignment.event_uid)

    removed: list[str] = []
    for event_uid in identity.unmatched_existing_uids:
        stored = old_by_uid[event_uid]
        if not stored.is_active:
            continue
        stored.is_active = False
        removed.append(event_uid)
        _add_expiration(
            session,
            event_uid=event_uid,
            reason_code="EXPIRED_BY_REMOVAL",
            uid_factory=uid_factory,
        )
        _invalidate_origin_plan(
            session,
            origin_event_uid=event_uid,
            uid_factory=uid_factory,
        )

    for plan in session.query(BuybackPlan).filter(BuybackPlan.code == code).all():
        rebuild_plan_projection(
            session,
            plan_id=plan.buyback_plan_id,
            aggregation_rule_version=aggregation_rule_version,
        )

    # Surface uniqueness/check failures before the caller switches result adoption.
    session.flush()
    return BuybackEventAdoptionResult(
        assigned_event_uids=tuple(item.event_uid for item in identity.assignments),
        content_changed_uids=tuple(changed),
        removed_event_uids=tuple(removed),
        reactivated_event_uids=tuple(reactivated),
    )
