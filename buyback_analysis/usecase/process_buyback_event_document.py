"""Testable orchestration for one verified Phase 1 buyback document."""

from __future__ import annotations

from buyback_analysis.usecase.run_buyback_event_stage import run_buyback_event_stage
from buyback_analysis.usecase.save_buyback_event_result import save_buyback_event_result


def process_buyback_event_document(
    session,
    recorder,
    source,
    *,
    title: str,
    content: str,
    code: str,
    name: str,
    url: str,
    disclosure_datetime: str | None,
) -> bool:
    """Extract, quote-check, adopt and relink a recorder-started document."""

    stage_result = run_buyback_event_stage(
        recorder,
        source,
        title=title,
        content=content,
        code=code,
        name=name,
    )
    if stage_result is None:
        return False
    return save_buyback_event_result(
        session,
        code=code,
        url=url,
        document_title=title,
        disclosure_datetime=disclosure_datetime,
        extraction=stage_result.extraction,
        quote_verified=stage_result.quote_verified_flags,
        run_ids=recorder.document_run_ids,
        clock=recorder.clock,
    )
