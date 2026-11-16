import pytest

from buyback_analysis.usecase.event_schemas import BuybackEventExtraction
from buyback_analysis.usecase.link_existing_plan_events import (
    PlanLinkCandidate,
    evaluate_amendment,
    evaluate_completion,
    evaluate_equity_compensation,
    evaluate_execution_notice,
    evaluate_non_linkable,
    evaluate_progress,
    evaluate_retirement,
    evaluate_supplement,
)


def _candidate(plan_id="plan-1", **overrides):
    values = {
        "plan_id": plan_id,
        "resolution_date": "2026-01-01",
        "start_date": "2026-01-02",
        "end_date": "2026-12-31",
        "current_shares": 1000,
        "current_amount_yen": 5_000_000,
        "current_method": "market_purchase",
        "origin_document_title": "自己株式取得に係る事項の決定",
        "origin_document_date": "2026-01-01",
        "lifecycle_status": "ACTIVE",
    }
    values.update(overrides)
    return PlanLinkCandidate(**values)


def _event(event_type, payload, **overrides):
    values = {
        "event_type": event_type,
        "source_quote": "案件との対応を示す原文",
        "payload": payload,
        **overrides,
    }
    return BuybackEventExtraction.model_validate({"events": [values]}).events[0]


def test_amendment_links_by_explicit_referenced_resolution_and_changed_value():
    event = _event(
        "amendment",
        {"changed_buyback_amount_yen": 6_000_000},
        referenced_document_date="2026-01-01",
    )

    result = evaluate_amendment(event, [_candidate()])

    assert result.status == "LINKED"
    assert result.linked_plan_id == "plan-1"
    assert result.candidate_plan_ids == ("plan-1",)
    assert "EXPLICIT_RESOLUTION_REFERENCE" in result.reason_codes


def test_amendment_links_by_resolution_and_matching_previous_values():
    event = _event(
        "amendment",
        {
            "previous_buyback_shares": 1000,
            "previous_buyback_amount_yen": 5_000_000,
            "changed_buyback_amount_yen": 6_000_000,
        },
        resolution_date="2026-01-01",
    )

    result = evaluate_amendment(event, [_candidate()])

    assert result.status == "LINKED"
    assert "RESOLUTION_AND_PREVIOUS_VALUES_MATCH" in result.reason_codes


def test_amendment_previous_value_conflict_is_unresolved():
    event = _event(
        "amendment",
        {
            "previous_buyback_amount_yen": 4_000_000,
            "changed_buyback_amount_yen": 6_000_000,
        },
        resolution_date="2026-01-01",
    )

    result = evaluate_amendment(event, [_candidate()])

    assert result.status == "UNRESOLVED"
    assert result.linked_plan_id is None
    assert "PREVIOUS_VALUE_CONFLICT" in result.reason_codes


def test_amendment_without_changed_value_is_unresolved_even_with_reference():
    event = _event(
        "amendment",
        {"previous_buyback_amount_yen": 5_000_000},
        referenced_document_date="2026-01-01",
    )

    result = evaluate_amendment(event, [_candidate()])

    assert result.status == "UNRESOLVED"
    assert result.reason_codes == ("MISSING_CHANGED_VALUE",)


def test_amendment_with_two_matching_candidates_is_ambiguous():
    event = _event(
        "amendment",
        {"changed_buyback_amount_yen": 6_000_000},
        referenced_document_date="2026-01-01",
    )

    result = evaluate_amendment(
        event, [_candidate("plan-a"), _candidate("plan-b")]
    )

    assert result.status == "AMBIGUOUS"
    assert result.candidate_plan_ids == ("plan-a", "plan-b")


def test_progress_links_when_reporting_period_is_unique_to_plan():
    event = _event(
        "progress",
        {
            "period_start": "2026-03-01",
            "period_end": "2026-03-31",
            "cumulative_shares_acquired": 400,
            "cumulative_amount_spent_yen": 2_000_000,
        },
    )

    result = evaluate_progress(event, [_candidate()])

    assert result.status == "LINKED"
    assert result.linked_plan_id == "plan-1"
    assert "REPORTING_PERIOD_WITHIN_PLAN" in result.reason_codes


def test_progress_explicit_resolution_reference_can_identify_plan():
    event = _event(
        "progress",
        {"cumulative_shares_acquired": 400},
        referenced_document_date="2026-01-01",
    )

    result = evaluate_progress(event, [_candidate()])

    assert result.status == "LINKED"
    assert "EXPLICIT_RESOLUTION_REFERENCE" in result.reason_codes


@pytest.mark.parametrize(
    "payload",
    [
        {"cumulative_shares_acquired": 1001},
        {"cumulative_amount_spent_yen": 5_000_001},
        {"cumulative_shares_acquired": -1},
    ],
)
def test_progress_cumulative_contradiction_is_unresolved(payload):
    event = _event(
        "progress", payload, referenced_document_date="2026-01-01"
    )

    result = evaluate_progress(event, [_candidate()])

    assert result.status == "UNRESOLVED"
    assert "CUMULATIVE_VALUE_CONFLICT" in result.reason_codes


def test_progress_matching_two_overlapping_plans_is_ambiguous():
    event = _event(
        "progress",
        {
            "period_start": "2026-03-01",
            "period_end": "2026-03-31",
            "cumulative_shares_acquired": 100,
        },
    )

    result = evaluate_progress(
        event, [_candidate("plan-a"), _candidate("plan-b")]
    )

    assert result.status == "AMBIGUOUS"
    assert result.candidate_plan_ids == ("plan-a", "plan-b")


def test_inactive_plan_is_not_a_link_candidate():
    event = _event(
        "progress",
        {"cumulative_shares_acquired": 100},
        referenced_document_date="2026-01-01",
    )

    result = evaluate_progress(
        event, [_candidate(lifecycle_status="INVALIDATED_ORIGIN")]
    )

    assert result.status == "UNRESOLVED"
    assert result.reason_codes == ("NO_MATCHING_PLAN",)


def test_execution_notice_links_with_resolution_and_matching_method():
    event = _event(
        "execution_notice",
        {"subtype": "planned", "buyback_method": "market_purchase"},
        referenced_document_date="2026-01-01",
    )

    result = evaluate_execution_notice(event, [_candidate()])

    assert result.status == "LINKED"
    assert result.linked_plan_id == "plan-1"
    assert "RESOLUTION_AND_EXECUTION_TERMS_MATCH" in result.reason_codes


def test_execution_notice_links_with_resolution_and_matching_frame():
    event = _event(
        "execution_notice",
        {"subtype": "planned", "planned_buyback_shares": 1000},
        referenced_document_date="2026-01-01",
    )

    result = evaluate_execution_notice(event, [_candidate()])

    assert result.status == "LINKED"


def test_execution_notice_partial_planned_frame_is_within_plan_limit():
    event = _event(
        "execution_notice",
        {
            "subtype": "planned",
            "planned_buyback_shares": 96_934_800,
            "planned_buyback_amount_yen": 25_299_982_800,
        },
        resolution_date="2026-10-13",
    )
    candidate = _candidate(
        resolution_date="2026-10-13",
        current_shares=200_000_000,
        current_amount_yen=60_000_000_000,
    )

    result = evaluate_execution_notice(event, [candidate])

    assert result.status == "LINKED"


@pytest.mark.parametrize(
    ("event_type", "payload", "evaluator"),
    [
        ("progress", {"cumulative_shares_acquired": 100}, evaluate_progress),
        (
            "execution_notice",
            {"subtype": "planned", "planned_buyback_shares": 1000},
            evaluate_execution_notice,
        ),
        ("completion", {"shares_acquired": 900}, evaluate_completion),
    ],
)
def test_resolution_date_is_accepted_as_resolution_reference(
    event_type, payload, evaluator
):
    event = _event(
        event_type,
        payload,
        resolution_date="2026-01-01",
    )

    result = evaluator(event, [_candidate()])

    assert result.status == "LINKED"


def test_referenced_document_date_matches_origin_disclosure_not_resolution():
    event = _event(
        "progress",
        {"cumulative_shares_acquired": 100},
        referenced_document_date="2026-02-01",
    )
    candidate = _candidate(
        resolution_date="2026-02-01",
        origin_document_date="2026-01-15",
    )

    result = evaluate_progress(event, [candidate])

    assert result.status == "UNRESOLVED"

    matching_document = _candidate(
        resolution_date="2026-01-01",
        origin_document_date="2026-02-01",
    )
    result = evaluate_progress(event, [matching_document])

    assert result.status == "LINKED"


def test_referenced_document_date_matches_iso_disclosure_datetime():
    event = _event(
        "progress",
        {"cumulative_shares_acquired": 100},
        referenced_document_date="2026-10-13",
    )
    candidate = _candidate(
        resolution_date="2026-10-01",
        origin_document_date="2026-10-13T15:00:00+09:00",
    )

    result = evaluate_progress(event, [candidate])

    assert result.status == "LINKED"


@pytest.mark.parametrize(
    "payload",
    [
        {"subtype": "planned", "buyback_method": "tostnet-3"},
        {"subtype": "planned", "planned_buyback_shares": 1001},
        {"subtype": "result", "executed_amount_yen": 5_000_001},
    ],
)
def test_execution_notice_term_conflict_is_unresolved(payload):
    event = _event(
        "execution_notice", payload, referenced_document_date="2026-01-01"
    )

    result = evaluate_execution_notice(event, [_candidate()])

    assert result.status == "UNRESOLVED"
    assert result.candidate_plan_ids == ("plan-1",)
    assert result.reason_codes == ("EXECUTION_TERMS_CONFLICT",)


def test_execution_notice_without_resolution_reference_is_unresolved():
    event = _event(
        "execution_notice",
        {"subtype": "planned", "buyback_method": "market_purchase"},
    )

    result = evaluate_execution_notice(event, [_candidate()])

    assert result.status == "UNRESOLVED"
    assert result.reason_codes == ("NO_MATCHING_PLAN",)


def test_execution_notice_matching_two_plans_is_ambiguous():
    event = _event(
        "execution_notice",
        {"subtype": "planned", "buyback_method": "market_purchase"},
        referenced_document_date="2026-01-01",
    )

    result = evaluate_execution_notice(
        event, [_candidate("plan-a"), _candidate("plan-b")]
    )

    assert result.status == "AMBIGUOUS"


def test_completion_links_by_explicit_resolution_reference():
    event = _event(
        "completion",
        {"shares_acquired": 900, "amount_spent_yen": 4_500_000},
        referenced_document_date="2026-01-01",
    )

    result = evaluate_completion(event, [_candidate()])

    assert result.status == "LINKED"
    assert "EXPLICIT_RESOLUTION_REFERENCE" in result.reason_codes


def test_completion_links_by_exact_acquisition_period():
    event = _event(
        "completion",
        {
            "shares_acquired": 900,
            "start_date": "2026-01-02",
            "end_date": "2026-12-31",
        },
    )

    result = evaluate_completion(event, [_candidate()])

    assert result.status == "LINKED"
    assert "ACQUISITION_PERIOD_MATCH" in result.reason_codes


def test_completion_links_by_referenced_origin_title():
    event = _event(
        "completion",
        {"shares_acquired": 900},
        referenced_document_title="自己株式取得に係る事項の決定",
    )

    result = evaluate_completion(event, [_candidate()])

    assert result.status == "LINKED"
    assert "ORIGIN_DOCUMENT_REFERENCE" in result.reason_codes


@pytest.mark.parametrize(
    "payload",
    [
        {"shares_acquired": 1001},
        {"amount_spent_yen": 5_000_001},
        {"shares_acquired": -1},
    ],
)
def test_completion_final_value_conflict_is_unresolved(payload):
    event = _event("completion", payload, referenced_document_date="2026-01-01")

    result = evaluate_completion(event, [_candidate()])

    assert result.status == "UNRESOLVED"
    assert result.candidate_plan_ids == ("plan-1",)
    assert result.reason_codes == ("FINAL_VALUE_CONFLICT",)


def test_completion_without_final_value_is_unresolved():
    event = _event(
        "completion", {}, referenced_document_date="2026-01-01"
    )

    result = evaluate_completion(event, [_candidate()])

    assert result.status == "UNRESOLVED"
    assert result.reason_codes == ("MISSING_FINAL_VALUE",)


def test_completion_matching_two_plans_is_ambiguous():
    event = _event(
        "completion",
        {"shares_acquired": 900},
        referenced_document_date="2026-01-01",
    )

    result = evaluate_completion(
        event, [_candidate("plan-a"), _candidate("plan-b")]
    )

    assert result.status == "AMBIGUOUS"


def test_supplement_links_by_explicit_resolution_reference():
    event = _event(
        "supplement",
        {"description": "取得条件の補足"},
        referenced_document_date="2026-01-01",
    )

    result = evaluate_supplement(event, [_candidate()])

    assert result.status == "LINKED"
    assert result.linked_plan_id == "plan-1"
    assert result.reason_codes == ("EXPLICIT_RESOLUTION_REFERENCE",)


def test_supplement_links_by_origin_document_reference():
    event = _event(
        "supplement",
        {"description": "取得条件の補足"},
        referenced_document_title="自己株式取得に係る事項の決定",
    )

    result = evaluate_supplement(event, [_candidate()])

    assert result.status == "LINKED"
    assert result.reason_codes == ("ORIGIN_DOCUMENT_REFERENCE",)


def test_supplement_without_explicit_reference_is_unresolved():
    event = _event("supplement", {"description": "取得条件の補足"})

    result = evaluate_supplement(event, [_candidate()])

    assert result.status == "UNRESOLVED"
    assert result.candidate_plan_ids == ("plan-1",)
    assert result.reason_codes == ("MISSING_EXPLICIT_REFERENCE",)


def test_supplement_matching_two_plans_is_ambiguous():
    event = _event(
        "supplement", {}, referenced_document_date="2026-01-01"
    )

    result = evaluate_supplement(
        event, [_candidate("plan-a"), _candidate("plan-b")]
    )

    assert result.status == "AMBIGUOUS"


def test_equity_compensation_requires_existing_plan_use_and_reference():
    event = _event(
        "equity_compensation",
        {"uses_existing_buyback_plan": True, "buyback_shares": 100},
        referenced_document_date="2026-01-01",
    )

    result = evaluate_equity_compensation(event, [_candidate()])

    assert result.status == "LINKED"
    assert result.reason_codes == ("EXISTING_PLAN_USE_AND_REFERENCE",)


@pytest.mark.parametrize("uses_existing", [None, False])
def test_equity_compensation_without_existing_plan_use_is_unresolved(
    uses_existing,
):
    event = _event(
        "equity_compensation",
        {"uses_existing_buyback_plan": uses_existing, "buyback_shares": 100},
        referenced_document_date="2026-01-01",
    )

    result = evaluate_equity_compensation(event, [_candidate()])

    assert result.status == "UNRESOLVED"
    assert result.reason_codes == ("EXISTING_PLAN_USE_UNCONFIRMED",)


def test_equity_compensation_frame_conflict_is_unresolved():
    event = _event(
        "equity_compensation",
        {"uses_existing_buyback_plan": True, "buyback_shares": 1001},
        referenced_document_date="2026-01-01",
    )

    result = evaluate_equity_compensation(event, [_candidate()])

    assert result.status == "UNRESOLVED"
    assert result.reason_codes == ("EQUITY_COMPENSATION_FRAME_CONFLICT",)


def test_retirement_requires_buyback_relationship_and_reference():
    event = _event(
        "retirement",
        {"related_to_buyback_plan": True, "retirement_shares": 900},
        referenced_document_date="2026-01-01",
    )

    result = evaluate_retirement(event, [_candidate()])

    assert result.status == "LINKED"
    assert result.reason_codes == ("BUYBACK_RELATION_AND_REFERENCE",)


def test_retirement_without_buyback_relationship_is_unresolved():
    event = _event(
        "retirement",
        {"retirement_shares": 900},
        referenced_document_date="2026-01-01",
    )

    result = evaluate_retirement(event, [_candidate()])

    assert result.status == "UNRESOLVED"
    assert result.reason_codes == ("BUYBACK_RELATION_UNCONFIRMED",)


def test_retirement_share_conflict_is_unresolved():
    event = _event(
        "retirement",
        {"related_to_buyback_plan": True, "retirement_shares": 1001},
        referenced_document_date="2026-01-01",
    )

    result = evaluate_retirement(event, [_candidate()])

    assert result.status == "UNRESOLVED"
    assert result.reason_codes == ("RETIREMENT_SHARES_CONFLICT",)


@pytest.mark.parametrize("event_type", ["other_party_transaction", "other"])
def test_non_linkable_event_types_never_link(event_type):
    payload = (
        {"other_party_code": "5678", "description": "他社による取得"}
        if event_type == "other_party_transaction"
        else {"description": "分類不能"}
    )
    event = _event(
        event_type, payload, referenced_document_date="2026-01-01"
    )

    result = evaluate_non_linkable(event, [_candidate()])

    assert result.status == "UNRESOLVED"
    assert result.linked_plan_id is None
    assert result.candidate_plan_ids == ()
    assert result.reason_codes == ("EVENT_TYPE_NOT_LINKABLE",)
