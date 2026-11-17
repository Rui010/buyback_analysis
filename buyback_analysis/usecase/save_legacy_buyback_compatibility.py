"""Materialize legacy buyback tables from adopted Phase 1 events without an LLM."""

from __future__ import annotations

from buyback_analysis.interface.logger import Logger
from buyback_analysis.models.announcement import Announcement
from buyback_analysis.models.buyback_event import BuybackEvent
from buyback_analysis.models.completion import Completion
from buyback_analysis.models.correction import Correction
from buyback_analysis.models.is_checked import IsChecked
from buyback_analysis.models.progress import Progress
from buyback_analysis.models.retirement import Retirement
from tdnet_provenance.usecase.adopt_result import adopt_result


BUYBACK_RESULT_TYPE = "buyback"
BUYBACK_TABLES = (IsChecked, Announcement, Progress, Completion, Correction, Retirement)
logger = Logger()


def requires_legacy_llm(title: str) -> bool:
    """Corrections remain on the legacy extraction path until Phase 2."""

    return "訂正" in title


def _first_by_type(events):
    result = {}
    for event in events:
        result.setdefault(event.event_type, event)
    return result


def save_legacy_buyback_compatibility(
    session,
    *,
    code: str,
    url: str,
    disclosure_date: str,
    company_name: str | None,
    rerun: bool,
) -> bool:
    """Write legacy current tables from active events; never calls an LLM."""

    events = (
        session.query(BuybackEvent)
        .filter(BuybackEvent.url == url, BuybackEvent.is_active.is_(True))
        .order_by(BuybackEvent.event_uid)
        .all()
    )
    by_type = _first_by_type(events)
    rows = []

    event = by_type.get("new_plan")
    if event is not None:
        payload = event.payload or {}
        rows.append(
            Announcement(
                url=url,
                code=code,
                disclosure_date=disclosure_date,
                resolution_date=event.resolution_date,
                company_name=company_name,
                buyback_method=payload.get("buyback_method"),
                share_type=payload.get("share_type"),
                buyback_amount_yen=payload.get("buyback_amount_yen"),
                buyback_shares=payload.get("buyback_shares"),
                start_date=payload.get("start_date"),
                end_date=payload.get("end_date"),
            )
        )

    event = by_type.get("progress")
    if event is not None:
        payload = event.payload or {}
        rows.append(
            Progress(
                url=url,
                code=code,
                disclosure_date=disclosure_date,
                company_name=company_name,
                cumulative_shares_acquired=payload.get("cumulative_shares_acquired"),
                cumulative_amount_spent_yen=payload.get("cumulative_amount_spent_yen"),
                period_start=payload.get("period_start"),
                period_end=payload.get("period_end"),
            )
        )

    event = by_type.get("completion")
    if event is not None:
        payload = event.payload or {}
        if payload.get("shares_acquired") is not None and payload.get("amount_spent_yen") is not None:
            rows.append(
                Completion(
                    url=url,
                    code=code,
                    disclosure_date=disclosure_date,
                    resolution_date=event.resolution_date,
                    company_name=company_name,
                    start_date=payload.get("start_date"),
                    end_date=payload.get("end_date"),
                    shares_acquired=payload.get("shares_acquired"),
                    amount_spent_yen=payload.get("amount_spent_yen"),
                    buyback_method=payload.get("buyback_method"),
                )
            )

    event = by_type.get("retirement")
    if event is not None:
        payload = event.payload or {}
        if payload.get("retirement_date") is not None:
            rows.append(
                Retirement(
                    url=url,
                    code=code,
                    disclosure_date=disclosure_date,
                    retirement_date=payload["retirement_date"],
                    company_name=company_name,
                    share_type=payload.get("share_type"),
                    retirement_shares=payload.get("retirement_shares"),
                )
            )

    detected_type = (
        "buyback_announcement"
        if "new_plan" in by_type
        else "buyback_progress"
        if "progress" in by_type
        else "buyback_completion"
        if "completion" in by_type
        else "retirement"
        if "retirement" in by_type
        else "other"
    )
    parse_status = "saved" if rows else "skipped"

    def write() -> bool:
        session.add(
            IsChecked(
                code=code,
                url=url,
                detected_type=detected_type,
                parse_status=parse_status,
            )
        )
        session.add_all(rows)
        session.flush()
        return True

    if rerun:
        return adopt_result(
            session,
            result_type=BUYBACK_RESULT_TYPE,
            tables=BUYBACK_TABLES,
            url=url,
            code=code,
            extraction_status=parse_status,
            run_ids=[],
            write_current=write,
            status_column="parse_status",
        )
    try:
        write()
        session.commit()
        return True
    except Exception as exc:
        session.rollback()
        logger.error(f"[LegacyCompatibility] 保存失敗: {url} {exc!r}")
        return False
