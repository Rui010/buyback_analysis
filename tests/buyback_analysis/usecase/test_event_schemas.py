import pytest
from pydantic import ValidationError

from buyback_analysis.usecase.event_schemas import (
    BuybackEventExtraction,
    CompletionPayload,
    EventType,
    NewPlanPayload,
)


def _common(event_type: str, payload: dict) -> dict:
    return {
        "event_type": event_type,
        "event_date": "2026-10-13",
        "resolution_date": "2026-10-13",
        "source_quote": "原文に記載された根拠",
        "source_page": 1,
        "source_section": "記",
        "payload": payload,
    }


def test_one_document_can_contain_completion_and_new_plan_events():
    extraction = BuybackEventExtraction.model_validate(
        {
            "events": [
                _common(
                    "completion",
                    {
                        "shares_acquired": 0,
                        "amount_spent_yen": 0,
                        "start_date": "2025-10-29",
                        "end_date": "2026-10-13",
                    },
                ),
                _common(
                    "new_plan",
                    {
                        "buyback_shares": 200000000,
                        "buyback_amount_yen": 60000000000,
                        "start_date": "2026-10-14",
                        "end_date": "2027-10-13",
                        "buyback_method": "market_purchase",
                    },
                ),
            ]
        }
    )

    assert [event.event_type for event in extraction.events] == [
        EventType.COMPLETION,
        EventType.NEW_PLAN,
    ]
    assert isinstance(extraction.events[0].payload, CompletionPayload)
    assert isinstance(extraction.events[1].payload, NewPlanPayload)


@pytest.mark.parametrize(
    ("event_type", "payload"),
    [
        ("new_plan", {}),
        ("amendment", {"changed_buyback_amount_yen": 100}),
        ("execution_notice", {"subtype": "planned"}),
        ("progress", {"cumulative_shares_acquired": 10}),
        ("completion", {"shares_acquired": 10}),
        ("supplement", {}),
        ("equity_compensation", {}),
        ("retirement", {"retirement_shares": 10}),
        ("other_party_transaction", {"other_party_code": "5401"}),
        ("other", {"description": "分類不能"}),
    ],
)
def test_phase1_event_types_have_typed_payloads(event_type, payload):
    extraction = BuybackEventExtraction.model_validate(
        {"events": [_common(event_type, payload)]}
    )

    assert extraction.events[0].event_type.value == event_type


def test_unknown_event_type_is_rejected():
    with pytest.raises(ValidationError):
        BuybackEventExtraction.model_validate(
            {"events": [_common("correction", {})]}
        )


def test_source_quote_must_not_be_blank():
    event = _common("new_plan", {})
    event["source_quote"] = "   "

    with pytest.raises(ValidationError):
        BuybackEventExtraction.model_validate({"events": [event]})


def test_events_default_is_not_shared_between_instances():
    first = BuybackEventExtraction()
    second = BuybackEventExtraction()

    first.events.append(
        BuybackEventExtraction.model_validate(
            {"events": [_common("other", {"description": "test"})]}
        ).events[0]
    )

    assert len(first.events) == 1
    assert second.events == []
