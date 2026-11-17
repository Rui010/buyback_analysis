"""Atomically adopt, relink, and version one Phase 1 event extraction."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Sequence
from datetime import datetime, timezone

from buyback_analysis.interface.logger import Logger
from buyback_analysis.usecase.adopt_buyback_events import adopt_buyback_events
from buyback_analysis.usecase.event_schemas import BuybackEventExtraction
from buyback_analysis.usecase.relink_buyback_events import relink_buyback_events
from tdnet_provenance.models.result_adoption import ResultAdoption
from tdnet_provenance.models.result_version import ResultVersion


RESULT_TYPE = "buyback_events_v1"
LINK_RULE_VERSION = "buyback-link:v1"
PROJECTION_RULE_VERSION = "projection:v1"

logger = Logger()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def has_buyback_event_result(session, url: str) -> bool:
    """Return whether the document already has a versioned Phase 1 result."""

    return (
        session.query(ResultVersion.version_id)
        .filter(ResultVersion.url == url, ResultVersion.result_type == RESULT_TYPE)
        .first()
        is not None
    )


def save_buyback_event_result(
    session,
    *,
    code: str,
    url: str,
    document_title: str | None,
    disclosure_datetime: str | None,
    extraction: BuybackEventExtraction,
    quote_verified: Sequence[bool],
    run_ids: Sequence[str],
    clock: Callable[[], datetime] = _utc_now,
    version_id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
    adoption_id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
    event_uid_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
    decision_uid_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
) -> bool:
    """Save all Phase 1 state in one transaction, preserving the old adoption on error."""

    version_id = version_id_factory()
    now = clock().isoformat()
    payload = {
        "events": [event.model_dump(mode="json") for event in extraction.events],
        "source_quote_verified": list(quote_verified),
    }
    try:
        adopt_buyback_events(
            session,
            version_id=version_id,
            url=url,
            code=code,
            document_title=document_title,
            disclosure_datetime=disclosure_datetime,
            events=extraction.events,
            quote_verified=quote_verified,
            aggregation_rule_version=PROJECTION_RULE_VERSION,
            uid_factory=event_uid_factory,
        )
        relink_buyback_events(
            session,
            code=code,
            rule_version=LINK_RULE_VERSION,
            aggregation_rule_version=PROJECTION_RULE_VERSION,
            uid_factory=decision_uid_factory,
        )
        session.add(
            ResultVersion(
                version_id=version_id,
                url=url,
                code=code,
                result_type=RESULT_TYPE,
                extraction_status="ok",
                payload=json.dumps(payload, ensure_ascii=False, sort_keys=True),
                run_ids=json.dumps(list(run_ids), ensure_ascii=False),
                origin="run",
                created_at=now,
            )
        )
        session.add(
            ResultAdoption(
                adoption_id=adoption_id_factory(),
                url=url,
                result_type=RESULT_TYPE,
                version_id=version_id,
                adopted_at=now,
            )
        )
        session.commit()
        return True
    except Exception as exc:
        session.rollback()
        logger.error(
            f"[BuybackEvents] 採用・紐づけに失敗しました（旧採用を維持）: {url} {exc!r}"
        )
        return False
