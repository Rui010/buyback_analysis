import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from google import genai
from google.genai._transformers import t_schema
from google.genai.errors import APIError

from buyback_analysis.usecase import extract_buyback_events as module
from buyback_analysis.usecase.event_schemas import BuybackEventExtraction


def _response(payload):
    return SimpleNamespace(text=json.dumps(payload, ensure_ascii=False))


@patch.object(module, "report_llm_response")
@patch.object(module, "genai")
def test_extracts_multiple_typed_events(mock_genai, mock_report, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    client = MagicMock()
    mock_genai.Client.return_value = client
    response = _response(
        {
            "events": [
                {"event_type": "completion", "source_quote": "取得を終了した。", "payload": {}},
                {"event_type": "new_plan", "source_quote": "新たな取得枠を設定した。", "payload": {}},
            ]
        }
    )
    client.models.generate_content.return_value = response

    result = module.extract_buyback_events("title", "content", "1234", "Example")

    assert isinstance(result, BuybackEventExtraction)
    assert [event.event_type.value for event in result.events] == ["completion", "new_plan"]
    kwargs = client.models.generate_content.call_args.kwargs
    assert kwargs["config"] == module.GENERATION_CONFIG
    assert kwargs["config"]["response_schema"] is module.LlmBuybackEventExtraction
    mock_report.assert_called_once_with(response)


@patch.object(module, "report_llm_response")
@patch.object(module, "genai")
def test_transport_superset_fields_are_removed_for_each_strict_payload(
    mock_genai, mock_report, monkeypatch
):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    client = MagicMock()
    mock_genai.Client.return_value = client
    client.models.generate_content.return_value = _response(
        {
            "events": [
                {
                    "event_type": "progress",
                    "source_quote": "取得状況を報告します。",
                    "payload": {
                        "cumulative_shares_acquired": 10,
                        "executed_shares": 0,
                        "executed_amount_yen": 0,
                    },
                },
                {
                    "event_type": "completion",
                    "source_quote": "取得を終了しました。",
                    "payload": {"shares_acquired": 0, "description": "取得枠の終了"},
                },
                {
                    "event_type": "execution_notice",
                    "source_quote": "買付けを実施します。",
                    "payload": {
                        "subtype": "planned",
                        "related_to_buyback_plan": True,
                    },
                },
            ]
        }
    )

    result = module.extract_buyback_events("title", "content", "1234", "Example")

    assert result.events[0].payload.cumulative_shares_acquired == 10
    assert result.events[1].payload.shares_acquired == 0
    assert result.events[2].payload.subtype.value == "planned"


def test_generation_contract_has_stable_version_and_zero_temperature():
    assert module.EXTRACTOR_VERSION == "buyback_events_text:4"
    assert module.GENERATION_CONFIG["temperature"] == 0
    assert module.PROMPT_FILENAME == "buyback_events.md"


def test_generation_schema_is_convertible_by_installed_google_genai_sdk():
    client = genai.Client(api_key="test-key")

    converted = t_schema(client._api_client, module.GENERATION_CONFIG["response_schema"])

    assert converted is not None


def test_requires_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(module, "load_dotenv", lambda: None)

    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        module.extract_buyback_events("title", "content", "1234", "Example")


@patch.object(module.logger, "error")
@patch.object(module, "report_llm_response")
@patch.object(module, "genai")
def test_returns_none_for_invalid_json(mock_genai, mock_report, mock_error, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    client = MagicMock()
    mock_genai.Client.return_value = client
    response = SimpleNamespace(text="not-json")
    client.models.generate_content.return_value = response

    result = module.extract_buyback_events("title", "content", "1234", "Example")

    assert result is None
    mock_report.assert_called_once_with(response)
    mock_error.assert_called_once()


@patch.object(module.time, "sleep")
@patch.object(module, "report_llm_response")
@patch.object(module, "genai")
def test_retries_temporary_server_error(mock_genai, mock_report, mock_sleep, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    client = MagicMock()
    mock_genai.Client.return_value = client
    response = _response({"events": []})
    client.models.generate_content.side_effect = [
        APIError(503, {"error": {"message": "unavailable"}}),
        response,
    ]

    result = module.extract_buyback_events("title", "content", "1234", "Example")

    assert result == BuybackEventExtraction(events=[])
    assert client.models.generate_content.call_count == 2
    mock_sleep.assert_called_once_with(60)
    mock_report.assert_called_once_with(response)


@patch.object(module, "genai")
def test_unexpected_attribute_error_is_not_hidden(mock_genai, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    client = MagicMock()
    mock_genai.Client.return_value = client
    client.models.generate_content.return_value = object()

    with pytest.raises(AttributeError):
        module.extract_buyback_events("title", "content", "1234", "Example")


@patch.object(module.logger, "error")
@patch.object(module, "report_llm_response")
@patch.object(module, "genai")
def test_returns_none_when_response_text_is_none(
    mock_genai, mock_report, mock_error, monkeypatch
):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    client = MagicMock()
    mock_genai.Client.return_value = client
    response = SimpleNamespace(text=None)
    client.models.generate_content.return_value = response

    result = module.extract_buyback_events("title", "content", "1234", "Example")

    assert result is None
    mock_report.assert_called_once_with(response)
    mock_error.assert_called_once()


@patch.object(module.time, "sleep")
@patch.object(module, "genai")
def test_raises_after_three_temporary_server_errors(mock_genai, mock_sleep, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    client = MagicMock()
    mock_genai.Client.return_value = client
    error = APIError(503, {"error": {"message": "unavailable"}})
    client.models.generate_content.side_effect = [error, error, error]

    with pytest.raises(APIError):
        module.extract_buyback_events("title", "content", "1234", "Example")

    assert client.models.generate_content.call_count == 3
    assert [item.args for item in mock_sleep.call_args_list] == [(60,), (60,)]
