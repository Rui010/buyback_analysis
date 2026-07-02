import json
from unittest.mock import MagicMock, patch

import pytest
from google.genai.errors import APIError

from forecast_revision_analysis.usecase.extract_forecast_revision_stage1 import (
    extract_forecast_revision_stage1,
)
from forecast_revision_analysis.usecase.schemas import Stage1Extraction


VALID_JSON = json.dumps(
    {
        "prev_forecast_date": "2026-02-13",
        "value_unit": "百万円",
        "periods": [
            {
                "period_type": "4q",
                "fiscal_year": 2026,
                "consolidation_type": "consolidated",
                "metric_name": "sales",
                "label_raw": "売上高",
                "prev_value": 594000.0,
                "prev_value_upper": None,
                "curr_value": 778000.0,
                "curr_value_upper": None,
                "prev_year_actual": 489000.0,
            }
        ],
        "reason_raw": "修正理由の原文",
    },
    ensure_ascii=False,
)


@pytest.fixture(autouse=True)
def _no_sleep():
    with patch("forecast_revision_analysis.usecase.extract_forecast_revision_stage1.time.sleep"):
        yield


@pytest.fixture(autouse=True)
def _no_load_dotenv():
    # .envに実際のGEMINI_API_KEYが設定されていると、load_dotenv()がmonkeypatch.delenv()後の
    # 環境変数を上書きしてしまうため、load_dotenv自体を無効化してテストを環境非依存にする
    with patch("forecast_revision_analysis.usecase.extract_forecast_revision_stage1.load_dotenv"):
        yield


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key")


class TestExtractForecastRevisionStage1:

    def test_no_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        with pytest.raises(ValueError):
            extract_forecast_revision_stage1(title="t", content="c", code="5803", name="n")

    def test_success_returns_type_and_data(self):
        mock_response = MagicMock()
        mock_response.text = VALID_JSON
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        with patch(
            "forecast_revision_analysis.usecase.extract_forecast_revision_stage1.genai.Client",
            return_value=mock_client,
        ):
            result = extract_forecast_revision_stage1(title="t", content="c", code="5803", name="n")

        assert result["type"] == "FORECAST_REVISION"
        assert result["data"]["prev_forecast_date"] == "2026-02-13"
        assert result["data"]["periods"][0]["metric_name"] == "sales"

    def test_config_uses_response_schema(self):
        mock_response = MagicMock()
        mock_response.text = VALID_JSON
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        with patch(
            "forecast_revision_analysis.usecase.extract_forecast_revision_stage1.genai.Client",
            return_value=mock_client,
        ):
            extract_forecast_revision_stage1(title="t", content="c", code="5803", name="n")

        _, kwargs = mock_client.models.generate_content.call_args
        assert kwargs["config"]["response_schema"] is Stage1Extraction
        assert kwargs["config"]["response_mime_type"] == "application/json"
        assert kwargs["config"]["temperature"] == 0.0

    def test_strips_json_code_fence(self):
        mock_response = MagicMock()
        mock_response.text = f"```json\n{VALID_JSON}\n```"
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        with patch(
            "forecast_revision_analysis.usecase.extract_forecast_revision_stage1.genai.Client",
            return_value=mock_client,
        ):
            result = extract_forecast_revision_stage1(title="t", content="c", code="5803", name="n")

        assert result["data"]["prev_forecast_date"] == "2026-02-13"

    def test_json_decode_error_returns_none_after_retries(self):
        mock_response = MagicMock()
        mock_response.text = "not a json"
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        with patch(
            "forecast_revision_analysis.usecase.extract_forecast_revision_stage1.genai.Client",
            return_value=mock_client,
        ):
            result = extract_forecast_revision_stage1(title="t", content="c", code="5803", name="n")

        assert result is None
        assert mock_client.models.generate_content.call_count == 3

    def test_server_error_retries_then_succeeds(self):
        mock_response = MagicMock()
        mock_response.text = VALID_JSON
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = [
            APIError(503, {"error": {"message": "unavailable"}}),
            mock_response,
        ]

        with patch(
            "forecast_revision_analysis.usecase.extract_forecast_revision_stage1.genai.Client",
            return_value=mock_client,
        ):
            result = extract_forecast_revision_stage1(title="t", content="c", code="5803", name="n")

        assert result["data"]["prev_forecast_date"] == "2026-02-13"
        assert mock_client.models.generate_content.call_count == 2

    def test_server_error_exhausts_retries_raises_system_exit(self):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = APIError(
            503, {"error": {"message": "unavailable"}}
        )

        with patch(
            "forecast_revision_analysis.usecase.extract_forecast_revision_stage1.genai.Client",
            return_value=mock_client,
        ):
            with pytest.raises(SystemExit):
                extract_forecast_revision_stage1(title="t", content="c", code="5803", name="n")

        assert mock_client.models.generate_content.call_count == 3

    def test_rate_limit_error_raises_system_exit_immediately(self):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = APIError(
            429, {"error": {"message": "rate limited"}}
        )

        with patch(
            "forecast_revision_analysis.usecase.extract_forecast_revision_stage1.genai.Client",
            return_value=mock_client,
        ):
            with pytest.raises(SystemExit):
                extract_forecast_revision_stage1(title="t", content="c", code="5803", name="n")

        assert mock_client.models.generate_content.call_count == 1

    def test_unexpected_error_returns_none(self):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = RuntimeError("unexpected")

        with patch(
            "forecast_revision_analysis.usecase.extract_forecast_revision_stage1.genai.Client",
            return_value=mock_client,
        ):
            result = extract_forecast_revision_stage1(title="t", content="c", code="5803", name="n")

        assert result is None
        assert mock_client.models.generate_content.call_count == 1
