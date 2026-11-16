"""Deterministic candidate evaluation for events that target existing plans."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Sequence

from buyback_analysis.usecase.event_schemas import (
    AmendmentEvent,
    CompletionEvent,
    EquityCompensationEvent,
    ExecutionNoticeEvent,
    OtherEvent,
    OtherPartyTransactionEvent,
    ProgressEvent,
    RetirementEvent,
    SupplementEvent,
)
from buyback_analysis.usecase.link_normalization import normalize_date, normalize_method


LinkStatus = Literal["LINKED", "UNRESOLVED", "AMBIGUOUS"]


@dataclass(frozen=True)
class PlanLinkCandidate:
    plan_id: str
    resolution_date: Optional[str]
    start_date: Optional[str]
    end_date: Optional[str]
    current_shares: Optional[int]
    current_amount_yen: Optional[int]
    current_method: Optional[str] = None
    origin_document_title: Optional[str] = None
    lifecycle_status: str = "ACTIVE"
    origin_document_date: Optional[str] = None
    original_shares: Optional[int] = None
    original_amount_yen: Optional[int] = None
    original_start_date: Optional[str] = None
    original_end_date: Optional[str] = None


@dataclass(frozen=True)
class ExistingPlanEvaluation:
    status: LinkStatus
    linked_plan_id: Optional[str]
    candidate_plan_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]


def _finish(
    matches: list[tuple[str, str]],
    no_match_reason: str,
    considered_plan_ids: Sequence[str],
):
    ordered = sorted(matches)
    plan_ids = tuple(plan_id for plan_id, _ in ordered)
    if len(ordered) == 1:
        return ExistingPlanEvaluation(
            "LINKED", ordered[0][0], plan_ids, (ordered[0][1],)
        )
    if len(ordered) >= 2:
        return ExistingPlanEvaluation(
            "AMBIGUOUS", None, plan_ids, ("MULTIPLE_MATCHING_PLANS",)
        )
    return ExistingPlanEvaluation(
        "UNRESOLVED",
        None,
        tuple(sorted(set(considered_plan_ids))),
        (no_match_reason,),
    )


def _resolution_reference_matches(event, candidate: PlanLinkCandidate) -> bool:
    return bool(
        (
            event.resolution_date
            and normalize_date(event.resolution_date)
            == normalize_date(candidate.resolution_date)
        )
        or (
            event.referenced_document_date
            and normalize_date(event.referenced_document_date)
            == normalize_date(candidate.origin_document_date)
        )
    )


def _has_amendment_change(event: AmendmentEvent) -> bool:
    payload = event.payload
    return any(
        value is not None
        for value in (
            payload.changed_buyback_shares,
            payload.changed_buyback_amount_yen,
            payload.changed_start_date,
            payload.changed_end_date,
            payload.changed_buyback_method,
        )
    )


def _previous_values(candidate: PlanLinkCandidate, event: AmendmentEvent):
    payload = event.payload
    return (
        (payload.previous_buyback_shares, candidate.current_shares, lambda value: value),
        (payload.previous_buyback_amount_yen, candidate.current_amount_yen, lambda value: value),
        (payload.previous_start_date, candidate.start_date, normalize_date),
        (payload.previous_end_date, candidate.end_date, normalize_date),
        (payload.previous_buyback_method, candidate.current_method, normalize_method),
    )


def evaluate_amendment(
    event: AmendmentEvent,
    candidates: Sequence[PlanLinkCandidate],
) -> ExistingPlanEvaluation:
    if event.event_type.value != "amendment":
        raise ValueError("event must be amendment")
    if not _has_amendment_change(event):
        return ExistingPlanEvaluation(
            "UNRESOLVED", None, (), ("MISSING_CHANGED_VALUE",)
        )

    matches: list[tuple[str, str]] = []
    considered: list[str] = []
    previous_conflict = False
    for candidate in candidates:
        if candidate.lifecycle_status != "ACTIVE":
            continue
        considered.append(candidate.plan_id)
        values = _previous_values(candidate, event)
        provided = [
            (old, current, normalizer)
            for old, current, normalizer in values
            if old is not None
        ]
        conflict = any(
            current is None or normalizer(old) != normalizer(current)
            for old, current, normalizer in provided
        )
        if conflict:
            previous_conflict = True
            continue

        explicit = bool(
            event.referenced_document_date
            and normalize_date(event.referenced_document_date)
            == normalize_date(candidate.origin_document_date)
        )
        resolution_and_previous = bool(
            event.resolution_date
            and normalize_date(event.resolution_date)
            == normalize_date(candidate.resolution_date)
            and provided
        )
        if explicit:
            matches.append((candidate.plan_id, "EXPLICIT_RESOLUTION_REFERENCE"))
        elif resolution_and_previous:
            matches.append(
                (candidate.plan_id, "RESOLUTION_AND_PREVIOUS_VALUES_MATCH")
            )
        elif _resolution_reference_matches(event, candidate):
            matches.append((candidate.plan_id, "EXPLICIT_RESOLUTION_REFERENCE"))

    return _finish(
        matches,
        "PREVIOUS_VALUE_CONFLICT" if previous_conflict else "NO_MATCHING_PLAN",
        considered,
    )


def _progress_conflicts(candidate: PlanLinkCandidate, event: ProgressEvent) -> bool:
    shares = event.payload.cumulative_shares_acquired
    amount = event.payload.cumulative_amount_spent_yen
    if shares is not None and (shares < 0 or (
        candidate.current_shares is not None and shares > candidate.current_shares
    )):
        return True
    if amount is not None and (amount < 0 or (
        candidate.current_amount_yen is not None and amount > candidate.current_amount_yen
    )):
        return True
    return False


def evaluate_progress(
    event: ProgressEvent,
    candidates: Sequence[PlanLinkCandidate],
) -> ExistingPlanEvaluation:
    if event.event_type.value != "progress":
        raise ValueError("event must be progress")
    if (
        event.payload.cumulative_shares_acquired is None
        and event.payload.cumulative_amount_spent_yen is None
    ):
        return ExistingPlanEvaluation(
            "UNRESOLVED", None, (), ("MISSING_CUMULATIVE_VALUE",)
        )

    matches: list[tuple[str, str]] = []
    considered: list[str] = []
    cumulative_conflict = False
    for candidate in candidates:
        if candidate.lifecycle_status != "ACTIVE":
            continue
        considered.append(candidate.plan_id)
        if _progress_conflicts(candidate, event):
            cumulative_conflict = True
            continue
        explicit = _resolution_reference_matches(event, candidate)
        period_within = bool(
            event.payload.period_start
            and event.payload.period_end
            and candidate.start_date
            and candidate.end_date
            and normalize_date(candidate.start_date)
            <= normalize_date(event.payload.period_start)
            and normalize_date(event.payload.period_end)
            <= normalize_date(candidate.end_date)
        )
        if explicit:
            matches.append((candidate.plan_id, "EXPLICIT_RESOLUTION_REFERENCE"))
        elif period_within:
            matches.append((candidate.plan_id, "REPORTING_PERIOD_WITHIN_PLAN"))

    return _finish(
        matches,
        "CUMULATIVE_VALUE_CONFLICT" if cumulative_conflict else "NO_MATCHING_PLAN",
        considered,
    )


def _execution_terms_conflict(
    candidate: PlanLinkCandidate, event: ExecutionNoticeEvent
) -> bool:
    payload = event.payload
    if (
        payload.buyback_method is not None
        and candidate.current_method is not None
        and normalize_method(payload.buyback_method)
        != normalize_method(candidate.current_method)
    ):
        return True
    if payload.planned_buyback_shares is not None and (
        payload.planned_buyback_shares < 0
        or (
            candidate.current_shares is not None
            and payload.planned_buyback_shares > candidate.current_shares
        )
    ):
        return True
    if payload.planned_buyback_amount_yen is not None and (
        payload.planned_buyback_amount_yen < 0
        or (
            candidate.current_amount_yen is not None
            and payload.planned_buyback_amount_yen > candidate.current_amount_yen
        )
    ):
        return True
    if payload.executed_shares is not None and (
        payload.executed_shares < 0
        or (
            candidate.current_shares is not None
            and payload.executed_shares > candidate.current_shares
        )
    ):
        return True
    if payload.executed_amount_yen is not None and (
        payload.executed_amount_yen < 0
        or (
            candidate.current_amount_yen is not None
            and payload.executed_amount_yen > candidate.current_amount_yen
        )
    ):
        return True
    return False


def evaluate_execution_notice(
    event: ExecutionNoticeEvent,
    candidates: Sequence[PlanLinkCandidate],
) -> ExistingPlanEvaluation:
    if event.event_type.value != "execution_notice":
        raise ValueError("event must be execution_notice")
    payload = event.payload
    has_terms = any(
        value is not None
        for value in (
            payload.buyback_method,
            payload.planned_buyback_shares,
            payload.planned_buyback_amount_yen,
            payload.executed_shares,
            payload.executed_amount_yen,
        )
    )
    if not has_terms:
        return ExistingPlanEvaluation(
            "UNRESOLVED", None, (), ("MISSING_EXECUTION_TERMS",)
        )

    matches: list[tuple[str, str]] = []
    considered: list[str] = []
    terms_conflict = False
    for candidate in candidates:
        if candidate.lifecycle_status != "ACTIVE":
            continue
        considered.append(candidate.plan_id)
        if _execution_terms_conflict(candidate, event):
            terms_conflict = True
            continue
        resolution_matches = _resolution_reference_matches(event, candidate)
        if resolution_matches:
            matches.append(
                (candidate.plan_id, "RESOLUTION_AND_EXECUTION_TERMS_MATCH")
            )

    return _finish(
        matches,
        "EXECUTION_TERMS_CONFLICT" if terms_conflict else "NO_MATCHING_PLAN",
        considered,
    )


def _completion_value_conflict(
    candidate: PlanLinkCandidate, event: CompletionEvent
) -> bool:
    shares = event.payload.shares_acquired
    amount = event.payload.amount_spent_yen
    if shares is not None and (
        shares < 0
        or (
            candidate.current_shares is not None
            and shares > candidate.current_shares
        )
    ):
        return True
    if amount is not None and (
        amount < 0
        or (
            candidate.current_amount_yen is not None
            and amount > candidate.current_amount_yen
        )
    ):
        return True
    return False


def evaluate_completion(
    event: CompletionEvent,
    candidates: Sequence[PlanLinkCandidate],
) -> ExistingPlanEvaluation:
    if event.event_type.value != "completion":
        raise ValueError("event must be completion")
    if (
        event.payload.shares_acquired is None
        and event.payload.amount_spent_yen is None
    ):
        return ExistingPlanEvaluation(
            "UNRESOLVED", None, (), ("MISSING_FINAL_VALUE",)
        )

    matches: list[tuple[str, str]] = []
    considered: list[str] = []
    value_conflict = False
    for candidate in candidates:
        if candidate.lifecycle_status != "ACTIVE":
            continue
        considered.append(candidate.plan_id)
        if _completion_value_conflict(candidate, event):
            value_conflict = True
            continue
        explicit = _resolution_reference_matches(event, candidate)
        period_matches = bool(
            event.payload.start_date
            and event.payload.end_date
            and normalize_date(event.payload.start_date)
            == normalize_date(candidate.start_date)
            and normalize_date(event.payload.end_date)
            == normalize_date(candidate.end_date)
        )
        title_matches = bool(
            event.referenced_document_title
            and candidate.origin_document_title
            and event.referenced_document_title == candidate.origin_document_title
        )
        if explicit:
            reason = "EXPLICIT_RESOLUTION_REFERENCE"
        elif period_matches:
            reason = "ACQUISITION_PERIOD_MATCH"
        elif title_matches:
            reason = "ORIGIN_DOCUMENT_REFERENCE"
        else:
            continue
        matches.append((candidate.plan_id, reason))

    return _finish(
        matches,
        "FINAL_VALUE_CONFLICT" if value_conflict else "NO_MATCHING_PLAN",
        considered,
    )


def _explicit_reference_reason(event, candidate: PlanLinkCandidate) -> Optional[str]:
    if _resolution_reference_matches(event, candidate):
        return "EXPLICIT_RESOLUTION_REFERENCE"
    if (
        event.referenced_document_title
        and candidate.origin_document_title
        and event.referenced_document_title == candidate.origin_document_title
    ):
        return "ORIGIN_DOCUMENT_REFERENCE"
    return None


def evaluate_supplement(
    event: SupplementEvent,
    candidates: Sequence[PlanLinkCandidate],
) -> ExistingPlanEvaluation:
    if event.event_type.value != "supplement":
        raise ValueError("event must be supplement")
    matches: list[tuple[str, str]] = []
    considered: list[str] = []
    for candidate in candidates:
        if candidate.lifecycle_status != "ACTIVE":
            continue
        considered.append(candidate.plan_id)
        reason = _explicit_reference_reason(event, candidate)
        if reason:
            matches.append((candidate.plan_id, reason))
    return _finish(matches, "MISSING_EXPLICIT_REFERENCE", considered)


def _equity_frame_conflicts(
    event: EquityCompensationEvent, candidate: PlanLinkCandidate
) -> bool:
    shares = event.payload.buyback_shares
    amount = event.payload.buyback_amount_yen
    if shares is not None and (
        shares < 0
        or (candidate.current_shares is not None and shares > candidate.current_shares)
    ):
        return True
    if amount is not None and (
        amount < 0
        or (
            candidate.current_amount_yen is not None
            and amount > candidate.current_amount_yen
        )
    ):
        return True
    return False


def evaluate_equity_compensation(
    event: EquityCompensationEvent,
    candidates: Sequence[PlanLinkCandidate],
) -> ExistingPlanEvaluation:
    if event.event_type.value != "equity_compensation":
        raise ValueError("event must be equity_compensation")
    active_ids = tuple(
        sorted(
            candidate.plan_id
            for candidate in candidates
            if candidate.lifecycle_status == "ACTIVE"
        )
    )
    if event.payload.uses_existing_buyback_plan is not True:
        return ExistingPlanEvaluation(
            "UNRESOLVED",
            None,
            active_ids,
            ("EXISTING_PLAN_USE_UNCONFIRMED",),
        )

    matches: list[tuple[str, str]] = []
    frame_conflict = False
    for candidate in candidates:
        if candidate.lifecycle_status != "ACTIVE":
            continue
        if _equity_frame_conflicts(event, candidate):
            frame_conflict = True
            continue
        if _explicit_reference_reason(event, candidate):
            matches.append(
                (candidate.plan_id, "EXISTING_PLAN_USE_AND_REFERENCE")
            )
    return _finish(
        matches,
        (
            "EQUITY_COMPENSATION_FRAME_CONFLICT"
            if frame_conflict
            else "MISSING_EXPLICIT_REFERENCE"
        ),
        active_ids,
    )


def evaluate_retirement(
    event: RetirementEvent,
    candidates: Sequence[PlanLinkCandidate],
) -> ExistingPlanEvaluation:
    if event.event_type.value != "retirement":
        raise ValueError("event must be retirement")
    active_ids = tuple(
        sorted(
            candidate.plan_id
            for candidate in candidates
            if candidate.lifecycle_status == "ACTIVE"
        )
    )
    if event.payload.related_to_buyback_plan is not True:
        return ExistingPlanEvaluation(
            "UNRESOLVED", None, active_ids, ("BUYBACK_RELATION_UNCONFIRMED",)
        )

    matches: list[tuple[str, str]] = []
    shares_conflict = False
    for candidate in candidates:
        if candidate.lifecycle_status != "ACTIVE":
            continue
        shares = event.payload.retirement_shares
        if shares is not None and (
            shares < 0
            or (
                candidate.current_shares is not None
                and shares > candidate.current_shares
            )
        ):
            shares_conflict = True
            continue
        if _explicit_reference_reason(event, candidate):
            matches.append((candidate.plan_id, "BUYBACK_RELATION_AND_REFERENCE"))
    return _finish(
        matches,
        (
            "RETIREMENT_SHARES_CONFLICT"
            if shares_conflict
            else "MISSING_EXPLICIT_REFERENCE"
        ),
        active_ids,
    )


def evaluate_non_linkable(
    event: OtherPartyTransactionEvent | OtherEvent,
    candidates: Sequence[PlanLinkCandidate],
) -> ExistingPlanEvaluation:
    del candidates
    if event.event_type.value not in {"other_party_transaction", "other"}:
        raise ValueError("event type is linkable")
    return ExistingPlanEvaluation(
        "UNRESOLVED", None, (), ("EVENT_TYPE_NOT_LINKABLE",)
    )
