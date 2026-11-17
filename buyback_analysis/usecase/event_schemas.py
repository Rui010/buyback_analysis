"""Pydantic response schemas for Phase 1 multi-event buyback extraction."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


NonBlankString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class EventType(str, Enum):
    NEW_PLAN = "new_plan"
    AMENDMENT = "amendment"
    EXECUTION_NOTICE = "execution_notice"
    PROGRESS = "progress"
    COMPLETION = "completion"
    SUPPLEMENT = "supplement"
    EQUITY_COMPENSATION = "equity_compensation"
    RETIREMENT = "retirement"
    OTHER_PARTY_TRANSACTION = "other_party_transaction"
    OTHER = "other"


class ExecutionNoticeSubtype(str, Enum):
    PLANNED = "planned"
    PRICE_DETERMINED = "price_determined"
    RESULT = "result"


class PayloadBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NewPlanPayload(PayloadBase):
    company_own_transaction: Optional[bool] = None
    independent_resolution: Optional[bool] = None
    buyback_shares: Optional[int] = None
    buyback_amount_yen: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    buyback_method: Optional[str] = None
    purpose: Optional[str] = None
    share_type: Optional[str] = None


class AmendmentPayload(PayloadBase):
    previous_buyback_shares: Optional[int] = None
    changed_buyback_shares: Optional[int] = None
    previous_buyback_amount_yen: Optional[int] = None
    changed_buyback_amount_yen: Optional[int] = None
    previous_start_date: Optional[str] = None
    changed_start_date: Optional[str] = None
    previous_end_date: Optional[str] = None
    changed_end_date: Optional[str] = None
    previous_buyback_method: Optional[str] = None
    changed_buyback_method: Optional[str] = None


class ExecutionNoticePayload(PayloadBase):
    subtype: ExecutionNoticeSubtype
    execution_date: Optional[str] = None
    planned_buyback_shares: Optional[int] = None
    planned_buyback_amount_yen: Optional[int] = None
    executed_shares: Optional[int] = None
    executed_amount_yen: Optional[int] = None
    price_per_share_yen: Optional[float] = None
    buyback_method: Optional[str] = None


class ProgressPayload(PayloadBase):
    cumulative_shares_acquired: Optional[int] = None
    cumulative_amount_spent_yen: Optional[int] = None
    period_start: Optional[str] = None
    period_end: Optional[str] = None


class CompletionPayload(PayloadBase):
    shares_acquired: Optional[float] = None
    amount_spent_yen: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    buyback_method: Optional[str] = None


class SupplementPayload(PayloadBase):
    description: Optional[str] = None


class EquityCompensationPayload(PayloadBase):
    uses_existing_buyback_plan: Optional[bool] = None
    description: Optional[str] = None
    buyback_shares: Optional[int] = None
    buyback_amount_yen: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class RetirementPayload(PayloadBase):
    related_to_buyback_plan: Optional[bool] = None
    retirement_shares: Optional[int] = None
    retirement_date: Optional[str] = None
    share_type: Optional[str] = None


class OtherPartyTransactionPayload(PayloadBase):
    other_party_code: Optional[str] = None
    other_party_name: Optional[str] = None
    transaction_role: Optional[str] = None
    description: Optional[str] = None


class OtherPayload(PayloadBase):
    description: Optional[str] = None


class EventBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_date: Optional[str] = Field(
        default=None, description="このイベントが発生又は公表された日（YYYY-MM-DD）"
    )
    resolution_date: Optional[str] = Field(
        default=None,
        description=(
            "本文でこのイベントの根拠として明示された取得決議日（YYYY-MM-DD）。"
            "amendmentでは変更元の取得決議日を入れ、変更を決めた日はevent_dateへ入れる"
        ),
    )
    referenced_document_date: Optional[str] = Field(
        default=None,
        description="本文が参照する別文書の開示日（決議日ではない、YYYY-MM-DD）",
    )
    referenced_document_title: Optional[str] = Field(
        default=None, description="本文が明示的に参照する別文書の題名"
    )
    source_quote: NonBlankString
    source_page: Optional[int] = Field(default=None, ge=1)
    source_section: Optional[str] = None


class NewPlanEvent(EventBase):
    event_type: Literal[EventType.NEW_PLAN]
    payload: NewPlanPayload


class AmendmentEvent(EventBase):
    event_type: Literal[EventType.AMENDMENT]
    payload: AmendmentPayload


class ExecutionNoticeEvent(EventBase):
    event_type: Literal[EventType.EXECUTION_NOTICE]
    payload: ExecutionNoticePayload


class ProgressEvent(EventBase):
    event_type: Literal[EventType.PROGRESS]
    payload: ProgressPayload


class CompletionEvent(EventBase):
    event_type: Literal[EventType.COMPLETION]
    payload: CompletionPayload


class SupplementEvent(EventBase):
    event_type: Literal[EventType.SUPPLEMENT]
    payload: SupplementPayload


class EquityCompensationEvent(EventBase):
    event_type: Literal[EventType.EQUITY_COMPENSATION]
    payload: EquityCompensationPayload


class RetirementEvent(EventBase):
    event_type: Literal[EventType.RETIREMENT]
    payload: RetirementPayload


class OtherPartyTransactionEvent(EventBase):
    event_type: Literal[EventType.OTHER_PARTY_TRANSACTION]
    payload: OtherPartyTransactionPayload


class OtherEvent(EventBase):
    event_type: Literal[EventType.OTHER]
    payload: OtherPayload


ExtractedBuybackEvent = Annotated[
    Union[
        NewPlanEvent,
        AmendmentEvent,
        ExecutionNoticeEvent,
        ProgressEvent,
        CompletionEvent,
        SupplementEvent,
        EquityCompensationEvent,
        RetirementEvent,
        OtherPartyTransactionEvent,
        OtherEvent,
    ],
    Field(discriminator="event_type"),
]


class BuybackEventExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[ExtractedBuybackEvent] = Field(default_factory=list)


class LlmEventPayload(BaseModel):
    """SDK-compatible superset; strict event-specific validation happens afterward."""

    company_own_transaction: Optional[bool] = None
    independent_resolution: Optional[bool] = None
    buyback_shares: Optional[int] = None
    buyback_amount_yen: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    buyback_method: Optional[str] = None
    purpose: Optional[str] = None
    share_type: Optional[str] = None
    previous_buyback_shares: Optional[int] = None
    changed_buyback_shares: Optional[int] = None
    previous_buyback_amount_yen: Optional[int] = None
    changed_buyback_amount_yen: Optional[int] = None
    previous_start_date: Optional[str] = None
    changed_start_date: Optional[str] = None
    previous_end_date: Optional[str] = None
    changed_end_date: Optional[str] = None
    previous_buyback_method: Optional[str] = None
    changed_buyback_method: Optional[str] = None
    subtype: Optional[ExecutionNoticeSubtype] = None
    execution_date: Optional[str] = None
    planned_buyback_shares: Optional[int] = None
    planned_buyback_amount_yen: Optional[int] = None
    executed_shares: Optional[int] = None
    executed_amount_yen: Optional[int] = None
    price_per_share_yen: Optional[float] = None
    cumulative_shares_acquired: Optional[int] = None
    cumulative_amount_spent_yen: Optional[int] = None
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    shares_acquired: Optional[float] = None
    amount_spent_yen: Optional[int] = None
    description: Optional[str] = None
    uses_existing_buyback_plan: Optional[bool] = None
    related_to_buyback_plan: Optional[bool] = None
    retirement_shares: Optional[int] = None
    retirement_date: Optional[str] = None
    other_party_code: Optional[str] = None
    other_party_name: Optional[str] = None
    transaction_role: Optional[str] = None


class LlmBuybackEvent(BaseModel):
    """Flat event shape accepted by google-genai 1.14.0."""

    event_type: EventType
    event_date: Optional[str] = None
    resolution_date: Optional[str] = None
    referenced_document_date: Optional[str] = None
    referenced_document_title: Optional[str] = None
    source_quote: str
    source_page: Optional[int] = Field(default=None, ge=1)
    source_section: Optional[str] = None
    payload: LlmEventPayload = Field(default_factory=LlmEventPayload)


class LlmBuybackEventExtraction(BaseModel):
    """Transport schema sent to Gemini; convert to BuybackEventExtraction on receipt."""

    events: list[LlmBuybackEvent] = Field(default_factory=list)


STRICT_PAYLOAD_MODELS: dict[EventType, type[PayloadBase]] = {
    EventType.NEW_PLAN: NewPlanPayload,
    EventType.AMENDMENT: AmendmentPayload,
    EventType.EXECUTION_NOTICE: ExecutionNoticePayload,
    EventType.PROGRESS: ProgressPayload,
    EventType.COMPLETION: CompletionPayload,
    EventType.SUPPLEMENT: SupplementPayload,
    EventType.EQUITY_COMPENSATION: EquityCompensationPayload,
    EventType.RETIREMENT: RetirementPayload,
    EventType.OTHER_PARTY_TRANSACTION: OtherPartyTransactionPayload,
    EventType.OTHER: OtherPayload,
}


def strict_extraction_from_transport(
    transport: LlmBuybackEventExtraction,
) -> BuybackEventExtraction:
    """Drop only event-inapplicable fields from the SDK-compatible payload superset."""

    strict_events = []
    for event in transport.events:
        event_data = event.model_dump(mode="json", exclude_none=True)
        allowed = STRICT_PAYLOAD_MODELS[event.event_type].model_fields
        event_data["payload"] = {
            key: value
            for key, value in event_data.get("payload", {}).items()
            if key in allowed
        }
        strict_events.append(event_data)
    return BuybackEventExtraction.model_validate({"events": strict_events})
