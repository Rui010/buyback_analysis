"""Run the provenance-aware buyback events extraction and quote validation stage."""

from __future__ import annotations

from dataclasses import dataclass

from tdnet_provenance.usecase.provenance_recorder import (
    module_llm_settings,
    run_llm_stage,
    text_hash,
)

from buyback_analysis.usecase import extract_buyback_events as extraction_module
from buyback_analysis.usecase.event_schemas import BuybackEventExtraction
from buyback_analysis.usecase.extract_buyback_events import extract_buyback_events
from buyback_analysis.usecase.validate_event_quotes import (
    QuoteValidationResult,
    validate_event_quotes,
)


@dataclass(frozen=True)
class BuybackEventStageResult:
    extraction: BuybackEventExtraction
    quote_validation: QuoteValidationResult

    @property
    def quote_verified_flags(self) -> tuple[bool, ...]:
        """Return flags in the same order as ``extraction.events``."""
        return tuple(event.verified for event in self.quote_validation.events)


def run_buyback_event_stage(
    recorder,
    source,
    *,
    title: str,
    content: str,
    code: str,
    name: str,
) -> BuybackEventStageResult | None:
    input_payload = {
        "title": title,
        "text_sha256": text_hash(content),
        "code": code,
        "name": name,
    }

    def call():
        extracted = extract_buyback_events(title, content, code, name)
        return extracted.model_dump(mode="json") if extracted is not None else None

    raw = run_llm_stage(
        recorder,
        source,
        stage="events",
        prompt_name=extraction_module.PROMPT_FILENAME,
        input_payload=input_payload,
        call=call,
        **module_llm_settings(extraction_module),
    )
    if raw is None:
        return None
    extraction = BuybackEventExtraction.model_validate(raw)
    return BuybackEventStageResult(
        extraction=extraction,
        quote_validation=validate_event_quotes(extraction, content),
    )
