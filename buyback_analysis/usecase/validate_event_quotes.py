"""Verify extracted source quotes against the actual source text."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from buyback_analysis.usecase.event_schemas import (
    BuybackEventExtraction,
    ExtractedBuybackEvent,
)


MIN_SOURCE_QUOTE_CHARS = 10


@dataclass(frozen=True)
class EventQuoteValidation:
    event: ExtractedBuybackEvent
    verified: bool
    reason_code: str


@dataclass(frozen=True)
class QuoteValidationResult:
    events: tuple[EventQuoteValidation, ...]


def _normalize_for_quote_match(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", "", normalized)


def validate_event_quotes(
    extraction: BuybackEventExtraction, source_text: str
) -> QuoteValidationResult:
    """Retain every event while marking whether its quote exists in source text."""

    normalized_source = _normalize_for_quote_match(source_text)
    results = []
    for event in extraction.events:
        normalized_quote = _normalize_for_quote_match(event.source_quote)
        verified = (
            len(normalized_quote) >= MIN_SOURCE_QUOTE_CHARS
            and normalized_quote in normalized_source
        )
        results.append(
            EventQuoteValidation(
                event=event,
                verified=verified,
                reason_code=(
                    "SOURCE_QUOTE_VERIFIED"
                    if verified
                    else "SOURCE_QUOTE_NOT_FOUND"
                ),
            )
        )
    return QuoteValidationResult(events=tuple(results))
