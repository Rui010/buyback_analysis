from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from buyback_analysis.usecase.event_schemas import BuybackEventExtraction
from buyback_analysis.usecase.run_buyback_event_stage import run_buyback_event_stage
from tdnet_provenance.usecase.provenance_recorder import text_hash


@patch("buyback_analysis.usecase.run_buyback_event_stage.run_llm_stage")
@patch("buyback_analysis.usecase.run_buyback_event_stage.extract_buyback_events")
def test_stage_records_events_contract_and_validates_quotes(mock_extract, mock_run):
    extraction = BuybackEventExtraction.model_validate(
        {
            "events": [
                {"event_type": "new_plan", "source_quote": "自己株式の取得を決議しました。", "payload": {}}
            ]
        }
    )
    mock_extract.return_value = extraction
    mock_run.side_effect = lambda *args, **kwargs: kwargs["call"]()
    recorder = MagicMock()
    source = SimpleNamespace(source_hash="source-hash")

    result = run_buyback_event_stage(
        recorder,
        source,
        title="title",
        content="当社は自己株式の取得を決議しました。",
        code="1234",
        name="Example",
    )

    assert result.extraction == extraction
    assert result.quote_validation.events[0].verified is True
    assert result.quote_verified_flags == (True,)
    kwargs = mock_run.call_args.kwargs
    assert kwargs["stage"] == "events"
    assert kwargs["prompt_name"] == "buyback_events.md"
    assert kwargs["input_payload"] == {
        "title": "title",
        "text_sha256": text_hash("当社は自己株式の取得を決議しました。"),
        "code": "1234",
        "name": "Example",
    }
    assert kwargs["generation_config"]["temperature"] == 0
    assert kwargs["extractor_version"] == "buyback_events_text:5"


@patch("buyback_analysis.usecase.run_buyback_event_stage.run_llm_stage")
def test_stage_returns_none_when_extraction_fails(mock_run):
    mock_run.return_value = None

    result = run_buyback_event_stage(
        None,
        None,
        title="title",
        content="content",
        code="1234",
        name="Example",
    )

    assert result is None
