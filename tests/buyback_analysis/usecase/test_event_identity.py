from copy import deepcopy

from buyback_analysis.usecase.event_identity import (
    ExistingEvent,
    assign_event_uids,
    build_event_fingerprint,
)
from buyback_analysis.usecase.event_schemas import BuybackEventExtraction


def _event(event_type="new_plan", **payload_overrides):
    payload = {
        "buyback_shares": 1000,
        "buyback_amount_yen": 5000000,
        "start_date": "2026-01-01",
        "end_date": "2026-12-31",
        **payload_overrides,
    }
    return BuybackEventExtraction.model_validate(
        {
            "events": [
                {
                    "event_type": event_type,
                    "event_date": "2025-12-20",
                    "resolution_date": "2025-12-20",
                    "source_quote": "取締役会において自己株式取得を決議した。",
                    "source_page": 1,
                    "source_section": "取得内容",
                    "payload": payload,
                }
            ]
        }
    ).events[0]


def test_fingerprint_ignores_source_locator_and_quote_formatting():
    first = _event()
    second = deepcopy(first)
    second.source_page = 8
    second.source_section = "別の見出し"
    second.source_quote = "  取締役会において自己株式取得を決議した。  "

    assert build_event_fingerprint(first) == build_event_fingerprint(second)


def test_exact_fingerprint_match_inherits_existing_uid():
    event = _event()
    existing = ExistingEvent(
        event_uid="event-old",
        event_type="new_plan",
        event_fingerprint=build_event_fingerprint(event),
    )

    result = assign_event_uids([event], [existing], uid_factory=lambda: "event-new")

    assert result.assignments[0].event_uid == "event-old"
    assert result.assignments[0].match_kind == "FINGERPRINT"
    assert result.unmatched_existing_uids == ()


def test_single_same_type_pair_inherits_uid_when_values_were_corrected():
    old_event = _event(buyback_amount_yen=5000000)
    corrected_event = _event(buyback_amount_yen=6000000)
    existing = ExistingEvent(
        event_uid="event-old",
        event_type="new_plan",
        event_fingerprint=build_event_fingerprint(old_event),
    )

    result = assign_event_uids(
        [corrected_event], [existing], uid_factory=lambda: "event-new"
    )

    assert result.assignments[0].event_uid == "event-old"
    assert result.assignments[0].match_kind == "SINGLE_TYPE_FALLBACK"
    assert result.assignments[0].content_changed is True


def test_ambiguous_duplicate_fingerprint_gets_new_uid_without_guessing():
    event = _event()
    fingerprint = build_event_fingerprint(event)
    existing = [
        ExistingEvent("event-a", "new_plan", fingerprint),
        ExistingEvent("event-b", "new_plan", fingerprint),
    ]

    result = assign_event_uids([event], existing, uid_factory=lambda: "event-new")

    assert result.assignments[0].event_uid == "event-new"
    assert result.assignments[0].match_kind == "AMBIGUOUS"
    assert result.assignments[0].candidate_uids == ("event-a", "event-b")
    assert result.unmatched_existing_uids == ("event-a", "event-b")


def test_unmatched_new_event_gets_new_uid_and_old_event_is_reported_removed():
    old_event = _event("new_plan")
    progress = BuybackEventExtraction.model_validate(
        {
            "events": [
                {
                    "event_type": "progress",
                    "source_quote": "取得状況",
                    "payload": {"cumulative_shares_acquired": 100},
                }
            ]
        }
    ).events[0]
    existing = ExistingEvent(
        "event-old", "new_plan", build_event_fingerprint(old_event)
    )

    result = assign_event_uids([progress], [existing], uid_factory=lambda: "event-new")

    assert result.assignments[0].event_uid == "event-new"
    assert result.assignments[0].match_kind == "NEW"
    assert result.unmatched_existing_uids == ("event-old",)


def test_inactive_existing_event_can_be_reactivated_by_exact_match():
    event = _event()
    existing = ExistingEvent(
        event_uid="event-old",
        event_type="new_plan",
        event_fingerprint=build_event_fingerprint(event),
        is_active=False,
    )

    result = assign_event_uids([event], [existing], uid_factory=lambda: "event-new")

    assert result.assignments[0].event_uid == "event-old"
    assert result.assignments[0].reactivated is True


def test_two_same_type_unmatched_pairs_do_not_use_positional_fallback():
    new_events = [
        _event(buyback_amount_yen=6000000),
        _event(buyback_amount_yen=7000000),
    ]
    existing = [
        ExistingEvent("event-a", "new_plan", "old-a"),
        ExistingEvent("event-b", "new_plan", "old-b"),
    ]
    generated = iter(["event-new-1", "event-new-2"])

    result = assign_event_uids(new_events, existing, uid_factory=lambda: next(generated))

    assert [item.event_uid for item in result.assignments] == [
        "event-new-1",
        "event-new-2",
    ]
    assert all(item.match_kind == "AMBIGUOUS" for item in result.assignments)
    assert result.unmatched_existing_uids == ("event-a", "event-b")
