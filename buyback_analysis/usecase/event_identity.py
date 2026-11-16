"""Deterministic identity assignment for adopted buyback events."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Iterable, Literal, Sequence

from buyback_analysis.usecase.event_schemas import ExtractedBuybackEvent


MatchKind = Literal["FINGERPRINT", "SINGLE_TYPE_FALLBACK", "AMBIGUOUS", "NEW"]


@dataclass(frozen=True)
class ExistingEvent:
    event_uid: str
    event_type: str
    event_fingerprint: str
    is_active: bool = True


@dataclass(frozen=True)
class EventIdentityAssignment:
    event_uid: str
    event_fingerprint: str
    match_kind: MatchKind
    content_changed: bool
    reactivated: bool = False
    candidate_uids: tuple[str, ...] = ()


@dataclass(frozen=True)
class EventIdentityResult:
    assignments: tuple[EventIdentityAssignment, ...]
    unmatched_existing_uids: tuple[str, ...]


def _normalize(value):
    if isinstance(value, dict):
        return {key: _normalize(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, str):
        return " ".join(value.split())
    return value


def build_event_fingerprint(event: ExtractedBuybackEvent) -> str:
    """Hash identity-relevant extracted values, excluding unstable source locators."""

    values = event.model_dump(
        mode="json",
        exclude={"source_quote", "source_page", "source_section"},
    )
    canonical = json.dumps(
        _normalize(values),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def assign_event_uids(
    new_events: Sequence[ExtractedBuybackEvent],
    existing_events: Iterable[ExistingEvent],
    *,
    uid_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
) -> EventIdentityResult:
    """Match one URL's new adopted events to all prior events for that URL."""

    existing = tuple(existing_events)
    fingerprints = tuple(build_event_fingerprint(event) for event in new_events)
    assigned: list[EventIdentityAssignment | None] = [None] * len(new_events)
    matched_existing: set[str] = set()

    old_by_fingerprint: dict[str, list[ExistingEvent]] = defaultdict(list)
    new_by_fingerprint: dict[str, list[int]] = defaultdict(list)
    for old in existing:
        old_by_fingerprint[old.event_fingerprint].append(old)
    for index, fingerprint in enumerate(fingerprints):
        new_by_fingerprint[fingerprint].append(index)

    # An exact match is safe only when both sides are unique.
    for fingerprint, new_indexes in new_by_fingerprint.items():
        old_matches = old_by_fingerprint.get(fingerprint, [])
        if len(new_indexes) == 1 and len(old_matches) == 1:
            index = new_indexes[0]
            old = old_matches[0]
            assigned[index] = EventIdentityAssignment(
                event_uid=old.event_uid,
                event_fingerprint=fingerprint,
                match_kind="FINGERPRINT",
                content_changed=False,
                reactivated=not old.is_active,
            )
            matched_existing.add(old.event_uid)

    # A correction fallback is safe only for one unmatched old/new event of a type.
    unmatched_new_by_type: dict[str, list[int]] = defaultdict(list)
    unmatched_old_by_type: dict[str, list[ExistingEvent]] = defaultdict(list)
    for index, event in enumerate(new_events):
        if assigned[index] is None:
            unmatched_new_by_type[event.event_type.value].append(index)
    for old in existing:
        if old.event_uid not in matched_existing:
            unmatched_old_by_type[old.event_type].append(old)

    for event_type, new_indexes in unmatched_new_by_type.items():
        old_matches = unmatched_old_by_type.get(event_type, [])
        if len(new_indexes) == 1 and len(old_matches) == 1:
            index = new_indexes[0]
            old = old_matches[0]
            assigned[index] = EventIdentityAssignment(
                event_uid=old.event_uid,
                event_fingerprint=fingerprints[index],
                match_kind="SINGLE_TYPE_FALLBACK",
                content_changed=True,
                reactivated=not old.is_active,
            )
            matched_existing.add(old.event_uid)

    # Remaining same-type candidates are explicitly ambiguous; otherwise they are new.
    for index, event in enumerate(new_events):
        if assigned[index] is not None:
            continue
        candidates = tuple(
            sorted(
                old.event_uid
                for old in existing
                if old.event_uid not in matched_existing
                and old.event_type == event.event_type.value
            )
        )
        assigned[index] = EventIdentityAssignment(
            event_uid=uid_factory(),
            event_fingerprint=fingerprints[index],
            match_kind="AMBIGUOUS" if candidates else "NEW",
            content_changed=False,
            candidate_uids=candidates,
        )

    unmatched = tuple(
        sorted(old.event_uid for old in existing if old.event_uid not in matched_existing)
    )
    return EventIdentityResult(
        assignments=tuple(item for item in assigned if item is not None),
        unmatched_existing_uids=unmatched,
    )
